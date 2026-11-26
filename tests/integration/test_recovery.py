import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.features.notifications.delivery import consume
from backend.app.features.notifications.recovery import reconcile, store_event
from backend.app.features.providers.adapters.smtp import SMTPProvider
from backend.app.infrastructure.model_registry import (
    AuditEvent,
    Notification,
    NotificationAttempt,
    NotificationOutbox,
    WorkerEvent,
    WorkerHeartbeat,
    utcnow,
)
from backend.app.shared.provider_contract import ProviderError, ProviderResult
from tests.support.administration import ROOT, application, create, sign_in
from tests.support.notifications import body, prepare


def submit(client, template, headers, key):
    response = client.post(
        f"{ROOT}/notifications",
        json=body(template),
        headers={**headers, "Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["id"])


def test_safe_transient_errors_backoff_then_stop_at_three_attempts_and_replay_is_new(
    store, monkeypatch
):
    engine, factory = store
    app = application(store)
    calls = []

    def unavailable(self, message):
        calls.append(message)
        raise ProviderError("connection_failed", True, uncertain=False)

    monkeypatch.setattr(SMTPProvider, "send", unavailable)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        identifier = submit(client, template, headers, "retry-three")
        for number in range(1, 4):
            asyncio.run(
                consume(factory, app.state.settings, {"smtp": SMTPProvider}, identifier)
            )
            with Session(engine) as db:
                item = db.get(Notification, identifier)
                assert item.attempt_count == number
                assert item.status == ("retrying" if number < 3 else "failed")
                assert item.encrypted_payload is not None
                if number < 3:
                    assert item.next_attempt_at > item.updated_at
                    item.next_attempt_at = utcnow() - timedelta(seconds=1)
                    db.commit()
        assert len(calls) == 3
        detail = client.get(f"{ROOT}/notifications/{identifier}").json()
        payload = {
            "replay_key": "manual-once",
            "expected_updated_at": detail["updated_at"],
        }
        replay = client.post(f"{ROOT}/notifications/{identifier}/replay", json=payload)
        assert replay.status_code == 202, replay.text
        child = replay.json()["id"]
        assert child != str(identifier)
        assert (
            client.post(
                f"{ROOT}/notifications/{identifier}/replay", json=payload
            ).json()["id"]
            == child
        )
        monkeypatch.setattr(
            SMTPProvider,
            "send",
            lambda self, message: ProviderResult(status="accepted", message="Accepted"),
        )
        asyncio.run(
            consume(factory, app.state.settings, {"smtp": SMTPProvider}, UUID(child))
        )
        assert client.get(f"{ROOT}/notifications/{child}").json()["status"] == "sent"
        with Session(engine) as db:
            assert db.get(Notification, identifier).status == "failed"
            assert db.get(Notification, UUID(child)).replay_of_id == identifier
            assert (
                len(
                    list(
                        db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == "notification.replay"
                            )
                        )
                    )
                )
                == 1
            )


def test_permanent_failure_does_not_retry_and_expired_input_requires_actual_resupply(
    store, monkeypatch
):
    engine, factory = store
    app = application(store)

    def reject(self, message):
        raise ProviderError("authentication_failed", uncertain=False)

    monkeypatch.setattr(SMTPProvider, "send", reject)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        identifier = submit(client, template, headers, "permanent")
        asyncio.run(
            consume(factory, app.state.settings, {"smtp": SMTPProvider}, identifier)
        )
        assert (
            client.get(f"{ROOT}/notifications/{identifier}").json()["status"]
            == "failed"
        )
        with Session(engine) as db:
            item = db.get(Notification, identifier)
            item.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        asyncio.run(reconcile(factory, app.state.settings))
        with Session(engine) as db:
            assert db.get(Notification, identifier).encrypted_payload is None
        detail = client.get(f"{ROOT}/notifications/{identifier}").json()
        payload = {"replay_key": "expired", "expected_updated_at": detail["updated_at"]}
        assert (
            client.post(
                f"{ROOT}/notifications/{identifier}/replay", json=payload
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{ROOT}/notifications/{identifier}/replay",
                json={**payload, "recipient": "new@example.test", "context": {}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{ROOT}/notifications/{identifier}/replay",
                json={
                    **payload,
                    "recipient": "new@example.test",
                    "context": {"name": "Supplied"},
                },
            ).status_code
            == 202
        )


def test_recovery_fences_pre_send_owner_but_never_retries_in_flight_send_and_republishes_lost_queue(
    store,
):
    engine, factory = store
    app = application(store)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        identifiers = [submit(client, template, headers, str(i)) for i in range(4)]
        with Session(engine) as db:
            for number, identifier in enumerate(identifiers[:2]):
                item = db.get(Notification, identifier)
                item.status, item.attempt_count = "processing", 1
                item.lease_token, item.lease_expires_at = (
                    uuid4(),
                    utcnow() - timedelta(seconds=1),
                )
                item.send_started_at = utcnow() if number else None
                db.add(
                    NotificationAttempt(
                        id=uuid4(),
                        notification_id=identifier,
                        number=1,
                        status="processing",
                        retryable=False,
                        started_at=utcnow(),
                    )
                )
            outbox = db.scalar(
                select(NotificationOutbox).where(
                    NotificationOutbox.notification_id == identifiers[2]
                )
            )
            outbox.published_at = utcnow() - timedelta(minutes=2)
            db.get(Notification, identifiers[3]).expires_at = utcnow() - timedelta(
                seconds=1
            )
            db.commit()
        result = asyncio.run(reconcile(factory, app.state.settings))
        assert (
            result["recovered"]
            == result["unknown"]
            == result["expired"]
            == result["republished"]
            == 1
        )
        with Session(engine) as db:
            safe, uncertain, lost, expired = [
                db.get(Notification, value) for value in identifiers
            ]
            assert safe.status == "retrying" and safe.lease_token is None
            assert uncertain.status == "unknown" and uncertain.encrypted_payload is None
            assert expired.status == "failed" and expired.encrypted_payload is None
            assert (
                db.scalar(
                    select(NotificationOutbox).where(
                        NotificationOutbox.notification_id == lost.id
                    )
                ).published_at
                is None
            )
        unknown = client.get(f"{ROOT}/notifications/{identifiers[1]}").json()
        assert (
            client.post(
                f"{ROOT}/notifications/{identifiers[1]}/replay",
                json={"replay_key": "no", "expected_updated_at": unknown["updated_at"]},
            ).status_code
            == 409
        )


def test_provider_capacity_defers_without_consuming_attempt(store, monkeypatch):
    engine, factory = store
    app = application(store)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        active = submit(client, template, headers, "active")
        waiting = submit(client, template, headers, "waiting")
        app.state.settings.delivery_provider_concurrency = 1
        with Session(engine) as db:
            item = db.get(Notification, active)
            item.status, item.lease_expires_at = (
                "processing",
                utcnow() + timedelta(minutes=2),
            )
            db.commit()
        monkeypatch.setattr(
            SMTPProvider,
            "send",
            lambda *args: (_ for _ in ()).throw(AssertionError("must not send")),
        )
        asyncio.run(
            consume(factory, app.state.settings, {"smtp": SMTPProvider}, waiting)
        )
        with Session(engine) as db:
            item = db.get(Notification, waiting)
            assert (
                item.status == "queued"
                and item.attempt_count == 0
                and item.next_attempt_at > item.created_at
            )


def test_stale_owner_cannot_send_after_lease_is_recovered(store, monkeypatch):
    engine, factory = store
    app = application(store)
    import backend.app.features.notifications.delivery as runtime

    original_render = runtime.render_version
    sent = []

    async def expired(*args):
        # Simulate losing the lease during pre-send work, before the fencing check.
        with Session(engine) as db:
            item = db.scalar(
                select(Notification).where(Notification.status == "processing")
            )
            item.lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        await reconcile(factory, app.state.settings)
        return await original_render(*args)

    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        identifier = submit(client, template, headers, "fence")
        monkeypatch.setattr(runtime, "render_version", expired)
        monkeypatch.setattr(SMTPProvider, "send", lambda *args: sent.append(True))
        asyncio.run(
            consume(factory, app.state.settings, {"smtp": SMTPProvider}, identifier)
        )
        assert not sent
        assert (
            client.get(f"{ROOT}/notifications/{identifier}").json()["status"]
            == "retrying"
        )


def test_operations_scope_replay_permissions_and_sanitized_events(store, monkeypatch):
    engine, factory = store
    app = application(store)
    with TestClient(app) as client:
        project, _, _, template, _, _, headers = prepare(client, app)
        identifier = submit(client, template, headers, "scope")
        with Session(engine) as db:
            item = db.get(Notification, identifier)
            item.status = "failed"
            db.commit()
        create(
            client,
            f"/projects/{project['id']}/members",
            email="viewer@example.test",
            password="Synthetic viewer password",
            role="viewer",
        )
        hidden = create(client, "/projects", name="Hidden operations")
        create(
            client,
            f"/projects/{hidden['id']}/members",
            email="foreign@example.test",
            password="Synthetic foreign password",
            role="viewer",
        )
        asyncio.run(
            store_event(
                factory,
                {
                    "type": "worker-heartbeat",
                    "hostname": "email@test",
                    "args": "RAW-SECRET",
                },
            )
        )
        asyncio.run(
            store_event(
                factory,
                {
                    "type": "task-failed",
                    "hostname": "email@test",
                    "uuid": str(identifier),
                    "exception": "RAW-SECRET",
                    "traceback": "RAW-SECRET",
                },
            )
        )
        with Session(engine) as db:
            db.get(WorkerHeartbeat, "email@test").last_seen = utcnow() - timedelta(
                minutes=2
            )
            db.commit()
            assert "RAW-SECRET" not in str(
                [row.__dict__ for row in db.scalars(select(WorkerEvent))]
            )
        report = client.get(f"{ROOT}/operations").json()
        assert (
            report["counts"]["failed"] == 1 and report["workers"][0]["state"] == "stale"
        )
        assert "RAW-SECRET" not in str(report)
        assert client.get(f"{ROOT}/operations/metrics").status_code == 200
        with TestClient(app) as viewer:
            sign_in(viewer, "viewer@example.test", "Synthetic viewer password")
            detail = viewer.get(f"{ROOT}/notifications/{identifier}").json()
            assert not detail["replay_allowed"]
            assert (
                viewer.post(
                    f"{ROOT}/notifications/{identifier}/replay",
                    json={
                        "replay_key": "denied",
                        "expected_updated_at": detail["updated_at"],
                    },
                ).status_code
                == 403
            )
            scoped = viewer.get(f"{ROOT}/operations").json()
            assert (
                scoped["counts"]["failed"] == 1
                and scoped["workers"] is None
                and not scoped["events"]
            )
            assert viewer.get(f"{ROOT}/operations/metrics").status_code == 403
            assert viewer.get(f"{ROOT}/operations/audit").json()["total"] == 0
        with TestClient(app) as foreign:
            sign_in(foreign, "foreign@example.test", "Synthetic foreign password")
            assert foreign.get(f"{ROOT}/operations").json()["counts"]["failed"] == 0
            assert (
                foreign.get(f"{ROOT}/operations?project_id={project['id']}").status_code
                == 404
            )


def test_smtp_classifies_rejection_and_disconnect_before_or_during_send(monkeypatch):
    import smtplib

    import pytest

    from backend.app.features.providers.adapters.smtp import SMTPConfig
    from backend.app.shared.provider_contract import EmailMessage

    config = SMTPConfig(
        host="mailpit", port=1025, tls="none", sender="demo@example.test"
    )
    message = EmailMessage(recipient="demo@example.test", subject="Demo", text="Hello")

    class Transport:
        def ehlo_or_helo_if_needed(self):
            pass

        def send_message(self, *args, **kwargs):
            raise smtplib.SMTPServerDisconnected("RAW-SECRET")

        def close(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: Transport())
    with pytest.raises(ProviderError) as raised:
        SMTPProvider(config).send(message)
    assert raised.value.uncertain and raised.value.retryable

    def disconnected(*args, **kwargs):
        raise OSError("RAW-SECRET")

    monkeypatch.setattr(smtplib, "SMTP", disconnected)
    with pytest.raises(ProviderError) as raised:
        SMTPProvider(config).send(message)
    assert not raised.value.uncertain and raised.value.retryable

    def rejected(self, *args, **kwargs):
        raise smtplib.SMTPDataError(451, b"RAW-SECRET")

    monkeypatch.setattr(smtplib, "SMTP", lambda *args, **kwargs: Transport())
    monkeypatch.setattr(Transport, "send_message", rejected)
    with pytest.raises(ProviderError) as raised:
        SMTPProvider(config).send(message)
    assert (
        not raised.value.uncertain
        and raised.value.retryable
        and str(raised.value) == "smtp_rejected"
    )


def test_metrics_requires_nonempty_explicit_token_even_with_admin_cookie(store):
    from pydantic import SecretStr

    app = application(store)
    with TestClient(app) as client:
        sign_in(client)
        app.state.settings.metrics_token = SecretStr("")
        assert (
            client.get(
                f"{ROOT}/operations/metrics", headers={"Authorization": "Bearer "}
            ).status_code
            == 401
        )
        app.state.settings.metrics_token = SecretStr("synthetic-metrics-credential")
        assert (
            client.get(
                f"{ROOT}/operations/metrics", headers={"Authorization": "Bearer wrong"}
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"{ROOT}/operations/metrics",
                headers={"Authorization": "Bearer synthetic-metrics-credential"},
            ).status_code
            == 200
        )

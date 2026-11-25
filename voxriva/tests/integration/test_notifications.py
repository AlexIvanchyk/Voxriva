import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.features.notifications.delivery import consume, publish_once
from backend.app.features.providers.adapters.smtp import SMTPProvider
from backend.app.infrastructure.model_registry import (
    Notification,
    NotificationAttempt,
    NotificationOutbox,
)
from backend.app.shared.provider_contract import ProviderError, ProviderResult
from tests.support.administration import ROOT, application, create, sign_in
from tests.support.notifications import body, count, prepare


def test_delivery_acceptance_is_atomic_idempotent_and_never_uses_preview_fixture(store):
    engine, _ = store
    app = application(store)
    with TestClient(app) as client:
        _, _, _, template, version, smtp, headers = prepare(client, app)
        missing = client.post(
            f"{ROOT}/notifications", json=body(template, context={}), headers=headers
        )
        assert missing.status_code == 422
        assert count(engine, Notification) == count(engine, NotificationOutbox) == 0
        response = client.post(
            f"{ROOT}/notifications", json=body(template), headers=headers
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert (
            accepted["template_version_id"] == version["id"]
            and accepted["provider_revision_id"] == smtp["latest"]["id"]
        )
        assert (
            client.post(
                f"{ROOT}/notifications", json=body(template), headers=headers
            ).json()["id"]
            == accepted["id"]
        )
        assert (
            client.post(
                f"{ROOT}/notifications",
                json=body(template, context={"name": "Changed"}),
                headers=headers,
            ).status_code
            == 409
        )
        assert count(engine, Notification) == count(engine, NotificationOutbox) == 1
        with Session(engine) as db:
            saved = db.get(Notification, UUID(accepted["id"]))
            assert (
                "recipient.private" not in saved.encrypted_payload
                and "RuntimeOnly" not in saved.encrypted_payload
            )
            assert "recipient.private" not in saved.encrypted_recipient
            assert "recipient.private" not in saved.request_hash
        status = client.get(
            f"{ROOT}/notifications/{accepted['id']}",
            headers={"Authorization": headers["Authorization"]},
        )
        assert (
            status.status_code == 200
            and "recipient.private" not in status.text
            and "RuntimeOnly" not in status.text
        )
        assert status.json()["recipient_mask"] == "r***@***"
        assert (
            client.post(f"{ROOT}/notifications", json=body(template)).status_code == 401
        )


def test_status_and_history_are_scoped_to_environment_and_dashboard_membership(store):
    app = application(store)
    with TestClient(app) as client:
        project, _, prod, template, _, _, headers = prepare(client, app)
        accepted = client.post(
            f"{ROOT}/notifications", json=body(template), headers=headers
        ).json()
        other_key = create(
            client,
            f"/projects/{project['id']}/environments/{prod['id']}/keys",
            name="Other environment",
        )
        other_headers = {"Authorization": f"Bearer {other_key['key']}"}
        assert (
            client.get(
                f"{ROOT}/notifications/{accepted['id']}", headers=other_headers
            ).status_code
            == 404
        )
        create(
            client,
            f"/projects/{project['id']}/members",
            email="history@example.test",
            password="Synthetic history password",
            role="viewer",
        )
        private = create(client, "/projects", name="Private history")
        create(
            client,
            f"/projects/{private['id']}/members",
            email="foreign@example.test",
            password="Synthetic foreign password",
            role="viewer",
        )
        with TestClient(app) as viewer:
            sign_in(viewer, "history@example.test", "Synthetic history password")
            assert viewer.get(f"{ROOT}/notifications").json()["total"] == 1
            assert (
                viewer.get(f"{ROOT}/notifications/{accepted['id']}").status_code == 200
            )
            assert (
                viewer.get(
                    f"{ROOT}/notifications?project_id={private['id']}"
                ).status_code
                == 404
            )
        with TestClient(app) as foreign:
            sign_in(foreign, "foreign@example.test", "Synthetic foreign password")
            assert foreign.get(f"{ROOT}/notifications").json()["total"] == 0
            assert (
                foreign.get(f"{ROOT}/notifications/{accepted['id']}").status_code == 404
            )


def test_dashboard_recipient_email_search_is_scoped_and_paginated(store):
    engine, _ = store
    app = application(store)
    with TestClient(app) as client:
        project, _, _, template, _, _, headers = prepare(client, app)
        identifiers = []
        for index, email in enumerate(
            ["first@example.test", "second@example.test", "other@elsewhere.test"]
        ):
            response = client.post(
                f"{ROOT}/notifications",
                json=body(template, recipient=email),
                headers={**headers, "Idempotency-Key": f"email-search-{index}"},
            )
            assert response.status_code == 202
            identifiers.append(response.json()["id"])
        history = client.get(f"{ROOT}/notifications").json()
        assert {row["recipient_email"] for row in history["items"]} == {
            "first@example.test",
            "second@example.test",
            "other@elsewhere.test",
        }
        assert "RuntimeOnly" not in str(history)
        assert (
            client.get(f"{ROOT}/notifications/{identifiers[0]}").json()[
                "recipient_email"
            ]
            == "first@example.test"
        )
        api_detail = client.get(
            f"{ROOT}/notifications/{identifiers[0]}",
            headers={"Authorization": headers["Authorization"]},
        ).json()
        assert api_detail["recipient_email"] is None
        results = client.get(
            f"{ROOT}/notifications",
            params={"recipient_email": "  EXAMPLE.TEST  ", "limit": 1, "offset": 1},
        ).json()
        assert results["total"] == 2 and len(results["items"]) == 1
        assert results["items"][0]["recipient_email"] == "first@example.test"
        assert (
            client.get(
                f"{ROOT}/notifications", params={"recipient_email": "first@"}
            ).json()["total"]
            == 1
        )
        assert (
            client.get(
                f"{ROOT}/notifications", params={"recipient_email": "missing"}
            ).json()["total"]
            == 0
        )
        assert (
            client.get(
                f"{ROOT}/notifications",
                params={"recipient_email": "example", "channel": "push"},
            ).json()["total"]
            == 0
        )
        private = create(client, "/projects", name="Other email history")
        create(
            client,
            f"/projects/{private['id']}/members",
            email="email-viewer@example.test",
            password="Synthetic history password",
            role="viewer",
        )
        with TestClient(app) as foreign:
            sign_in(foreign, "email-viewer@example.test", "Synthetic history password")
            assert (
                foreign.get(
                    f"{ROOT}/notifications", params={"recipient_email": "first@"}
                ).json()["total"]
                == 0
            )
        with Session(engine) as db:
            item = db.get(Notification, UUID(identifiers[0]))
            item.encrypted_payload = None
            db.commit()
        assert (
            client.get(f"{ROOT}/notifications/{identifiers[0]}").json()[
                "recipient_email"
            ]
            == "first@example.test"
        )
        assert (
            client.get(
                f"{ROOT}/notifications", params={"recipient_email": "first@"}
            ).json()["total"]
            == 1
        )
        with Session(engine) as db:
            item = db.get(Notification, UUID(identifiers[0]))
            item.encrypted_recipient = None
            db.commit()
        assert (
            client.get(f"{ROOT}/notifications/{identifiers[0]}").json()[
                "recipient_email"
            ]
            is None
        )


def test_outbox_publish_retries_and_duplicate_consumption_cannot_resend(
    store, monkeypatch
):
    engine, factory = store
    app = application(store)
    calls = []

    def send(self, message):
        calls.append(message)
        return ProviderResult(
            status="accepted", message="Accepted", message_id="synthetic-message-id"
        )

    monkeypatch.setattr(SMTPProvider, "send", send)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        identifier = UUID(
            client.post(
                f"{ROOT}/notifications", json=body(template), headers=headers
            ).json()["id"]
        )

        async def check():
            async def unavailable(value):
                raise OSError("synthetic broker outage")

            try:
                await publish_once(factory, unavailable)
                assert False
            except OSError:
                pass

            async def publish_id(value):
                assert value == str(identifier)

            assert await publish_once(factory, publish_id)
            assert not await publish_once(factory, publish_id)
            await consume(
                factory, app.state.settings, {"smtp": SMTPProvider}, identifier
            )
            await consume(
                factory, app.state.settings, {"smtp": SMTPProvider}, identifier
            )

        asyncio.run(check())
        assert len(calls) == 1 and calls[0].subject == "Hello RuntimeOnly"
        assert (
            client.get(f"{ROOT}/notifications/{identifier}").json()["recipient_email"]
            == "recipient.private@example.test"
        )
        assert (
            client.get(
                f"{ROOT}/notifications", params={"recipient_email": "recipient.private"}
            ).json()["total"]
            == 1
        )
        assert count(engine, NotificationAttempt) == 1
        with Session(engine) as db:
            item = db.get(Notification, identifier)
            assert item.status == "sent" and item.encrypted_payload is None
        replay = client.post(
            f"{ROOT}/notifications", json=body(template), headers=headers
        )
        assert (
            replay.status_code == 202
            and replay.json()["status"] == "sent"
            and replay.json()["replayed"]
        )
        assert len(calls) == 1


def test_provider_failure_is_sanitized_and_uncertain_send_is_not_blindly_retried(
    store, monkeypatch
):
    engine, factory = store
    app = application(store)

    def send(self, message):
        raise ProviderError("raw-secret-transport-failure", True)

    monkeypatch.setattr(SMTPProvider, "send", send)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        identifier = UUID(
            client.post(
                f"{ROOT}/notifications", json=body(template), headers=headers
            ).json()["id"]
        )
        asyncio.run(
            consume(factory, app.state.settings, {"smtp": SMTPProvider}, identifier)
        )
        result = client.get(f"{ROOT}/notifications/{identifier}")
        assert result.json()["status"] == "unknown"
        assert "raw-secret" not in result.text and "RuntimeOnly" not in result.text
        assert result.json()["recipient_email"] == "recipient.private@example.test"
        assert not result.json()["attempts"][0]["retryable"]
        with Session(engine) as db:
            assert db.get(Notification, identifier).encrypted_payload is None

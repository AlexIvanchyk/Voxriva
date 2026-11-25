"""Real PostgreSQL acceptance, outbox locks and worker fencing.

These cases deliberately use two committed connections. SQLite-backed API tests
cannot establish the SKIP LOCKED and unique-constraint behavior exercised here.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from backend.app.features.notifications.delivery import consume, publish_once
from backend.app.features.notifications.recovery import reconcile
from backend.app.features.providers.adapters.smtp import SMTPProvider
from backend.app.infrastructure.model_registry import (
    Notification,
    NotificationAttempt,
    NotificationOutbox,
    utcnow,
)
from backend.app.shared.provider_contract import ProviderResult
from tests.support.administration import ROOT, application
from tests.support.notifications import body, prepare

pytestmark = pytest.mark.postgres


def accepted_notification(store):
    app = application(store)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)
        response = client.post(
            f"{ROOT}/notifications", json=body(template), headers=headers
        )
        assert response.status_code == 202, response.text
    return app, UUID(response.json()["id"])


def test_concurrent_acceptance_has_one_notification_and_one_atomic_outbox(
    postgres_store,
):
    app = application(postgres_store)
    barrier = threading.Barrier(2)
    with TestClient(app) as client:
        _, _, _, template, _, _, headers = prepare(client, app)

        def submit():
            with TestClient(app) as delivery:
                barrier.wait(timeout=10)
                response = delivery.post(
                    f"{ROOT}/notifications", json=body(template), headers=headers
                )
                assert response.status_code == 202, response.text
                return response.json()["id"]

        with ThreadPoolExecutor(max_workers=2) as workers:
            identifiers = list(workers.map(lambda _: submit(), range(2)))
    assert identifiers[0] == identifiers[1]

    async def check():
        async with postgres_store[1]() as db:
            assert await db.scalar(select(func.count()).select_from(Notification)) == 1
            assert (
                await db.scalar(select(func.count()).select_from(NotificationOutbox))
                == 1
            )

    asyncio.run(check())


def test_outbox_skip_locked_prevents_parallel_publication_and_rollback_keeps_pending(
    postgres_store,
):
    _, identifier = accepted_notification(postgres_store)
    factory = postgres_store[1]

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def blocked_publish(value):
            calls.append(value)
            entered.set()
            await release.wait()

        first = asyncio.create_task(publish_once(factory, blocked_publish))
        await asyncio.wait_for(entered.wait(), 5)
        try:
            assert (
                await asyncio.wait_for(publish_once(factory, blocked_publish), 5)
                is False
            )
        finally:
            release.set()
            await first
        assert calls == [str(identifier)]
        async with factory() as db:
            await db.execute(update(NotificationOutbox).values(published_at=None))
            await db.commit()

        async def unavailable(_):
            raise ConnectionError("synthetic broker failure")

        try:
            await publish_once(factory, unavailable)
        except ConnectionError:
            pass
        else:
            raise AssertionError("Broker error must propagate")
        async with factory() as db:
            assert (await db.scalar(select(NotificationOutbox))).published_at is None

    asyncio.run(run())


def test_two_workers_send_once_with_a_real_database_claim(postgres_store, monkeypatch):
    app, identifier = accepted_notification(postgres_store)
    calls = []

    def send(_, message):
        calls.append(message.recipient)
        return ProviderResult(
            status="accepted",
            message="Synthetic acceptance",
            message_id="postgres-test-receipt",
        )

    monkeypatch.setattr(SMTPProvider, "send", send)

    async def run():
        await asyncio.wait_for(
            asyncio.gather(
                *[
                    consume(
                        postgres_store[1],
                        app.state.settings,
                        {"smtp": SMTPProvider},
                        identifier,
                    )
                    for _ in range(2)
                ]
            ),
            15,
        )
        async with postgres_store[1]() as db:
            assert (await db.get(Notification, identifier)).status == "sent"
            assert (
                await db.scalar(select(func.count()).select_from(NotificationAttempt))
                == 1
            )

    asyncio.run(run())
    assert calls == ["recipient.private@example.test"]


def test_recovery_skips_locked_claim_and_fences_expired_owner(postgres_store):
    app, identifier = accepted_notification(postgres_store)
    factory = postgres_store[1]
    expired_token = uuid4()

    async def run():
        async with factory() as db:
            await db.execute(
                update(Notification)
                .where(Notification.id == identifier)
                .values(
                    status="processing",
                    attempt_count=1,
                    lease_token=expired_token,
                    lease_expires_at=utcnow() - timedelta(seconds=5),
                )
            )
            db.add(
                NotificationAttempt(
                    notification_id=identifier,
                    number=1,
                    status="processing",
                    retryable=False,
                )
            )
            await db.commit()
        async with factory() as owner:
            await owner.scalar(
                select(Notification)
                .where(Notification.id == identifier)
                .with_for_update()
            )
            assert (await asyncio.wait_for(reconcile(factory, app.state.settings), 5))[
                "recovered"
            ] == 0
            await owner.rollback()
        assert (await reconcile(factory, app.state.settings))["recovered"] == 1
        async with factory() as db:
            row = await db.get(Notification, identifier)
            assert row.status == "retrying" and row.lease_token is None
            stale = await db.execute(
                update(Notification)
                .where(
                    Notification.id == identifier,
                    Notification.lease_token == expired_token,
                )
                .values(send_started_at=utcnow())
            )
            assert stale.rowcount == 0
            assert (
                await db.scalar(select(NotificationAttempt))
            ).status == "interrupted"

    asyncio.run(run())

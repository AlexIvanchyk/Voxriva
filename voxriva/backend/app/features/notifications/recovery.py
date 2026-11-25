"""Recovery policies and sanitized Celery telemetry, shared by relay and worker."""

import asyncio
import re
import threading
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.features.notifications.models import (
    Notification,
    NotificationAttempt,
    NotificationOutbox,
    WorkerEvent,
    WorkerHeartbeat,
)
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.settings import Settings


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def reschedule(db: AsyncSession, item: Notification, when: datetime) -> None:
    item.next_attempt_at = when
    outbox = await db.scalar(
        select(NotificationOutbox).where(NotificationOutbox.notification_id == item.id)
    )
    if outbox is not None:
        outbox.published_at = None


async def reconcile(
    factory: async_sessionmaker[AsyncSession], settings: Settings
) -> dict[str, int]:
    counts = {"expired": 0, "recovered": 0, "unknown": 0, "republished": 0}
    now = utcnow()
    async with factory() as db:
        rows = await db.scalars(
            select(Notification)
            .where(
                or_(
                    Notification.status.in_(["queued", "retrying"])
                    & (Notification.expires_at <= now),
                    (Notification.status == "processing")
                    & (Notification.lease_expires_at <= now),
                    (Notification.status == "failed")
                    & Notification.encrypted_payload.is_not(None)
                    & (Notification.expires_at <= now),
                )
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
        for item in rows:
            if item.status == "processing":
                attempt = await db.scalar(
                    select(NotificationAttempt).where(
                        NotificationAttempt.notification_id == item.id,
                        NotificationAttempt.number == item.attempt_count,
                    )
                )
                if item.send_started_at is not None:
                    item.status, item.error_code = ("unknown", "send_outcome_unknown")
                    item.encrypted_payload = None
                    counts["unknown"] += 1
                elif item.expires_at and aware(item.expires_at) <= now:
                    item.status, item.error_code = ("failed", "payload_expired")
                    item.encrypted_payload = None
                    counts["expired"] += 1
                elif item.attempt_count >= settings.delivery_max_attempts:
                    item.status, item.error_code = ("failed", "attempts_exhausted")
                else:
                    item.status, item.error_code = ("retrying", "worker_interrupted")
                    await reschedule(db, item, now)
                    counts["recovered"] += 1
                if attempt and attempt.status == "processing":
                    attempt.status, attempt.error_code, attempt.finished_at = (
                        "interrupted",
                        item.error_code,
                        now,
                    )
                    attempt.retryable = item.status == "retrying"
                item.lease_token = item.lease_expires_at = item.send_started_at = None
                item.updated_at = now
            elif item.status in {"queued", "retrying"}:
                item.status, item.error_code, item.encrypted_payload = (
                    "failed",
                    "payload_expired",
                    None,
                )
                item.updated_at = now
                counts["expired"] += 1
            else:
                item.encrypted_payload = None
        pending = await db.execute(
            select(NotificationOutbox, Notification)
            .join(Notification)
            .where(
                Notification.status.in_(["queued", "retrying"]),
                NotificationOutbox.published_at
                < now - timedelta(seconds=settings.delivery_outbox_resend_seconds),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        )
        for outbox, item in pending:
            outbox.published_at = None
            counts["republished"] += 1
        await db.execute(
            delete(WorkerEvent).where(WorkerEvent.created_at < now - timedelta(days=7))
        )
        await db.execute(
            delete(WorkerHeartbeat).where(
                WorkerHeartbeat.last_seen < now - timedelta(days=7)
            )
        )
        from backend.app.features.providers.events_service import apply_events

        await apply_events(db)
        await db.commit()
    return counts


async def renew(
    factory: async_sessionmaker[AsyncSession],
    identifier: UUID,
    token: UUID,
    settings: Settings,
) -> None:
    while True:
        await asyncio.sleep(max(1, settings.delivery_lease_seconds / 3))
        now = utcnow()
        async with factory() as db:
            result = await db.execute(
                update(Notification)
                .where(
                    Notification.id == identifier,
                    Notification.status == "processing",
                    Notification.lease_token == token,
                    Notification.lease_expires_at > now,
                )
                .values(
                    lease_expires_at=now
                    + timedelta(seconds=settings.delivery_lease_seconds)
                )
            )
            await db.commit()
            if not cast(CursorResult[tuple[object, ...]], result).rowcount:
                return


async def store_event(
    factory: async_sessionmaker[AsyncSession], event: dict[str, Any]
) -> None:
    kind, node = (str(event.get("type", "")), str(event.get("hostname", "")))
    if kind not in {
        "worker-online",
        "worker-heartbeat",
        "worker-offline",
        "task-succeeded",
        "task-failed",
        "task-received",
        "task-started",
    } or not re.fullmatch("[A-Za-z0-9@._-]{1,200}", node):
        return
    async with factory() as db:
        if kind.startswith("worker-"):
            row = await db.get(WorkerHeartbeat, node)
            if row is None:
                row = WorkerHeartbeat(node=node, state="online", last_seen=utcnow())
                db.add(row)
            row.last_seen, row.state = (
                utcnow(),
                "offline" if kind == "worker-offline" else "online",
            )
        identifier = None
        try:
            identifier = UUID(str(event.get("uuid", "")))
        except ValueError:
            pass
        db.add(
            WorkerEvent(
                id=uuid4(),
                node=node,
                event=kind,
                notification_id=identifier,
                created_at=utcnow(),
            )
        )
        await db.commit()


def event_collector(
    app: Any,
    factory: async_sessionmaker[AsyncSession],
    loop: asyncio.AbstractEventLoop,
    stopped: threading.Event,
) -> None:
    while not stopped.is_set():
        try:
            with app.connection() as connection:
                receiver = app.events.Receiver(connection)

                def receive(event: dict[str, Any]) -> None:
                    if stopped.is_set():
                        receiver.should_stop = True
                        return
                    asyncio.run_coroutine_threadsafe(
                        store_event(factory, event), loop
                    ).result(timeout=5)

                receiver.handlers = {"*": receive}
                receiver.capture(limit=None, timeout=5, wakeup=True)
        except Exception:
            stopped.wait(1)

"""Process bootstrap for Celery and the outbox relay; imported by worker entrypoints only."""

import asyncio
import signal
import threading
from pathlib import Path
from time import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.features.notifications.delivery import consume, publish_once
from backend.app.features.notifications.recovery import event_collector, reconcile
from backend.app.features.providers.adapters.registry import discover
from backend.app.infrastructure.broker import create_celery

# Process composition must register the complete foreign-key graph before ORM flushes.
from backend.app.infrastructure.model_registry import Notification
from backend.app.infrastructure.settings import Settings

settings = Settings()
celery_app = create_celery(settings)


async def process(identifier: str) -> None:
    if not settings.database_url:
        raise RuntimeError("Delivery database is not configured")
    engine = create_async_engine(
        settings.database_url, poolclass=NullPool, hide_parameters=True
    )
    try:
        await consume(
            async_sessionmaker(engine, expire_on_commit=False),
            settings,
            discover(),
            UUID(identifier),
        )
    finally:
        await engine.dispose()


def deliver(identifier: str) -> None:
    try:
        asyncio.run(process(identifier))
    except Exception:
        raise RuntimeError("Delivery state could not be saved") from None


celery_app.task(name="voxriva.send_email")(deliver)
celery_app.task(name="voxriva.send_push")(deliver)


async def relay() -> None:
    if not settings.database_url:
        raise RuntimeError("Relay database is not configured")
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stopping = asyncio.Event()
    for sig in [signal.SIGTERM, signal.SIGINT]:
        asyncio.get_running_loop().add_signal_handler(sig, stopping.set)

    async def publish(identifier: str) -> None:
        async with factory() as db:
            channel = await db.scalar(
                select(Notification.channel).where(Notification.id == UUID(identifier))
            )
        await asyncio.to_thread(
            celery_app.send_task,
            "voxriva.send_push" if channel == "push" else "voxriva.send_email",
            args=[identifier],
            task_id=identifier,
            queue="push" if channel == "push" else "email",
            retry=False,
        )

    event_stop = threading.Event()
    collector = threading.Thread(
        target=event_collector,
        args=(celery_app, factory, asyncio.get_running_loop(), event_stop),
        daemon=True,
    )
    collector.start()
    try:
        while not stopping.is_set():
            try:
                await reconcile(factory, settings)
                for _ in range(50):
                    if stopping.is_set() or not await publish_once(factory, publish):
                        break
                    Path("/tmp/voxriva-relay-heartbeat").write_text(str(time()))
                Path("/tmp/voxriva-relay-heartbeat").write_text(str(time()))
            except Exception:
                print(
                    "Outbox publish unavailable; pending records will be retried.",
                    flush=True,
                )
            try:
                await asyncio.wait_for(stopping.wait(), timeout=1)
            except TimeoutError:
                pass
    finally:
        event_stop.set()
        await asyncio.to_thread(collector.join, 6)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(relay())

"""Scoped durable delivery statistics and restricted infrastructure telemetry."""

import asyncio
from collections.abc import Awaitable
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.identity.models import AuditEvent
from backend.app.features.identity.schemas import Principal
from backend.app.features.notifications.audit_presentation import present_audit
from backend.app.features.notifications.models import (
    Notification,
    NotificationAttempt,
    NotificationOutbox,
    WorkerEvent,
    WorkerHeartbeat,
)
from backend.app.features.notifications.recovery import aware
from backend.app.features.projects.models import Environment, Membership
from backend.app.features.projects.service import project_access
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.resources import Dependencies
from backend.app.infrastructure.settings import Settings


async def snapshot(
    db: AsyncSession,
    settings: Settings,
    dependencies: Dependencies,
    project_ids: list[UUID] | None,
    environment_id: UUID | None = None,
) -> dict[str, Any]:
    now = utcnow()
    conditions: list[Any] = []
    if project_ids is not None:
        conditions.append(Notification.project_id.in_(project_ids))
    if environment_id:
        conditions.append(Notification.environment_id == environment_id)
    counts = {
        state: count
        for state, count in await db.execute(
            select(Notification.status, func.count())
            .where(*conditions)
            .group_by(Notification.status)
        )
    }
    waiting = Notification.status.in_(["queued", "retrying"])
    oldest = await db.scalar(
        select(func.min(Notification.created_at)).where(*conditions, waiting)
    )
    pending = await db.scalar(
        select(func.count())
        .select_from(NotificationOutbox)
        .join(Notification)
        .where(*conditions, waiting, NotificationOutbox.published_at.is_(None))
    )
    attempts = await db.scalar(
        select(func.count())
        .select_from(NotificationAttempt)
        .join(Notification)
        .where(*conditions)
    )
    hour = func.substr(func.cast(Notification.created_at, String), 1, 13)
    buckets = await db.execute(
        select(hour, Notification.status, func.count())
        .where(*conditions, Notification.created_at >= now - timedelta(hours=24))
        .group_by(hour, Notification.status)
        .order_by(hour)
    )
    trend: dict[str, dict[str, Any]] = {}
    for bucket, status, count in buckets:
        trend.setdefault(
            bucket,
            {
                "hour": bucket,
                "sent": 0,
                "failed": 0,
                "delivered": 0,
                "bounced": 0,
                "unknown": 0,
                "queued": 0,
                "retrying": 0,
                "processing": 0,
            },
        )[status] = count
    result: dict[str, Any] = {
        "observed_at": now,
        "counts": {
            state: counts.get(state, 0)
            for state in [
                "queued",
                "retrying",
                "processing",
                "sent",
                "delivered",
                "bounced",
                "failed",
                "unknown",
            ]
        },
        "pending_outbox": pending or 0,
        "attempts": attempts or 0,
        "oldest_waiting_seconds": max(0, (now - aware(oldest)).total_seconds())
        if oldest
        else 0,
        "trend": list(trend.values()),
        "workers": None,
        "broker_depth": None,
        "broker_depths": None,
        "broker_status": "restricted",
        "events": [],
    }
    if project_ids is None:
        result["workers"] = [
            {
                "node": row.node,
                "state": "stale"
                if row.state == "online"
                and (now - aware(row.last_seen)).total_seconds()
                > settings.worker_stale_seconds
                else row.state,
                "last_seen": row.last_seen,
            }
            for row in await db.scalars(
                select(WorkerHeartbeat).order_by(WorkerHeartbeat.node)
            )
        ]
        result["events"] = [
            {
                "id": row.id,
                "node": row.node,
                "event": row.event,
                "notification_id": row.notification_id,
                "created_at": row.created_at,
            }
            for row in await db.scalars(
                select(WorkerEvent)
                .where(WorkerEvent.event != "worker-heartbeat")
                .order_by(WorkerEvent.created_at.desc())
                .limit(25)
            )
        ]
        redis = dependencies.redis
        result["broker_status"] = "unavailable"
        if redis is not None:
            try:
                async with asyncio.timeout(2):
                    depths = await asyncio.gather(
                        cast(Awaitable[int], redis.llen("email")),
                        cast(Awaitable[int], redis.llen("push")),
                    )
                    result["broker_depths"] = dict(
                        zip(["email", "push"], depths, strict=True)
                    )
                    result["broker_depth"] = sum(depths)
                result["broker_status"] = "ready"
            except Exception:
                pass
    return result


async def overview(
    db: AsyncSession,
    principal: Principal,
    settings: Settings,
    dependencies: Dependencies,
    project_id: UUID | None = None,
    environment_id: UUID | None = None,
) -> dict[str, Any]:
    if project_id:
        await project_access(db, principal, project_id)
    if environment_id:
        env = await db.get(Environment, environment_id)
        if env is None or (project_id and env.project_id != project_id):
            raise ApplicationError(404, "Environment not found")
        await project_access(db, principal, env.project_id)
    ids = (
        [project_id]
        if project_id
        else None
        if principal.account.platform_admin
        else list(
            await db.scalars(
                select(Membership.project_id).where(
                    Membership.account_id == principal.account.id
                )
            )
        )
    )
    report = await snapshot(db, settings, dependencies, ids, environment_id)
    return report


async def audit_history(
    db: AsyncSession,
    principal: Principal,
    project_id: UUID | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    query = select(AuditEvent)
    if project_id:
        await project_access(db, principal, project_id)
        query = query.where(AuditEvent.project_id == project_id)
    if not principal.account.platform_admin:
        query = query.where(
            AuditEvent.project_id.in_(
                select(Membership.project_id).where(
                    Membership.account_id == principal.account.id,
                    Membership.role == "project_admin",
                )
            )
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = await db.scalars(
        query.order_by(AuditEvent.created_at.desc(), AuditEvent.id)
        .offset(offset)
        .limit(25)
    )
    return {
        "total": total or 0,
        "items": await present_audit(db, principal, list(items)),
    }


async def metrics(
    db: AsyncSession, settings: Settings, dependencies: Dependencies
) -> str:
    report = await snapshot(db, settings, dependencies, None)
    lines = ["# TYPE voxriva_notifications gauge"]
    lines.extend(
        (
            f'voxriva_notifications{{status="{state}"}} {count}'
            for state, count in report["counts"].items()
        )
    )
    for name, value in [
        ("attempts", report["attempts"]),
        ("pending_outbox", report["pending_outbox"]),
        ("oldest_waiting_seconds", report["oldest_waiting_seconds"]),
        ("broker_ready", int(report["broker_status"] == "ready")),
        ("workers_online", sum(row["state"] == "online" for row in report["workers"])),
    ]:
        lines.extend([f"# TYPE voxriva_{name} gauge", f"voxriva_{name} {value}"])
    if report["broker_depth"] is not None:
        lines.extend(
            [
                "# TYPE voxriva_broker_depth gauge",
                f"voxriva_broker_depth {report['broker_depth']}",
            ]
        )
    if report["broker_depths"]:
        lines.append("# TYPE voxriva_queue_depth gauge")
        lines.extend(
            (
                f'voxriva_queue_depth{{channel="{channel}"}} {count}'
                for channel, count in report["broker_depths"].items()
            )
        )
    return "\n".join(lines) + "\n"

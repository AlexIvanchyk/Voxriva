"""Outbox relay and idempotent provider consumer. Queue bodies contain IDs only."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.features.notifications.models import (
    Notification,
    NotificationAttempt,
    NotificationOutbox,
)
from backend.app.features.notifications.policy import retry_delay
from backend.app.features.notifications.recovery import aware, renew, reschedule
from backend.app.features.providers.adapters.crypto import decrypt
from backend.app.features.providers.models import (
    ProviderConfiguration,
    ProviderRevision,
)
from backend.app.features.templates.layouts import pinned_layout, render_version
from backend.app.features.templates.models import TemplateVersion
from backend.app.features.templates.rendering import DraftContent
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.settings import Settings
from backend.app.shared.provider_contract import (
    BaseProvider,
    EmailMessage,
    ProviderError,
    PushMessage,
)


async def publish_once(
    factory: async_sessionmaker[AsyncSession], publish: Callable[[str], Awaitable[None]]
) -> bool:
    async with factory() as db:
        item = await db.scalar(
            select(NotificationOutbox)
            .join(Notification)
            .where(
                NotificationOutbox.published_at.is_(None),
                Notification.status.in_(["queued", "retrying"]),
                Notification.next_attempt_at <= utcnow(),
            )
            .order_by(NotificationOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if item is None:
            return False
        await publish(str(item.notification_id))
        item.published_at = utcnow()
        await db.commit()
        return True


async def consume(
    factory: async_sessionmaker[AsyncSession],
    config: Settings,
    registry: dict[str, type[BaseProvider]],
    identifier: UUID,
) -> None:
    async with factory() as db:
        candidate = await db.get(Notification, identifier)
        if not candidate or candidate.status not in {"queued", "retrying"}:
            return
        revision = await db.get(ProviderRevision, candidate.provider_revision_id)
        if revision is None:
            return
        await db.scalar(
            select(ProviderConfiguration)
            .where(ProviderConfiguration.id == revision.configuration_id)
            .with_for_update()
        )
        item = await db.scalar(
            select(Notification)
            .where(
                Notification.id == identifier,
                Notification.status.in_(["queued", "retrying"]),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        now = utcnow()
        if item is None or (item.next_attempt_at and aware(item.next_attempt_at) > now):
            return
        if not item.encrypted_payload or (
            item.expires_at and aware(item.expires_at) <= now
        ):
            item.status, item.error_code, item.encrypted_payload, item.updated_at = (
                "failed",
                "payload_expired",
                None,
                now,
            )
            await db.commit()
            return
        active = await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.status == "processing",
                Notification.lease_expires_at > now,
                Notification.provider_revision_id.in_(
                    select(ProviderRevision.id).where(
                        ProviderRevision.configuration_id == revision.configuration_id
                    )
                ),
            )
        )
        if (active or 0) >= config.delivery_provider_concurrency:
            await reschedule(db, item, now + timedelta(seconds=1))
            await db.commit()
            return
        token = uuid4()
        item.status, item.updated_at = ("processing", now)
        item.lease_token, item.lease_expires_at, item.send_started_at = (
            token,
            now + timedelta(seconds=config.delivery_lease_seconds),
            None,
        )
        item.attempt_count += 1
        attempt = NotificationAttempt(
            id=uuid4(),
            notification_id=item.id,
            number=item.attempt_count,
            status="processing",
            retryable=False,
            started_at=now,
        )
        db.add(attempt)
        await db.commit()
        keeper = asyncio.create_task(renew(factory, identifier, token, config))
        sending = False
        outcome = "failed"
        error: str | None = "configuration_unavailable"
        retryable, retry_after = (False, None)
        message_id: str | None = None
        try:
            saved = await db.get(TemplateVersion, item.template_version_id)
            revision = await db.get(ProviderRevision, item.provider_revision_id)
            provider = (
                await db.get(ProviderConfiguration, revision.configuration_id)
                if revision
                else None
            )
            if (
                not saved
                or not revision
                or (not provider)
                or (provider.project_id not in {None, item.project_id})
            ):
                raise ValueError("Unavailable pinned input")
            adapter = registry[provider.provider_type]
            if adapter.channel != item.channel:
                raise ValueError("Wrong provider channel")
            model = adapter.config_model.model_validate(
                {
                    **{
                        key: value
                        for key, value in revision.public_config.items()
                        if key != "_configured_secrets"
                    },
                    **decrypt(config, revision.encrypted_secrets),
                }
            )
            if (
                adapter.key == "smtp"
                and config.smtp_allowed_hosts
                and (
                    str(getattr(model, "host")).lower()
                    not in {host.lower() for host in config.smtp_allowed_hosts}
                )
            ):
                raise ValueError("Host not allowed")
            payload = decrypt(config, item.encrypted_payload)
            draft = DraftContent.model_validate(saved.content)
            layout = await pinned_layout(db, draft.layout, item.layout_version_id)
            rendered = await render_version(
                item.channel, draft, layout, payload["context"]
            )
            if rendered.errors or not rendered.rendered:
                error = "context_invalid"
            else:
                transport = adapter(model)
                phase = await db.execute(
                    update(Notification)
                    .where(
                        Notification.id == identifier,
                        Notification.status == "processing",
                        Notification.lease_token == token,
                        Notification.lease_expires_at > utcnow(),
                    )
                    .values(send_started_at=utcnow())
                )
                await db.commit()
                if not cast(CursorResult[tuple[object, ...]], phase).rowcount:
                    return
                sending = True
                message = (
                    EmailMessage(
                        recipient=payload["recipient"],
                        subject=str(rendered.rendered["subject"]),
                        text=str(rendered.rendered["text"]),
                        html=str(rendered.rendered["html"]),
                        images=rendered.rendered.get("images", []),
                    )
                    if item.channel == "email"
                    else PushMessage(
                        token=payload["device_token"],
                        title=str(rendered.rendered["title"]),
                        body=str(rendered.rendered["body"]),
                        data=rendered.rendered.get("data", {}),
                    )
                )
                result = await asyncio.to_thread(transport.send, message)
                if result.status != "accepted":
                    raise ValueError("Provider did not confirm acceptance")
                outcome, error = ("sent", None)
                message_id = result.message_id[:200] if result.message_id else None
        except ProviderError as failure:
            if sending and failure.uncertain:
                outcome, error = ("unknown", "send_outcome_unknown")
            else:
                error = (
                    failure.code
                    if failure.code
                    in {
                        "authentication_failed",
                        "tls_failed",
                        "capability_unavailable",
                        "recipient_rejected",
                        "smtp_rejected",
                        "connection_failed",
                        "rate_limited",
                        "service_unavailable",
                        "permission_denied",
                        "sending_disabled",
                        "device_unregistered",
                        "invalid_message",
                        "message_rejected",
                    }
                    else "provider_error"
                )
                retryable, retry_after = (failure.retryable, failure.retry_after)
        except Exception:
            outcome, error = (
                ("unknown", "send_outcome_unknown")
                if sending
                else ("failed", "configuration_unavailable")
            )
        finally:
            keeper.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await keeper
        item = await db.scalar(
            select(Notification)
            .where(
                Notification.id == identifier,
                Notification.status == "processing",
                Notification.lease_token == token,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if item is None:
            return
        now = utcnow()
        if (
            retryable
            and outcome == "failed"
            and (item.attempt_count < config.delivery_max_attempts)
            and item.expires_at
            and (aware(item.expires_at) > now)
        ):
            outcome = "retrying"
            delay = retry_delay(config, item.attempt_count, retry_after)
            await reschedule(db, item, now + timedelta(seconds=delay))
        item.status, item.error_code, item.updated_at = (outcome, error, now)
        item.lease_token = item.lease_expires_at = item.send_started_at = None
        if outcome in {"sent", "unknown"} or (
            item.expires_at and aware(item.expires_at) <= now
        ):
            item.encrypted_payload = None
        attempt.status, attempt.error_code, attempt.retryable = (
            outcome,
            error,
            retryable and outcome != "unknown",
        )
        attempt.provider_message_id, attempt.finished_at = (message_id, now)
        await db.commit()

"""Signed SNS ingress and a normalized SES event inbox, with no raw payload retention."""

import asyncio
import base64
import json
import re
from datetime import timedelta
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.notifications.models import Notification, NotificationAttempt
from backend.app.features.notifications.recovery import aware
from backend.app.features.providers.adapters.crypto import decrypt
from backend.app.features.providers.adapters.ses import SESConfig, SESProvider
from backend.app.features.providers.models import (
    ProviderConfiguration,
    ProviderEvent,
    ProviderRevision,
)
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError


@lru_cache(maxsize=64)
def certificate(url: str) -> x509.Certificate:
    chunks = []
    size = 0
    with httpx.stream(
        "GET", url, timeout=3, follow_redirects=False, trust_env=False
    ) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > 64000:
                raise ValueError("Oversized certificate")
            chunks.append(chunk)
    return x509.load_pem_x509_certificate(b"".join(chunks))


def verify_sns(payload: dict[str, Any], topics: set[str]) -> None:
    """Trust only the expected signed topic and its exact region's HTTPS certificate host."""
    topic = payload.get("TopicArn")
    if not isinstance(topic, str) or topic not in topics:
        raise ValueError("Unexpected topic")
    partition, region = (topic.split(":")[1], topic.split(":")[3])
    host = f"sns.{region}.amazonaws.com" + (".cn" if partition == "aws-cn" else "")
    url = payload.get("SigningCertURL", "")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != host
        or parsed.query
        or parsed.fragment
        or (
            not re.fullmatch(
                "/SimpleNotificationService-[A-Za-z0-9_-]+\\.pem", parsed.path
            )
        )
    ):
        raise ValueError("Untrusted signing certificate URL")
    kind = payload.get("Type")
    if kind == "Notification":
        fields = [
            "Message",
            "MessageId",
            *(["Subject"] if "Subject" in payload else []),
            "Timestamp",
            "TopicArn",
            "Type",
        ]
    elif kind == "SubscriptionConfirmation":
        fields = [
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ]
    else:
        raise ValueError("Unsupported SNS message type")
    if any(not isinstance(payload.get(name), str) for name in fields):
        raise ValueError("Missing signed field")
    from datetime import datetime

    timestamp = aware(
        datetime.fromisoformat(payload["Timestamp"].replace("Z", "+00:00"))
    )
    if timestamp > utcnow() + timedelta(minutes=5) or timestamp < utcnow() - timedelta(
        days=30
    ):
        raise ValueError("Invalid signed timestamp")
    version = payload.get("SignatureVersion")
    if version not in {"1", "2"}:
        raise ValueError("Unsupported signature algorithm")
    cert = certificate(url)
    if not cert.not_valid_before_utc <= utcnow() <= cert.not_valid_after_utc:
        raise ValueError("Expired signing certificate")
    key = cert.public_key()
    if not isinstance(key, rsa.RSAPublicKey):
        raise ValueError("Unsupported signing key")
    canonical = "".join(name + "\n" + payload[name] + "\n" for name in fields).encode()
    key.verify(
        base64.b64decode(payload["Signature"], validate=True),
        canonical,
        padding.PKCS1v15(),
        hashes.SHA256() if version == "2" else hashes.SHA1(),
    )


async def apply_events(db: AsyncSession) -> None:
    """Correlate only with a saved provider acceptance; early webhooks wait in the inbox."""
    rows = await db.execute(
        select(ProviderEvent, Notification, ProviderRevision)
        .join(
            NotificationAttempt,
            NotificationAttempt.provider_message_id
            == ProviderEvent.provider_message_id,
        )
        .join(Notification, Notification.id == NotificationAttempt.notification_id)
        .join(
            ProviderRevision, ProviderRevision.id == Notification.provider_revision_id
        )
        .where(
            ProviderEvent.applied_at.is_(None),
            ProviderRevision.configuration_id == ProviderEvent.configuration_id,
        )
        .order_by(ProviderEvent.occurred_at, ProviderEvent.id)
        .with_for_update(of=(ProviderEvent, Notification), skip_locked=True)
        .limit(100)
    )
    for event, item, revision in rows:
        if item.status not in {"sent", "delivered", "bounced"}:
            continue
        event.applied_at = utcnow()
        if revision.public_config.get("sns_topic_arn") != event.topic_arn:
            continue
        latest = await db.scalar(
            select(ProviderEvent)
            .where(
                ProviderEvent.notification_id == item.id,
                ProviderEvent.applied_at.is_not(None),
            )
            .order_by(ProviderEvent.occurred_at.desc(), ProviderEvent.event.asc())
            .limit(1)
        )
        event.notification_id = item.id
        if latest and (aware(latest.occurred_at), latest.event == "bounced") >= (
            aware(event.occurred_at),
            event.event == "bounced",
        ):
            continue
        item.status, item.updated_at, item.error_code = (event.event, utcnow(), None)
    await db.execute(
        delete(ProviderEvent).where(
            ProviderEvent.applied_at.is_(None),
            ProviderEvent.created_at < utcnow() - timedelta(days=7),
        )
    )


async def ses_event(
    configuration_id: UUID, body: bytes, runtime: ApplicationContext, db: AsyncSession
) -> dict[str, str]:
    item = await db.get(ProviderConfiguration, configuration_id)
    if item is None or item.provider_type != "aws_ses":
        raise ApplicationError(404, "SES provider not found")
    revisions = list(
        await db.scalars(
            select(ProviderRevision)
            .where(ProviderRevision.configuration_id == item.id)
            .order_by(ProviderRevision.number.desc())
        )
    )
    topics = {
        str(row.public_config["sns_topic_arn"])
        for row in revisions
        if row.public_config.get("sns_topic_arn")
    }
    if not topics:
        raise ApplicationError(403, "No SNS topic is configured for this provider")
    slots: asyncio.Semaphore = runtime.provider_slots
    if slots.locked():
        raise ApplicationError(503, "Event verification capacity is busy")
    async with slots:
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("Invalid envelope")
            await asyncio.to_thread(verify_sns, payload, topics)
        except (httpx.HTTPError, OSError):
            raise ApplicationError(
                503, "SNS signing certificate is temporarily unavailable"
            ) from None
        except Exception:
            raise ApplicationError(
                403, "Invalid SNS message signature or envelope"
            ) from None
        if payload["Type"] == "SubscriptionConfirmation":
            try:
                saved = next(
                    row
                    for row in revisions
                    if row.public_config.get("sns_topic_arn") == payload["TopicArn"]
                )
                config = SESConfig.model_validate(
                    {
                        **{
                            key: value
                            for key, value in saved.public_config.items()
                            if key != "_configured_secrets"
                        },
                        **decrypt(runtime.settings, saved.encrypted_secrets),
                    }
                )
                if len(payload["Token"]) > 8192:
                    raise ValueError("Invalid token")
                await asyncio.to_thread(
                    SESProvider(config).confirm_subscription,
                    payload["TopicArn"],
                    payload["Token"],
                )
            except Exception:
                raise ApplicationError(
                    503, "SNS subscription confirmation failed; verify IAM permissions"
                ) from None
            return {"status": "subscription_confirmed"}
    try:
        external_id = str(UUID(payload["MessageId"]))
        content = json.loads(payload["Message"])
        kind = content.get("eventType", content.get("notificationType"))
        if kind not in {"Delivery", "Bounce"}:
            return {"status": "ignored"}
        message_id = content["mail"]["messageId"]
        if not isinstance(message_id, str) or not re.fullmatch(
            "[A-Za-z0-9_-]{1,200}", message_id
        ):
            raise ValueError("Invalid message ID")
        from datetime import datetime

        occurred = aware(
            datetime.fromisoformat(
                content[kind.lower()]["timestamp"].replace("Z", "+00:00")
            )
        )
        if occurred > utcnow() + timedelta(
            minutes=5
        ) or occurred < utcnow() - timedelta(days=30):
            raise ValueError("Invalid event time")
    except Exception:
        raise ApplicationError(422, "Invalid normalized SES delivery event") from None
    db.add(
        ProviderEvent(
            id=uuid4(),
            configuration_id=item.id,
            external_id=external_id,
            topic_arn=payload["TopicArn"],
            provider_message_id=message_id,
            event="delivered" if kind == "Delivery" else "bounced",
            occurred_at=occurred,
            created_at=utcnow(),
        )
    )
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return {"status": "duplicate"}
    await apply_events(db)
    await db.commit()
    return {"status": "recorded"}

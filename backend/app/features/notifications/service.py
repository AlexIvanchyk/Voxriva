"""Delivery acceptance and scoped, payload-free delivery history."""

import hmac
import json
from datetime import timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.deployments.service import resolve_version
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit
from backend.app.features.notifications.models import (
    Notification,
    NotificationAttempt,
    NotificationOutbox,
)
from backend.app.features.notifications.recovery import aware
from backend.app.features.notifications.schemas import (
    Accepted,
    ApiProblem,
    AttemptView,
    NotificationDetail,
    NotificationInput,
    NotificationList,
    NotificationView,
    Prepared,
    ProviderEventView,
    ReplayInput,
    State,
    ValidationResult,
)
from backend.app.features.projects.models import Environment, Membership, Project
from backend.app.features.projects.schemas import DeliveryScope
from backend.app.features.projects.service import project_access
from backend.app.features.providers.adapters.crypto import (
    decrypt,
    encrypt,
    fingerprints,
)
from backend.app.features.providers.models import (
    ProviderConfiguration,
    ProviderEvent,
    ProviderRevision,
)
from backend.app.features.providers.schemas import BindingVersion
from backend.app.features.providers.service import binding_version, resolve_binding
from backend.app.features.templates.formats import runtime_issue_message
from backend.app.features.templates.models import (
    Template,
    TemplateProject,
    TemplateVersion,
)
from backend.app.features.templates.rendering import DraftContent, render_message
from backend.app.features.templates.versions_service import summary
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings

ERRORS = {
    "rate_limited": "The provider rate limit was reached.",
    "service_unavailable": "The provider is temporarily unavailable.",
    "permission_denied": "Provider credentials lack permission for this operation.",
    "sending_disabled": "Sending is disabled for this provider account.",
    "device_unregistered": "The device token is no longer registered. Obtain a new token from the application.",
    "invalid_message": "The provider rejected the message format or size.",
    "message_rejected": "The provider rejected the message.",
    "payload_expired": "Runtime input expired before delivery could finish.",
    "attempts_exhausted": "The allowed delivery attempts were exhausted.",
    "worker_interrupted": "The worker stopped before sending; a safe retry was scheduled.",
    "provider_error": "The provider rejected the request.",
    "context_invalid": "The runtime context could not be rendered.",
    "configuration_unavailable": "The pinned provider configuration is unavailable.",
    "authentication_failed": "The provider rejected authentication.",
    "tls_failed": "The provider TLS connection could not be verified.",
    "capability_unavailable": "The provider does not support the configured connection mode.",
    "recipient_rejected": "The provider rejected the recipient.",
    "smtp_rejected": "The SMTP server rejected the message.",
    "connection_failed": "The provider connection failed.",
    "send_outcome_unknown": "Provider acceptance could not be confirmed. Review before sending again.",
}


def view(item: Notification, settings: Settings | None = None) -> NotificationView:
    result = NotificationView.model_validate(item)
    result.payload_available = item.encrypted_payload is not None and bool(
        item.expires_at and aware(item.expires_at) > utcnow()
    )
    if settings is not None and item.channel == "email":
        recipient_data = item.encrypted_recipient or (
            item.encrypted_payload if result.payload_available else None
        )
        if recipient_data:
            result.recipient_email = decrypt(settings, recipient_data).get("recipient")
    result.error_message = (
        ERRORS.get(item.error_code, "Delivery could not be completed.")
        if item.error_code
        else None
    )
    return result


def receipt(item: Notification, replayed: bool) -> Accepted:
    return Accepted(
        id=item.id,
        status=cast(State, item.status),
        environment_id=item.environment_id,
        template_version_id=item.template_version_id,
        provider_revision_id=item.provider_revision_id,
        replayed=replayed,
        status_url=f"/api/v1/notifications/{item.id}",
    )


async def replay(
    db: AsyncSession, scope: DeliveryScope, key: str, hashes: list[str]
) -> Notification | None:
    item = await db.scalar(
        select(Notification).where(
            Notification.environment_id == scope.environment_id,
            Notification.idempotency_key == key,
        )
    )
    if item and (
        not any(hmac.compare_digest(item.request_hash, value) for value in hashes)
    ):
        raise ApplicationError(
            409,
            "This idempotency key was already used with a different notification request",
        )
    return item


async def prepare(
    payload: NotificationInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    scope: DeliveryScope,
    original: Notification | None = None,
    current_deployments: bool = True,
) -> Prepared:
    settings = runtime.settings
    template = await db.scalar(
        select(Template)
        .join(TemplateProject)
        .where(
            Template.key == payload.template_key,
            TemplateProject.project_id == scope.project_id,
        )
    )
    if template is None:
        raise ApplicationError(404, "Template is not connected to this project")
    if (template.channel == "email") != (payload.recipient is not None):
        raise ApplicationError(
            422,
            "Email templates require recipient; push templates require device_token",
        )
    provider: BindingVersion | None
    if original and (not current_deployments):
        saved = await db.get(TemplateVersion, original.template_version_id)
        assert saved is not None
        version_summary = await summary(db, saved)
        fallback_used = saved.locale != payload.locale
        provider = await binding_version(db, original.provider_revision_id)
        provider_scope = original.resolution.get("provider_scope")
    else:
        resolved = await resolve_version(
            db, template.id, scope.project_id, scope.environment_id, payload.locale
        )
        saved = await db.get(TemplateVersion, resolved.version.id)
        assert saved is not None
        version_summary, fallback_used = (resolved.version, resolved.fallback_used)
        provider, provider_scope = await resolve_binding(
            db,
            ScopeInput(
                scope="environment",
                project_id=scope.project_id,
                environment_id=scope.environment_id,
            ),
            template.channel,
        )
    if provider is None:
        raise ApplicationError(
            422, "No channel provider is assigned to this environment or its defaults"
        )
    revision = await db.get(ProviderRevision, provider.revision_id)
    configuration = await db.get(ProviderConfiguration, provider.configuration_id)
    adapter = runtime.provider_registry.get(provider.provider_type)
    if (
        revision is None
        or configuration is None
        or configuration.project_id not in {None, scope.project_id}
        or (adapter is None)
        or (adapter.channel != template.channel)
    ):
        raise ApplicationError(422, "The assigned provider is unavailable")
    try:
        config = adapter.config_model.model_validate(
            {
                **{
                    key: value
                    for key, value in revision.public_config.items()
                    if key != "_configured_secrets"
                },
                **decrypt(settings, revision.encrypted_secrets),
            }
        )
    except Exception:
        raise ApplicationError(
            503, "The pinned provider settings cannot be loaded"
        ) from None
    if (
        adapter.key == "smtp"
        and settings.smtp_allowed_hosts
        and (
            str(getattr(config, "host")).lower()
            not in {host.lower() for host in settings.smtp_allowed_hosts}
        )
    ):
        raise ApplicationError(
            422, "The configured SMTP host is not allowed by this installation"
        )
    slots = runtime.preview_slots
    if slots.locked():
        raise ApplicationError(
            429, "Rendering capacity is busy. Retry with the same idempotency key."
        )
    async with slots:
        result = await render_message(
            template.channel,
            DraftContent.model_validate(saved.content),
            payload.context,
        )
    if result.errors:
        raise ApplicationError(
            422,
            detail={
                "message": "Runtime context does not match the published template.",
                "issues": [
                    {
                        "path": issue.path,
                        "code": issue.code,
                        "message": runtime_issue_message(issue.code, issue.message),
                    }
                    for issue in result.errors
                ],
            },
        )
    rendered = result.rendered or {}
    if template.channel == "email" and (
        not rendered.get("subject")
        or "\r" in str(rendered["subject"])
        or "\n" in str(rendered["subject"])
        or (not (rendered.get("text") or rendered.get("html")))
    ):
        raise ApplicationError(
            422, "The rendered email requires a valid subject and a non-empty body"
        )
    if template.channel == "push" and (
        not rendered.get("title")
        or not rendered.get("body")
        or len(
            json.dumps(
                {
                    "message": {
                        "token": payload.device_token,
                        "notification": {
                            "title": rendered["title"],
                            "body": rendered["body"],
                        },
                        "data": rendered.get("data", {}),
                    },
                    "validate_only": False,
                },
                ensure_ascii=False,
            ).encode()
        )
        > 4096
    ):
        raise ApplicationError(
            422,
            "A push requires a title and body, and a total FCM request size of at most 4096 bytes",
        )
    project = await db.get(Project, scope.project_id)
    environment = await db.get(Environment, scope.environment_id)
    assert project is not None and environment is not None
    return Prepared(
        template,
        saved,
        revision,
        {
            "project_name": project.name,
            "environment_name": environment.name,
            "template_name": template.name,
            "template_key": template.key,
            "branch_name": version_summary.branch_name,
            "template_version": saved.number,
            "resolved_locale": saved.locale,
            "fallback_used": fallback_used,
            "provider_name": configuration.name,
            "provider_type": configuration.provider_type,
            "provider_revision": revision.number,
            "provider_scope": provider_scope,
        },
    )


DELIVERY_ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ApiProblem, "description": description}
    for code, description in {
        401: "Invalid or inactive environment API key",
        404: "Template or deployment unavailable in this environment",
        422: "Invalid target, runtime context or channel settings",
        429: "Rendering capacity is busy",
        503: "Pinned provider settings cannot be loaded",
    }.items()
}


async def validate_notification(
    payload: NotificationInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    scope: DeliveryScope,
) -> ValidationResult:
    prepared = await prepare(payload, runtime, db, scope)
    return ValidationResult(
        project_id=scope.project_id,
        environment_id=scope.environment_id,
        channel=cast(Literal["email", "push"], prepared.template.channel),
        locale=payload.locale,
        resolved_locale=prepared.version.locale,
        fallback_used=bool(prepared.resolution["fallback_used"]),
        template_version_id=prepared.version.id,
        provider_revision_id=prepared.provider_revision.id,
    )


async def accept(
    payload: NotificationInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    scope: DeliveryScope,
    idempotency_key: str,
) -> Accepted:
    return await enqueue(payload, runtime, db, scope, idempotency_key)


async def enqueue(
    payload: NotificationInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    scope: DeliveryScope,
    idempotency_key: str,
    original: Notification | None = None,
    current_deployments: bool = True,
    actor: UUID | None = None,
) -> Accepted:
    settings = runtime.settings
    fingerprint = payload.model_dump(
        mode="json",
        exclude={"device_token"} if payload.recipient is not None else {"recipient"},
    )
    if original:
        fingerprint["_replay"] = {
            "original": str(original.id),
            "current_deployments": current_deployments,
        }
    hashes = fingerprints(
        settings,
        json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), allow_nan=False),
    )
    existing = await replay(db, scope, idempotency_key, hashes)
    if existing:
        return receipt(existing, True)
    prepared = await prepare(payload, runtime, db, scope, original, current_deployments)
    template, saved, revision = (
        prepared.template,
        prepared.version,
        prepared.provider_revision,
    )
    now = utcnow()
    item = Notification(
        id=uuid4(),
        project_id=scope.project_id,
        environment_id=scope.environment_id,
        delivery_key_id=scope.key_id,
        template_id=template.id,
        template_version_id=saved.id,
        provider_revision_id=revision.id,
        channel=template.channel,
        locale=payload.locale,
        attempt_count=0,
        next_attempt_at=now,
        expires_at=now + timedelta(seconds=settings.delivery_payload_ttl_seconds),
        replay_of_id=original.id if original else None,
        initiated_by=actor,
        idempotency_key=idempotency_key,
        request_hash=hashes[0],
        encrypted_recipient=encrypt(settings, {"recipient": payload.recipient})
        if payload.recipient
        else None,
        recipient_mask=f"{payload.recipient[0]}***@***"
        if payload.recipient
        else "Device token · hidden",
        encrypted_payload=encrypt(
            settings,
            {
                "recipient": payload.recipient,
                "device_token": payload.device_token,
                "context": payload.context,
            },
        ),
        resolution=prepared.resolution,
        status="queued",
        error_code=None,
        created_at=now,
        updated_at=now,
    )
    try:
        db.add(item)
        await db.flush()
        db.add(
            NotificationOutbox(
                id=uuid4(), notification_id=item.id, published_at=None, created_at=now
            )
        )
        if original and actor:
            audit(db, actor, "notification.replay", item.id, item.project_id)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        winner = await replay(db, scope, idempotency_key, hashes)
        if winner is None:
            raise ApplicationError(
                409, "Notification scope changed. Retry the request."
            ) from None
        return receipt(winner, True)
    return receipt(item, False)


async def history(
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
    project_id: UUID | None = None,
    environment_id: UUID | None = None,
    status: State | None = None,
    channel: Literal["email", "push"] | None = None,
    recipient_email: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> NotificationList:
    query = select(Notification)
    if not principal.account.platform_admin:
        query = query.where(
            Notification.project_id.in_(
                select(Membership.project_id).where(
                    Membership.account_id == principal.account.id
                )
            )
        )
    if project_id:
        await project_access(db, principal, project_id)
        query = query.where(Notification.project_id == project_id)
    if environment_id:
        env = await db.get(Environment, environment_id)
        if env is None or (project_id and env.project_id != project_id):
            raise ApplicationError(404, "Environment not found")
        await project_access(db, principal, env.project_id)
        query = query.where(Notification.environment_id == environment_id)
    if status:
        query = query.where(Notification.status == status)
    if channel:
        query = query.where(Notification.channel == channel)
    settings = runtime.settings
    email_search = (recipient_email or "").strip().casefold()
    if email_search:
        rows = await db.stream_scalars(
            query.where(Notification.channel == "email").order_by(
                Notification.created_at.desc(), Notification.id
            ),
            execution_options={"yield_per": 100},
        )
        matches: list[NotificationView] = []
        total_matches = 0
        async for item in rows:
            candidate = view(item, settings)
            if (
                candidate.recipient_email
                and email_search in candidate.recipient_email.casefold()
            ):
                if offset <= total_matches < offset + limit:
                    matches.append(candidate)
                total_matches += 1
        return NotificationList(
            items=matches, total=total_matches, limit=limit, offset=offset
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    items = await db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id)
        .offset(offset)
        .limit(limit)
    )
    return NotificationList(
        items=[view(item, settings) for item in items],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


async def detail(
    notification_id: UUID,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal | None = None,
    scope: DeliveryScope | None = None,
) -> NotificationDetail:
    item = await db.get(Notification, notification_id)
    replay_allowed = False
    if scope is not None:
        if item is None or item.environment_id != scope.environment_id:
            raise ApplicationError(404, "Notification not found")
    else:
        if principal is None:
            raise ApplicationError(401, "Sign in required")
        if item is None:
            raise ApplicationError(404, "Notification not found")
        _, role = await project_access(db, principal, item.project_id)
        replay_allowed = item.status == "failed" and role in {
            "platform_admin",
            "project_admin",
            "operator",
        }
    attempts = []
    for attempt in await db.scalars(
        select(NotificationAttempt)
        .where(NotificationAttempt.notification_id == item.id)
        .order_by(NotificationAttempt.number)
    ):
        data = AttemptView.model_validate(attempt)
        data.error_message = (
            ERRORS.get(attempt.error_code, "Delivery could not be completed.")
            if attempt.error_code
            else None
        )
        attempts.append(data)
    events = [
        ProviderEventView(
            id=row.id,
            event=cast(Literal["delivered", "bounced"], row.event),
            occurred_at=row.occurred_at,
            received_at=row.created_at,
        )
        for row in await db.scalars(
            select(ProviderEvent)
            .where(ProviderEvent.notification_id == item.id)
            .order_by(ProviderEvent.occurred_at)
        )
    ]
    return NotificationDetail(
        **view(item, runtime.settings if scope is None else None).model_dump(),
        replay_allowed=replay_allowed,
        attempts=attempts,
        provider_events=events,
    )


async def replay_failed(
    notification_id: UUID,
    payload: ReplayInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> Accepted:
    import hashlib

    item = await db.scalar(
        select(Notification).where(Notification.id == notification_id).with_for_update()
    )
    if item is None:
        raise ApplicationError(404, "Notification not found")
    _, role = await project_access(db, principal, item.project_id)
    if role not in {"platform_admin", "project_admin", "operator"}:
        raise ApplicationError(
            403, "Project administrator or operator access is required to replay"
        )
    if item.status != "failed":
        raise ApplicationError(
            409,
            "Only failed notifications can be replayed. Unknown outcomes require investigation.",
        )
    if aware(item.updated_at) != aware(payload.expected_updated_at):
        raise ApplicationError(409, "Notification changed. Refresh before replaying.")
    contact = payload.recipient if item.channel == "email" else payload.device_token
    if (
        payload.device_token is not None
        and item.channel == "email"
        or (payload.recipient is not None and item.channel == "push")
    ):
        raise ApplicationError(
            422, "Recipient type does not match this notification channel"
        )
    if (contact is None) != (payload.context is None):
        raise ApplicationError(422, "Supply both the recipient and runtime context")
    retained: dict[str, Any]
    if contact is not None and payload.context is not None:
        retained = {
            "recipient": payload.recipient,
            "device_token": payload.device_token,
            "context": payload.context,
        }
    elif (
        item.encrypted_payload
        and item.expires_at
        and (aware(item.expires_at) > utcnow())
    ):
        try:
            retained = decrypt(runtime.settings, item.encrypted_payload)
        except Exception:
            raise ApplicationError(
                503,
                "Retained runtime input cannot be loaded from the installation keyring",
            ) from None
    else:
        raise ApplicationError(
            422,
            "Runtime input has expired. Supply the recipient and context again; preview data is never substituted.",
        )
    content = NotificationInput(
        template_key=str(item.resolution["template_key"]),
        recipient=retained.get("recipient"),
        device_token=retained.get("device_token"),
        context=retained["context"],
        locale=item.locale,
    )
    key = (
        "replay:"
        + hashlib.sha256((str(item.id) + ":" + payload.replay_key).encode()).hexdigest()
    )
    scope = DeliveryScope(
        key_id=item.delivery_key_id,
        project_id=item.project_id,
        environment_id=item.environment_id,
    )
    return await enqueue(
        content,
        runtime,
        db,
        scope,
        key,
        original=item,
        current_deployments=payload.use_current_deployments,
        actor=principal.account.id,
    )

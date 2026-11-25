import asyncio
from collections import deque
from time import monotonic
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import SecretStr, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.identity.models import BootstrapLock
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit
from backend.app.features.projects.models import Environment, Membership, Project
from backend.app.features.projects.service import project_access, scoped_environment
from backend.app.features.providers.adapters.crypto import decrypt, encrypt
from backend.app.features.providers.adapters.registry import metadata, secret_fields
from backend.app.features.providers.models import (
    ProviderBinding,
    ProviderConfiguration,
    ProviderRevision,
)
from backend.app.features.providers.schemas import (
    BindingInput,
    BindingVersion,
    BindingView,
    ConfigurationInput,
    ConfigurationView,
    RevisionInput,
    RevisionView,
    SendPushTestInput,
    SendTestInput,
    TestInput,
)
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings
from backend.app.shared.provider_contract import (
    BaseProvider,
    EmailMessage,
    ProviderError,
    ProviderResult,
    PushMessage,
)


def adapter_for(runtime: ApplicationContext, key: str) -> type[BaseProvider]:
    registry: dict[str, type[BaseProvider]] = runtime.provider_registry
    if key not in registry:
        raise ApplicationError(422, "This provider plugin is not installed")
    return registry[key]


async def configuration(
    db: AsyncSession, principal: Principal, identifier: UUID, write: bool = False
) -> ProviderConfiguration:
    item = await db.get(ProviderConfiguration, identifier)
    if item is None:
        raise ApplicationError(404, "Provider configuration not found")
    if item.project_id:
        await project_access(db, principal, item.project_id, write)
    elif write and (not principal.account.platform_admin):
        raise ApplicationError(
            403, "Only installation administrators can manage shared providers"
        )
    return item


async def revision(
    db: AsyncSession, item: ProviderConfiguration, identifier: UUID | None = None
) -> ProviderRevision:
    query = select(ProviderRevision).where(ProviderRevision.configuration_id == item.id)
    query = (
        query.where(ProviderRevision.id == identifier)
        if identifier
        else query.where(ProviderRevision.number == item.revision)
    )
    result = await db.scalar(query)
    if result is None:
        raise ApplicationError(404, "Provider revision not found")
    return result


def revision_view(item: ProviderRevision, adapter: type[BaseProvider]) -> RevisionView:
    configured = item.public_config.get("_configured_secrets", [])
    return RevisionView(
        id=item.id,
        number=item.number,
        config={
            key: value
            for key, value in item.public_config.items()
            if key not in secret_fields(adapter)
        },
        configured_secrets=[str(value) for value in configured]
        if isinstance(configured, list)
        else [],
        created_at=item.created_at,
    )


async def configuration_view(
    db: AsyncSession,
    principal: Principal,
    item: ProviderConfiguration,
    runtime: ApplicationContext,
) -> ConfigurationView:
    project = await db.get(Project, item.project_id) if item.project_id else None
    member = (
        await db.get(Membership, (item.project_id, principal.account.id))
        if item.project_id
        else None
    )
    adapter = adapter_for(runtime, item.provider_type)
    latest = revision_view(await revision(db, item), adapter)
    latest.config.pop("_configured_secrets", None)
    return ConfigurationView(
        id=item.id,
        name=item.name,
        provider_type=item.provider_type,
        channel=adapter.channel,
        project_id=item.project_id,
        project_name=project.name if project else None,
        editable=principal.account.platform_admin
        or bool(member and member.role == "project_admin"),
        latest=latest,
    )


def validated_config(
    runtime: ApplicationContext,
    adapter: type[BaseProvider],
    incoming: dict[str, Any],
    previous: ProviderRevision | None = None,
    clear: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    settings: Settings = runtime.settings
    fields = secret_fields(adapter)
    secrets = decrypt(settings, previous.encrypted_secrets) if previous else {}
    if any(key not in fields for key in clear or []):
        raise ApplicationError(422, "Only declared secret fields can be cleared")
    for key in clear or []:
        secrets.pop(key, None)
    for key in fields:
        if key in incoming:
            secrets[key] = incoming[key]
    try:
        public_previous = (
            {
                key: value
                for key, value in previous.public_config.items()
                if key != "_configured_secrets"
            }
            if previous
            else {}
        )
        model = adapter.config_model.model_validate(
            {**public_previous, **incoming, **secrets}
        )
    except ValidationError as error:
        messages = {
            "aws_credentials": "Access key ID and secret are required for AWS access keys. For workload credentials, remove stored keys first.",
            "aws_topic": "Use an SNS topic in the SES region and set a configuration set.",
            "fcm_credentials": "Provide valid Google service account JSON with its private key and standard token endpoint. For workload credentials, remove stored JSON first.",
            "smtp_auth_pair": "Username and password must be configured together",
            "smtp_auth_tls": "SMTP authentication requires TLS",
            "smtp_secret_length": "Password exceeds the supported length",
        }
        detail = [
            {
                "loc": ["config", *entry["loc"]],
                "msg": messages.get(entry["type"], "Invalid provider setting"),
                "type": entry["type"],
            }
            for entry in error.errors()
        ]
        raise ApplicationError(422, detail=detail) from None
    if (
        adapter.key == "smtp"
        and settings.smtp_allowed_hosts
        and (
            str(getattr(model, "host")).lower()
            not in {host.lower() for host in settings.smtp_allowed_hosts}
        )
    ):
        raise ApplicationError(
            422, "This SMTP host is not in the installation's allowed host list"
        )
    public = model.model_dump(mode="json")
    stored = {}
    for key in fields:
        value = getattr(model, key)
        stored[key] = (
            value.get_secret_value() if isinstance(value, SecretStr) else value
        )
        public.pop(key, None)
    public["_configured_secrets"] = sorted(
        (key for key, value in stored.items() if value)
    )
    return (public, encrypt(settings, stored))


async def types(
    runtime: ApplicationContext, principal: Principal
) -> list[dict[str, Any]]:
    return [metadata(adapter) for adapter in runtime.provider_registry.values()]


async def list_configurations(
    runtime: ApplicationContext, db: AsyncSession, principal: Principal
) -> list[ConfigurationView]:
    query = select(ProviderConfiguration).order_by(
        ProviderConfiguration.name, ProviderConfiguration.id
    )
    if not principal.account.platform_admin:
        allowed = select(Membership.project_id).where(
            Membership.account_id == principal.account.id
        )
        query = query.where(
            or_(
                ProviderConfiguration.project_id.is_(None),
                ProviderConfiguration.project_id.in_(allowed),
            )
        )
    return [
        await configuration_view(db, principal, item, runtime)
        for item in await db.scalars(query)
    ]


async def create_configuration(
    payload: ConfigurationInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> ConfigurationView:
    if payload.project_id:
        await project_access(db, principal, payload.project_id, True)
    elif not principal.account.platform_admin:
        raise ApplicationError(
            403, "Only installation administrators can create shared providers"
        )
    adapter = adapter_for(runtime, payload.provider_type)
    public, encrypted = validated_config(runtime, adapter, payload.config)
    item = ProviderConfiguration(
        id=uuid4(),
        name=payload.name,
        provider_type=payload.provider_type,
        project_id=payload.project_id,
        revision=1,
        created_at=utcnow(),
    )
    db.add(item)
    await db.flush()
    db.add(
        ProviderRevision(
            id=uuid4(),
            configuration_id=item.id,
            number=1,
            public_config=public,
            encrypted_secrets=encrypted,
            actor_id=principal.account.id,
            created_at=utcnow(),
        )
    )
    audit(db, principal.account.id, "provider.create", item.id, item.project_id)
    await commit(db)
    return await configuration_view(db, principal, item, runtime)


async def binding_inventory(
    db: AsyncSession, principal: Principal
) -> list[BindingView]:
    query = select(Project).order_by(Project.name)
    if not principal.account.platform_admin:
        query = query.join(Membership).where(
            Membership.account_id == principal.account.id
        )
    projects = list(await db.scalars(query))
    targets: list[tuple[ScopeInput, str, bool]] = [
        (ScopeInput(scope="global"), "Global default", principal.account.platform_admin)
    ]
    for project in projects:
        _, role = await project_access(db, principal, project.id)
        editable = role in {"platform_admin", "project_admin"}
        targets.append(
            (
                ScopeInput(scope="project", project_id=project.id),
                f"{project.name} / default",
                editable,
            )
        )
        targets.extend(
            (
                ScopeInput(
                    scope="environment", project_id=project.id, environment_id=env.id
                ),
                f"{project.name} / {env.name}",
                editable,
            )
            for env in await db.scalars(
                select(Environment)
                .where(Environment.project_id == project.id)
                .order_by(Environment.name)
            )
        )
    result = []
    for scope, label, editable in targets:
        for channel in ["email", "push"]:
            direct = await db.scalar(
                select(ProviderBinding).where(
                    ProviderBinding.scope_key == scope.key,
                    ProviderBinding.channel == channel,
                )
            )
            effective, effective_scope = await resolve_binding(db, scope, channel)
            result.append(
                BindingView(
                    **scope.model_dump(),
                    channel=channel,
                    label=label,
                    generation=direct.generation if direct else 0,
                    direct=await binding_version(db, direct.revision_id)
                    if direct
                    else None,
                    effective=effective,
                    effective_scope=effective_scope,
                    editable=editable,
                )
            )
    return result


async def binding_version(db: AsyncSession, identifier: UUID) -> BindingVersion:
    rev = await db.get(ProviderRevision, identifier)
    if rev is None:
        raise ApplicationError(404, "Provider revision not found")
    item = await db.get(ProviderConfiguration, rev.configuration_id)
    assert item is not None
    return BindingVersion(
        configuration_id=item.id,
        configuration_name=item.name,
        revision_id=rev.id,
        revision=rev.number,
        provider_type=item.provider_type,
    )


async def resolve_binding(
    db: AsyncSession, target: ScopeInput, channel: str
) -> tuple[BindingVersion | None, str | None]:
    keys = [target.key]
    if target.scope == "environment":
        keys.append(f"project:{target.project_id}")
    if target.scope != "global":
        keys.append("global")
    rows = list(
        await db.scalars(
            select(ProviderBinding).where(
                ProviderBinding.scope_key.in_(keys), ProviderBinding.channel == channel
            )
        )
    )
    for key in keys:
        binding = next((item for item in rows if item.scope_key == key), None)
        if binding:
            return (await binding_version(db, binding.revision_id), binding.scope)
    return (None, None)


async def resolved_provider(
    project_id: UUID,
    environment_id: UUID,
    channel: Literal["email", "push"],
    db: AsyncSession,
    principal: Principal,
) -> dict[str, Any]:
    await project_access(db, principal, project_id)
    await scoped_environment(db, project_id, environment_id)
    result, scope = await resolve_binding(
        db,
        ScopeInput(
            scope="environment", project_id=project_id, environment_id=environment_id
        ),
        channel,
    )
    if result is None:
        raise ApplicationError(
            404, "No provider is assigned to this channel and environment"
        )
    return {"scope": scope, "provider": result.model_dump()}


async def bind(
    payload: BindingInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> dict[str, int]:
    if payload.project_id:
        await project_access(db, principal, payload.project_id, True)
        await db.scalar(
            select(Project).where(Project.id == payload.project_id).with_for_update()
        )
        if payload.environment_id:
            await scoped_environment(db, payload.project_id, payload.environment_id)
    elif not principal.account.platform_admin:
        raise ApplicationError(
            403, "Only installation administrators can bind global defaults"
        )
    else:
        await db.scalar(
            select(BootstrapLock).where(BootstrapLock.id == 1).with_for_update()
        )
    rev = await db.get(ProviderRevision, payload.revision_id)
    if rev is None:
        raise ApplicationError(404, "Provider revision not found")
    item = await configuration(db, principal, rev.configuration_id)
    if item.project_id is not None and item.project_id != payload.project_id:
        raise ApplicationError(
            404, "Provider configuration is not available in this project"
        )
    if adapter_for(runtime, item.provider_type).channel != payload.channel:
        raise ApplicationError(422, "Provider channel does not match the binding")
    current = await db.scalar(
        select(ProviderBinding).where(
            ProviderBinding.scope_key == payload.key,
            ProviderBinding.channel == payload.channel,
        )
    )
    if (current.generation if current else 0) != payload.expected_generation:
        raise ApplicationError(
            409, "Provider binding changed. Refresh before assigning a revision."
        )
    if current is None:
        current = ProviderBinding(
            id=uuid4(),
            scope_key=payload.key,
            scope=payload.scope,
            project_id=payload.project_id,
            environment_id=payload.environment_id,
            channel=payload.channel,
            revision_id=rev.id,
            generation=0,
        )
        db.add(current)
    current.revision_id = rev.id
    current.generation += 1
    current.updated_at = utcnow()
    audit(
        db,
        principal.account.id,
        "provider.binding.update",
        current.id,
        payload.project_id,
    )
    await commit(db)
    return {"generation": current.generation}


async def list_revisions(
    configuration_id: UUID,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> list[RevisionView]:
    item = await configuration(db, principal, configuration_id)
    adapter = adapter_for(runtime, item.provider_type)
    values = [
        revision_view(row, adapter)
        for row in await db.scalars(
            select(ProviderRevision)
            .where(ProviderRevision.configuration_id == item.id)
            .order_by(ProviderRevision.number.desc())
        )
    ]
    for row in values:
        row.config.pop("_configured_secrets", None)
    return values


async def create_revision(
    configuration_id: UUID,
    payload: RevisionInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> ConfigurationView:
    item = await configuration(db, principal, configuration_id, True)
    await db.refresh(item, with_for_update=True)
    if item.revision != payload.expected_revision:
        raise ApplicationError(
            409, "Provider configuration changed. Reload before saving a new revision."
        )
    adapter = adapter_for(runtime, item.provider_type)
    public, encrypted = validated_config(
        runtime,
        adapter,
        payload.config,
        await revision(db, item),
        payload.clear_secrets,
    )
    item.revision += 1
    db.add(
        ProviderRevision(
            id=uuid4(),
            configuration_id=item.id,
            number=item.revision,
            public_config=public,
            encrypted_secrets=encrypted,
            actor_id=principal.account.id,
            created_at=utcnow(),
        )
    )
    audit(
        db, principal.account.id, "provider.revision.create", item.id, item.project_id
    )
    await commit(db)
    return await configuration_view(db, principal, item, runtime)


def test_limit(runtime: ApplicationContext, principal: Principal) -> None:
    now = monotonic()
    limits: dict[UUID, deque[float]] = runtime.provider_limits
    for account in list(limits):
        while limits[account] and limits[account][0] < now - 60:
            limits[account].popleft()
        if not limits[account]:
            del limits[account]
    timestamps = limits.setdefault(principal.account.id, deque())
    if len(timestamps) >= 10:
        raise ApplicationError(429, "Provider tests are limited to ten per minute")
    timestamps.append(now)


async def run_test(
    configuration_id: UUID,
    payload: TestInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> ProviderResult:
    item = await configuration(db, principal, configuration_id, True)
    saved = await revision(db, item, payload.revision_id)
    adapter = adapter_for(runtime, item.provider_type)
    sending = isinstance(payload, (SendTestInput, SendPushTestInput))
    validating = isinstance(payload, SendPushTestInput) and payload.validate_only
    if (
        not (
            adapter.capabilities.test_send
            if sending
            else adapter.capabilities.test_connection
        )
        or (isinstance(payload, SendTestInput) and adapter.channel != "email")
        or (isinstance(payload, SendPushTestInput) and adapter.channel != "push")
        or (validating and (not adapter.capabilities.validate_only))
    ):
        raise ApplicationError(422, "This provider does not support the requested test")
    test_limit(runtime, principal)
    stored = {
        **{
            key: value
            for key, value in saved.public_config.items()
            if key != "_configured_secrets"
        },
        **decrypt(runtime.settings, saved.encrypted_secrets),
    }
    try:
        config = adapter.config_model.model_validate(stored)
        instance = adapter(config)
    except Exception:
        raise ApplicationError(
            503, "Saved provider settings are incompatible with the installed plugin"
        ) from None
    settings: Settings = runtime.settings
    if (
        adapter.key == "smtp"
        and settings.smtp_allowed_hosts
        and (
            str(getattr(config, "host")).lower()
            not in {host.lower() for host in settings.smtp_allowed_hosts}
        )
    ):
        raise ApplicationError(
            422, "This SMTP host is not in the installation's allowed host list"
        )
    audit(
        db,
        principal.account.id,
        "provider.test_validate"
        if validating
        else "provider.test_send"
        if sending
        else "provider.test_connection",
        saved.id,
        item.project_id,
    )
    await commit(db)
    slots: asyncio.Semaphore = runtime.provider_slots
    if slots.locked():
        raise ApplicationError(429, "Provider test capacity is busy; try again shortly")
    async with slots:
        try:
            if isinstance(payload, SendPushTestInput):
                message = PushMessage(
                    token=payload.device_token,
                    title=payload.title,
                    body=payload.body,
                    data=payload.data,
                )
                return await asyncio.to_thread(
                    instance.validate if payload.validate_only else instance.send,
                    message,
                )
            if isinstance(payload, SendTestInput):
                return await asyncio.to_thread(
                    instance.send,
                    EmailMessage(
                        recipient=payload.recipient,
                        subject=payload.subject,
                        text=payload.text,
                    ),
                )
            return await asyncio.to_thread(instance.test_connection)
        except ProviderError as error:
            allowed = {
                "authentication_failed",
                "tls_failed",
                "capability_unavailable",
                "recipient_rejected",
                "smtp_rejected",
                "connection_failed",
                "rate_limited",
                "service_unavailable",
                "permission_denied",
                "device_unregistered",
                "invalid_message",
                "message_rejected",
                "sending_disabled",
            }
            code = error.code if error.code in allowed else "provider_failed"
            messages = {
                "authentication_failed": "SMTP authentication failed. Check the saved username and password.",
                "tls_failed": "SMTP TLS verification failed. Check the server certificate and security mode.",
                "capability_unavailable": "The SMTP server does not support the selected security or authentication mode.",
                "recipient_rejected": "The SMTP server rejected the test recipient.",
                "smtp_rejected": "The SMTP server rejected the request.",
                "connection_failed": "Could not complete the SMTP connection. Check the saved host, port and server availability.",
            }
            raise ApplicationError(
                502,
                detail={
                    "message": messages.get(
                        code,
                        "Provider test failed ("
                        + code
                        + "). Check credentials, permissions and provider settings.",
                    )
                    if adapter.key == "smtp"
                    else "Provider test failed ("
                    + code
                    + "). Check credentials, permissions and provider settings.",
                    "code": code,
                    "retryable": error.retryable,
                },
            ) from None
        except Exception:
            raise ApplicationError(
                502, "Provider test failed. No transport details are exposed."
            ) from None


async def test_connection(
    configuration_id: UUID,
    payload: TestInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> ProviderResult:
    return await run_test(configuration_id, payload, runtime, db, principal)


async def send_test(
    configuration_id: UUID,
    payload: SendTestInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> ProviderResult:
    return await run_test(configuration_id, payload, runtime, db, principal)


async def send_test_push(
    configuration_id: UUID,
    payload: SendPushTestInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> ProviderResult:
    return await run_test(configuration_id, payload, runtime, db, principal)

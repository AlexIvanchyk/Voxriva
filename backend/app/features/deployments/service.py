from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.compatibility import (
    CompatibilityIssue,
    schema_changes,
)
from backend.app.features.deployments.layout_contracts import (
    active_contracts,
    check_contracts,
    dependent_letters,
)
from backend.app.features.deployments.models import DeploymentEvent, TemplateDeployment
from backend.app.features.deployments.resolution import effective
from backend.app.features.deployments.schemas import (
    ChangeInput,
    DeployInput,
    DeploymentMatrix,
    DeploymentRow,
    FallbackInput,
    HistoryView,
    PromoteInput,
    Resolution,
    ScopeInput,
)
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit
from backend.app.features.projects.models import Environment
from backend.app.features.projects.service import project_access, scoped_environment
from backend.app.features.templates.locales import Locale
from backend.app.features.templates.models import (
    Template,
    TemplateProject,
    TemplateVersion,
)
from backend.app.features.templates.rendering import DraftContent
from backend.app.features.templates.service import lookup, view
from backend.app.features.templates.versions_service import author, summary, version
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError


async def authorize_scope(
    db: AsyncSession,
    principal: Principal,
    item: Template,
    target: ScopeInput,
    write: bool = True,
) -> None:
    if target.scope == "global":
        if write and (not principal.account.platform_admin):
            raise ApplicationError(
                403,
                "Only installation administrators can change the explicit global default",
            )
        return
    assert target.project_id is not None
    await project_access(db, principal, target.project_id, write)
    if not await db.get(TemplateProject, (item.id, target.project_id)):
        raise ApplicationError(404, "Template is not connected to this project")
    if target.environment_id:
        await scoped_environment(db, target.project_id, target.environment_id)


async def slot(
    db: AsyncSession, template_id: UUID, target: ScopeInput
) -> TemplateDeployment | None:
    result: TemplateDeployment | None = await db.scalar(
        select(TemplateDeployment).where(
            TemplateDeployment.template_id == template_id,
            TemplateDeployment.scope_key == target.key,
            TemplateDeployment.locale == target.locale,
        )
    )
    return result


async def ensure_compatible(
    old: TemplateVersion | None, new: TemplateVersion | None, allow: bool
) -> list[CompatibilityIssue]:
    issues = (
        schema_changes(
            DraftContent.model_validate(old.content),
            DraftContent.model_validate(new.content),
        )
        if old and new and (old.id != new.id)
        else []
    )
    if issues and (not allow):
        raise ApplicationError(
            409,
            detail={
                "code": "schema_incompatible",
                "message": "This changes the variable contract. Review the schema diff and explicitly acknowledge the change.",
                "issues": [issue.model_dump() for issue in issues],
            },
        )
    return issues


async def change(
    db: AsyncSession,
    principal: Principal,
    item: Template,
    payload: ChangeInput,
    new: TemplateVersion | None,
    action: str,
) -> TemplateDeployment:
    await authorize_scope(db, principal, item, payload)
    pointer = await slot(db, item.id, payload)
    generation = pointer.generation if pointer else 0
    if generation != payload.expected_generation:
        raise ApplicationError(
            409, "The deployment changed. Refresh the matrix before trying again."
        )
    if new and new.locale != payload.locale:
        raise ApplicationError(
            422, "The published version's locale must match the deployment locale"
        )
    old = await effective(db, item, payload)
    if (
        "expected_effective_version_id" in payload.model_fields_set
        and (old[0].id if old else None) != payload.expected_effective_version_id
    ):
        raise ApplicationError(
            409,
            "The effective deployment changed. Refresh the matrix before trying again.",
        )
    next_effective = new
    if new is None:
        inherited = await effective(db, item, payload, ignore_key=payload.key)
        next_effective = inherited[0] if inherited else None
    composing_letter = not item.is_layout and any(
        candidate and candidate.content.get("layout")
        for candidate in (next_effective, old[0] if old else None)
    )
    # A variable can move between the letter and its layout while preserving
    # the sender's contract. Compare those versions in their effective scopes.
    if not composing_letter:
        await ensure_compatible(
            old[0] if old else None, next_effective, payload.allow_breaking
        )
    if (pointer.version_id if pointer else None) == (new.id if new else None):
        raise ApplicationError(
            409,
            "This deployment already has the selected version or inheritance setting",
        )
    letters = []
    if item.is_layout:
        letters = list(await dependent_letters(db, item.id))
    elif composing_letter:
        letters = [item]
    dependency = item.id if item.is_layout else None
    before = await active_contracts(db, letters, payload, dependency)
    previous = pointer.version_id if pointer else None
    if pointer is None:
        pointer = TemplateDeployment(
            id=uuid4(),
            template_id=item.id,
            scope_key=payload.key,
            scope=payload.scope,
            project_id=payload.project_id,
            environment_id=payload.environment_id,
            locale=payload.locale,
            generation=1,
            version_id=new.id if new else None,
            updated_at=utcnow(),
        )
        db.add(pointer)
    else:
        pointer.version_id = new.id if new else None
        pointer.generation += 1
        pointer.updated_at = utcnow()
    db.add(
        DeploymentEvent(
            id=uuid4(),
            template_id=item.id,
            scope_key=payload.key,
            project_id=payload.project_id,
            locale=payload.locale,
            from_version_id=previous,
            to_version_id=new.id if new else None,
            action=action,
            generation=pointer.generation,
            actor_id=principal.account.id,
            created_at=utcnow(),
        )
    )
    if letters:
        await db.flush()
        after = await active_contracts(db, letters, payload, dependency)
        check_contracts(before, after, payload.allow_breaking and not item.is_layout)
    audit(db, principal.account.id, f"template.{action}", item.id, payload.project_id)
    await commit(db)
    return pointer


async def deploy(
    template_id: UUID, payload: DeployInput, db: AsyncSession, principal: Principal
) -> dict[str, object]:
    item = await db.scalar(
        select(Template).where(Template.id == template_id).with_for_update()
    )
    if item is None:
        raise ApplicationError(404, "Template not found")
    await lookup(db, principal, template_id)
    result = await change(
        db,
        principal,
        item,
        payload,
        await version(db, template_id, payload.version_id),
        "deploy",
    )
    return {"generation": result.generation, "version_id": result.version_id}


async def promote(
    template_id: UUID, payload: PromoteInput, db: AsyncSession, principal: Principal
) -> dict[str, object]:
    item = await db.scalar(
        select(Template).where(Template.id == template_id).with_for_update()
    )
    if item is None:
        raise ApplicationError(404, "Template not found")
    await lookup(db, principal, template_id)
    await authorize_scope(db, principal, item, payload.source)
    await authorize_scope(db, principal, item, payload.target)
    if (
        payload.source.key == payload.target.key
        or payload.source.locale != payload.target.locale
    ):
        raise ApplicationError(
            422, "Promote between different targets of the same locale"
        )
    source = await slot(db, template_id, payload.source)
    if not source or not source.version_id:
        raise ApplicationError(
            404, "The source has no explicit deployed version to promote"
        )
    if source.generation != payload.expected_source_generation:
        raise ApplicationError(
            409, "The source changed. Refresh the matrix before promoting."
        )
    result = await change(
        db,
        principal,
        item,
        payload.target,
        await version(db, template_id, source.version_id),
        "promote",
    )
    return {"generation": result.generation, "version_id": result.version_id}


async def rollback(
    template_id: UUID, payload: DeployInput, db: AsyncSession, principal: Principal
) -> dict[str, object]:
    item = await db.scalar(
        select(Template).where(Template.id == template_id).with_for_update()
    )
    if item is None:
        raise ApplicationError(404, "Template not found")
    await lookup(db, principal, template_id)
    await authorize_scope(db, principal, item, payload)
    used = await db.scalar(
        select(DeploymentEvent.id)
        .where(
            DeploymentEvent.template_id == template_id,
            DeploymentEvent.scope_key == payload.key,
            DeploymentEvent.locale == payload.locale,
            or_(
                DeploymentEvent.from_version_id == payload.version_id,
                DeploymentEvent.to_version_id == payload.version_id,
            ),
        )
        .limit(1)
    )
    if not used:
        raise ApplicationError(
            422, "Roll back to a version previously used by this target"
        )
    result = await change(
        db,
        principal,
        item,
        payload,
        await version(db, template_id, payload.version_id),
        "rollback",
    )
    return {"generation": result.generation, "version_id": result.version_id}


async def clear(
    template_id: UUID, payload: ChangeInput, db: AsyncSession, principal: Principal
) -> dict[str, object]:
    item = await db.scalar(
        select(Template).where(Template.id == template_id).with_for_update()
    )
    if item is None:
        raise ApplicationError(404, "Template not found")
    await lookup(db, principal, template_id)
    result = await change(db, principal, item, payload, None, "clear")
    return {"generation": result.generation, "version_id": None}


async def fallback(
    template_id: UUID, payload: FallbackInput, db: AsyncSession, principal: Principal
) -> dict[str, str]:
    item = await lookup(db, principal, template_id, manage=True)
    if item.fallback_locale != payload.expected_locale:
        raise ApplicationError(
            409, "The fallback locale changed. Reload before changing it."
        )
    if not await db.scalar(
        select(TemplateVersion.id)
        .where(
            TemplateVersion.template_id == template_id,
            TemplateVersion.locale == payload.locale,
        )
        .limit(1)
    ):
        raise ApplicationError(
            422, "Publish a version in this locale before choosing it as fallback"
        )
    if (
        item.fallback_locale != payload.locale
        and (not payload.acknowledge_active_change)
        and await db.scalar(
            select(TemplateDeployment.id)
            .where(
                TemplateDeployment.template_id == template_id,
                TemplateDeployment.version_id.is_not(None),
            )
            .limit(1)
        )
    ):
        raise ApplicationError(
            409,
            "Changing fallback may change active resolutions. Explicitly acknowledge this change.",
        )
    letters = await dependent_letters(db, item.id) if item.is_layout else []
    before = await active_contracts(db, letters, None, item.id)
    item.fallback_locale = payload.locale
    check_contracts(before, await active_contracts(db, letters, None, item.id))
    audit(db, principal.account.id, "template.fallback.update", template_id)
    await commit(db)
    return {"fallback_locale": item.fallback_locale}


async def matrix(
    template_id: UUID, db: AsyncSession, principal: Principal, locale: Locale = "en"
) -> DeploymentMatrix:
    item = await lookup(db, principal, template_id)
    visible = await view(db, principal, item)
    targets: list[tuple[ScopeInput, str, str | None, str | None, bool]] = [
        (
            ScopeInput(scope="global", locale=locale),
            "Explicit global default",
            None,
            None,
            principal.account.platform_admin,
        )
    ]
    for project in visible.projects:
        _, role = await project_access(db, principal, project.id)
        editable = role in {"platform_admin", "project_admin"}
        targets.append(
            (
                ScopeInput(scope="project", project_id=project.id, locale=locale),
                f"{project.name} / default",
                project.name,
                None,
                editable,
            )
        )
        for env in await db.scalars(
            select(Environment)
            .where(Environment.project_id == project.id)
            .order_by(Environment.name)
        ):
            targets.append(
                (
                    ScopeInput(
                        scope="environment",
                        project_id=project.id,
                        environment_id=env.id,
                        locale=locale,
                    ),
                    f"{project.name} / {env.name}",
                    project.name,
                    env.name,
                    editable,
                )
            )
    rows = []
    for target, label, project_name, environment_name, editable in targets:
        pointer = await slot(db, template_id, target)
        resolved = await effective(db, item, target)
        inherited = await effective(db, item, target, ignore_key=target.key)
        history = []
        events = await db.scalars(
            select(DeploymentEvent)
            .where(
                DeploymentEvent.template_id == template_id,
                DeploymentEvent.scope_key == target.key,
                DeploymentEvent.locale == locale,
            )
            .order_by(DeploymentEvent.created_at.desc(), DeploymentEvent.id)
            .limit(20)
        )
        for event in events:
            before_version = (
                await version(db, template_id, event.from_version_id)
                if event.from_version_id
                else None
            )
            after_version = (
                await version(db, template_id, event.to_version_id)
                if event.to_version_id
                else None
            )
            history.append(
                HistoryView(
                    id=event.id,
                    action=event.action,
                    generation=event.generation,
                    before=await summary(db, before_version)
                    if before_version
                    else None,
                    after=await summary(db, after_version) if after_version else None,
                    author=await author(db, event.actor_id),
                    created_at=event.created_at,
                )
            )
        direct = (
            await version(db, template_id, pointer.version_id)
            if pointer and pointer.version_id
            else None
        )
        rows.append(
            DeploymentRow(
                **target.model_dump(),
                label=label,
                project_name=project_name,
                environment_name=environment_name,
                generation=pointer.generation if pointer else 0,
                version=await summary(db, direct) if direct else None,
                effective_version=await summary(db, resolved[0]) if resolved else None,
                effective_scope=resolved[1] if resolved else None,
                fallback_used=resolved[2] if resolved else False,
                editable=editable,
                inherited_version=await summary(db, inherited[0])
                if inherited
                else None,
                history=history,
            )
        )
    return DeploymentMatrix(
        locale=locale, fallback_locale=item.fallback_locale, rows=rows
    )


async def resolve_version(
    db: AsyncSession,
    template_id: UUID,
    project_id: UUID,
    environment_id: UUID,
    locale: str,
) -> Resolution:
    await scoped_environment(db, project_id, environment_id)
    item = await db.get(Template, template_id)
    if item is None or not await db.get(TemplateProject, (template_id, project_id)):
        raise ApplicationError(404, "Template is not connected to this project")
    result = await effective(
        db,
        item,
        ScopeInput(
            scope="environment",
            project_id=project_id,
            environment_id=environment_id,
            locale=locale,
        ),
    )
    if result is None:
        raise ApplicationError(
            404, "No explicit deployment or configured locale fallback was found"
        )
    return Resolution(
        requested_locale=locale,
        resolved_locale=result[0].locale,
        fallback_used=result[2],
        scope=result[1],
        version=await summary(db, result[0]),
    )


async def resolve(
    project_id: UUID,
    environment_id: UUID,
    template_id: UUID,
    db: AsyncSession,
    principal: Principal,
    locale: Locale = "en",
) -> Resolution:
    await project_access(db, principal, project_id)
    return await resolve_version(db, template_id, project_id, environment_id, locale)

import asyncio
from collections import deque
from time import monotonic
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.models import TemplateDeployment
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit
from backend.app.features.projects.models import Membership, Project
from backend.app.features.projects.schemas import NamedResource
from backend.app.features.projects.service import project_access
from backend.app.features.templates.models import (
    Template,
    TemplateBranch,
    TemplateProject,
    TemplateVersion,
)
from backend.app.features.templates.rendering import (
    DraftContent,
    RenderResult,
    render_message,
)
from backend.app.features.templates.schemas import (
    DraftUpdate,
    PreviewInput,
    ProjectBindings,
    RenameInput,
    TemplateInput,
    TemplateView,
)
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError


async def view(
    db: AsyncSession,
    principal: Principal,
    item: Template,
    branch_id: UUID | None = None,
) -> TemplateView:
    projects = list(
        await db.scalars(
            select(Project)
            .join(TemplateProject)
            .where(TemplateProject.template_id == item.id)
            .order_by(Project.name)
        )
    )
    roles = {
        row.project_id: row.role
        for row in await db.scalars(
            select(Membership).where(Membership.account_id == principal.account.id)
        )
    }
    visible = (
        projects
        if principal.account.platform_admin
        else [proj for proj in projects if proj.id in roles]
    )
    if not principal.account.platform_admin and (not visible):
        raise ApplicationError(404, "Template not found")
    editable = principal.account.platform_admin or (
        bool(projects)
        and all(
            roles.get(proj.id) in {"project_admin", "template_editor"}
            for proj in projects
        )
    )
    manage = principal.account.platform_admin or (
        bool(projects)
        and all(roles.get(proj.id) == "project_admin" for proj in projects)
    )
    branch = await get_branch(db, item.id, branch_id)
    published = await db.scalar(
        select(TemplateVersion.id)
        .where(TemplateVersion.template_id == item.id)
        .limit(1)
    )
    return TemplateView(
        id=item.id,
        name=item.name,
        key=item.key,
        channel=item.channel,
        draft=DraftContent.model_validate(branch.draft),
        draft_revision=branch.draft_revision,
        updated_at=branch.updated_at,
        branch_id=branch.id,
        branch_name=branch.name,
        locale=branch.locale,
        fallback_locale=item.fallback_locale,
        primary_locale=item.primary_locale,
        languages=list(
            await db.scalars(
                select(TemplateBranch.locale)
                .where(TemplateBranch.template_id == item.id)
                .distinct()
                .order_by(TemplateBranch.locale)
            )
        ),
        has_published_versions=published is not None,
        projects=[NamedResource.model_validate(proj) for proj in visible],
        project_count=len(projects),
        editable=editable,
        manage_bindings=manage,
    )


async def get_branch(
    db: AsyncSession, template_id: UUID, branch_id: UUID | None = None
) -> TemplateBranch:
    query = select(TemplateBranch).where(TemplateBranch.template_id == template_id)
    if branch_id:
        query = query.where(TemplateBranch.id == branch_id)
    else:
        template = await db.get(Template, template_id)
        query = (
            query.where(
                TemplateBranch.locale == (template.primary_locale if template else "en")
            )
            .order_by((TemplateBranch.name == "main").desc(), TemplateBranch.name)
            .limit(1)
        )
    branch = await db.scalar(query)
    if branch is None:
        raise ApplicationError(404, "Template branch not found")
    return branch


async def lookup(
    db: AsyncSession,
    principal: Principal,
    template_id: UUID,
    write: bool = False,
    manage: bool = False,
) -> Template:
    item = (
        await db.scalar(
            select(Template).where(Template.id == template_id).with_for_update()
        )
        if write or manage
        else await db.get(Template, template_id)
    )
    if item is None:
        raise ApplicationError(404, "Template not found")
    result = await view(db, principal, item)
    if write and (not result.editable) or (manage and (not result.manage_bindings)):
        raise ApplicationError(
            403, "This shared template requires permission in every connected project"
        )
    return item


async def check_bindings(
    db: AsyncSession,
    principal: Principal,
    project_ids: list[UUID],
    manage: bool = False,
) -> None:
    if not project_ids and (not principal.account.platform_admin):
        raise ApplicationError(403, "Connect the template to a project you can edit")
    for identifier in project_ids:
        _, role = await project_access(db, principal, identifier, manage)
        if role not in {"platform_admin", "project_admin", "template_editor"}:
            raise ApplicationError(403, "Template editor access required")


async def list_templates(
    db: AsyncSession, principal: Principal, project_id: UUID | None = None
) -> list[TemplateView]:
    query = select(Template).order_by(Template.name, Template.id)
    if project_id is not None:
        await project_access(db, principal, project_id)
        query = query.where(
            Template.id.in_(
                select(TemplateProject.template_id).where(
                    TemplateProject.project_id == project_id
                )
            )
        )
    if not principal.account.platform_admin:
        allowed = (
            select(TemplateProject.template_id)
            .join(Membership, Membership.project_id == TemplateProject.project_id)
            .where(Membership.account_id == principal.account.id)
        )
        query = query.where(Template.id.in_(allowed))
    return [await view(db, principal, item) for item in await db.scalars(query)]


async def create_template(
    payload: TemplateInput, db: AsyncSession, principal: Principal
) -> TemplateView:
    await check_bindings(db, principal, payload.project_ids)
    item = Template(
        id=uuid4(),
        key=payload.key,
        name=payload.name,
        channel=payload.channel,
        primary_locale=payload.locale,
        fallback_locale=payload.locale,
        updated_at=utcnow(),
    )
    db.add(item)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ApplicationError(409, "A template with this key already exists") from None
    db.add(
        TemplateBranch(
            id=uuid4(),
            template_id=item.id,
            name="main",
            locale=payload.locale,
            draft=payload.draft.model_dump(),
            draft_revision=1,
            updated_at=utcnow(),
        )
    )
    db.add_all(
        [
            TemplateProject(template_id=item.id, project_id=identifier)
            for identifier in payload.project_ids
        ]
    )
    audit(db, principal.account.id, "template.create", item.id)
    await commit(db)
    return await view(db, principal, item)


async def get_template(
    template_id: UUID,
    db: AsyncSession,
    principal: Principal,
    branch_id: UUID | None = None,
) -> TemplateView:
    return await view(
        db, principal, await lookup(db, principal, template_id), branch_id
    )


async def bind_projects(
    template_id: UUID, payload: ProjectBindings, db: AsyncSession, principal: Principal
) -> TemplateView:
    item = await lookup(db, principal, template_id, manage=True)
    await check_bindings(db, principal, payload.project_ids, manage=True)
    current = set(
        await db.scalars(
            select(TemplateProject.project_id).where(
                TemplateProject.template_id == template_id
            )
        )
    )
    removed = current - set(payload.project_ids)
    if removed and await db.scalar(
        select(TemplateDeployment.id)
        .where(
            TemplateDeployment.template_id == template_id,
            TemplateDeployment.project_id.in_(removed),
            TemplateDeployment.version_id.is_not(None),
        )
        .limit(1)
    ):
        raise ApplicationError(
            409,
            "Clear this project's explicit deployments before disconnecting the template",
        )
    await db.execute(
        select(Template.id).where(Template.id == template_id).with_for_update()
    )
    await db.execute(
        delete(TemplateProject).where(TemplateProject.template_id == template_id)
    )
    db.add_all(
        [
            TemplateProject(template_id=template_id, project_id=identifier)
            for identifier in payload.project_ids
        ]
    )
    audit(db, principal.account.id, "template.projects.update", template_id)
    await commit(db)
    return await view(db, principal, item)


async def save_draft(
    template_id: UUID, payload: DraftUpdate, db: AsyncSession, principal: Principal
) -> TemplateView:
    item = await lookup(db, principal, template_id, write=True)
    branch = await get_branch(db, template_id, payload.branch_id)
    changed = await db.scalar(
        update(TemplateBranch)
        .where(
            TemplateBranch.id == branch.id,
            TemplateBranch.draft_revision == payload.expected_revision,
        )
        .values(
            draft=payload.draft.model_dump(),
            draft_revision=TemplateBranch.draft_revision + 1,
            updated_at=utcnow(),
        )
        .returning(TemplateBranch.id)
    )
    if changed is None:
        raise ApplicationError(
            409, "Draft changed in another editor. Copy your edits before reloading."
        )
    item.updated_at = utcnow()
    audit(db, principal.account.id, "template.draft.update", template_id)
    await commit(db)
    await db.refresh(branch)
    return await view(db, principal, item, branch.id)


async def delete_template(
    template_id: UUID, db: AsyncSession, principal: Principal
) -> None:
    item = await lookup(db, principal, template_id, manage=True)
    if await db.scalar(
        select(TemplateVersion.id)
        .where(TemplateVersion.template_id == template_id)
        .limit(1)
    ):
        raise ApplicationError(
            409, "Published templates retain immutable history and cannot be deleted"
        )
    await db.delete(item)
    audit(db, principal.account.id, "template.delete", template_id)
    await commit(db)


async def preview(
    template_id: UUID,
    payload: PreviewInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> RenderResult:
    item = await lookup(db, principal, template_id, write=payload.draft is not None)
    draft = payload.draft or DraftContent.model_validate(
        (await get_branch(db, item.id, payload.branch_id)).draft
    )
    context = payload.context if payload.context is not None else draft.preview_context
    if payload.scenario is not None:
        if payload.scenario not in draft.scenarios:
            raise ApplicationError(422, "Preview scenario not found")
        context = draft.scenarios[payload.scenario]
    return await run_preview(
        item.channel,
        draft,
        context,
        runtime,
        principal,
        generate_example=payload.generate_example,
    )


async def run_preview(
    channel: str,
    draft: DraftContent,
    context: dict[str, JsonValue],
    runtime: ApplicationContext,
    principal: Principal,
    *,
    authoring: bool = True,
    generate_example: bool = False,
) -> RenderResult:
    limits: dict[UUID, deque[float]] = runtime.preview_limits
    now = monotonic()
    for key in list(limits):
        if not limits[key] or now - limits[key][-1] >= 60:
            del limits[key]
    attempts = limits.setdefault(principal.account.id, deque())
    while attempts and now - attempts[0] >= 60:
        attempts.popleft()
    if len(attempts) >= 60 or len(limits) > 1024:
        raise ApplicationError(
            429,
            "Preview rate limit reached. Try again in a minute.",
            headers={"Retry-After": "60"},
        )
    attempts.append(now)
    slots: asyncio.Semaphore = runtime.preview_slots
    try:
        await asyncio.wait_for(slots.acquire(), timeout=0.1)
    except TimeoutError:
        raise ApplicationError(429, "Preview is busy. Try again shortly.") from None
    try:
        return await render_message(
            channel,
            draft,
            context,
            authoring=authoring,
            generate_example=generate_example,
        )
    finally:
        slots.release()


async def rename_variable(
    template_id: UUID,
    payload: RenameInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> dict[str, object]:
    from backend.app.features.templates.authoring import rename_bounded

    item = await lookup(db, principal, template_id, write=True)
    slots: asyncio.Semaphore = runtime.preview_slots
    if slots.locked():
        raise ApplicationError(429, "Editor capacity is busy")
    async with slots:
        try:
            result = await rename_bounded(
                item.channel,
                payload.draft.model_dump(),
                payload.old_name,
                payload.new_name,
            )
            result["draft"] = DraftContent.model_validate(result["draft"]).model_dump()
            return result
        except ValueError as error:
            raise ApplicationError(422, str(error)) from None

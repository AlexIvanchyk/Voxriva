import asyncio
from collections import deque
from time import monotonic
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.layout_contracts import (
    active_contracts,
    dependent_letters,
)
from backend.app.features.deployments.models import TemplateDeployment
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit
from backend.app.features.projects.models import Environment, Membership, Project
from backend.app.features.projects.schemas import NamedResource
from backend.app.features.projects.service import project_access
from backend.app.features.templates.composition import (
    compose,
    layout_parts,
    validate_kind,
)
from backend.app.features.templates.layouts import (
    preview_scope,
    published_layout,
    resolve_layout,
)
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
        is_layout=item.is_layout,
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


async def check_layout_reference(
    db: AsyncSession,
    principal: Principal,
    draft: DraftContent,
    projects: list[UUID],
    locale: str,
) -> None:
    if not draft.layout:
        return
    layout = await lookup(db, principal, draft.layout.template_id)
    if not layout.is_layout:
        raise ApplicationError(422, "Select an email layout")
    if projects and not await db.scalar(
        select(TemplateProject.project_id)
        .where(
            TemplateProject.template_id == layout.id,
            TemplateProject.project_id.in_(projects),
        )
        .limit(1)
    ):
        raise ApplicationError(
            404, "Email layout is unavailable in the connected projects"
        )
    if draft.layout.version_id:
        await published_layout(db, layout, draft.layout.version_id, locale)


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
    validate_kind(payload.channel, payload.is_layout, payload.draft)
    await check_bindings(db, principal, payload.project_ids)
    await check_layout_reference(
        db, principal, payload.draft, payload.project_ids, payload.locale
    )
    item = Template(
        id=uuid4(),
        key=payload.key,
        name=payload.name,
        channel=payload.channel,
        is_layout=payload.is_layout,
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
    await db.flush()
    if item.is_layout and removed:
        await active_contracts(db, await dependent_letters(db, item.id), None, item.id)
    elif not item.is_layout and set(payload.project_ids) - current:
        await active_contracts(db, [item], None)
    audit(db, principal.account.id, "template.projects.update", template_id)
    await commit(db)
    return await view(db, principal, item)


async def save_draft(
    template_id: UUID, payload: DraftUpdate, db: AsyncSession, principal: Principal
) -> TemplateView:
    item = await lookup(db, principal, template_id, write=True)
    branch = await get_branch(db, template_id, payload.branch_id)
    validate_kind(item.channel, item.is_layout, payload.draft)
    if payload.draft.layout:
        projects = list(
            await db.scalars(
                select(TemplateProject.project_id).where(
                    TemplateProject.template_id == item.id
                )
            )
        )
        await check_layout_reference(
            db, principal, payload.draft, projects, branch.locale
        )
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
    branch = await get_branch(db, item.id, payload.branch_id)
    draft = payload.draft or DraftContent.model_validate(branch.draft)
    return await preview_content(
        item, draft, branch.locale, payload, runtime, db, principal
    )


async def preview_content(
    item: Template,
    draft: DraftContent,
    locale: str,
    payload: PreviewInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
    *,
    authoring: bool = True,
    check_defaults: bool = False,
) -> RenderResult:
    validate_kind(item.channel, item.is_layout, draft)
    wrappers = None
    metadata = None
    fixtures = {}
    local_context = draft.preview_context
    scenarios = draft.scenarios
    if item.is_layout:
        wrappers = layout_parts(draft)
        draft = draft.model_copy(update={field: "Email body" for field in wrappers})
    elif draft.layout:
        target = await preview_scope(
            db, principal, item.id, locale, payload.project_id, payload.environment_id
        )
        saved = await resolve_layout(db, draft.layout, target)
        layout = DraftContent.model_validate(saved.content)
        layout_branch = await get_branch(db, saved.template_id, saved.branch_id)
        metadata = {
            "template_id": str(saved.template_id),
            "version_id": str(saved.id),
            "number": saved.number,
            "locale": saved.locale,
            "branch": layout_branch.name,
            **target.model_dump(mode="json", exclude={"locale"}),
            "variable_schema": layout.variable_schema,
            "runtime_defaults": layout.runtime_defaults,
            "images": list(layout.images),
        }
        fixtures = layout.preview_context
        wrappers = layout_parts(layout)
        draft = compose(draft, layout)
    context = payload.context if payload.context is not None else local_context
    if payload.scenario is not None:
        if payload.scenario not in scenarios:
            raise ApplicationError(422, "Preview scenario not found")
        context = scenarios[payload.scenario]
    context = {**fixtures, **context}
    if check_defaults:
        context = {
            key: value
            for key, value in context.items()
            if key not in draft.runtime_defaults
        }
    result = await run_preview(
        item.channel,
        draft,
        context,
        runtime,
        principal,
        wrappers=wrappers,
        generate_example=payload.generate_example,
        authoring=authoring,
    )
    result.layout = metadata
    return result


async def run_preview(
    channel: str,
    draft: DraftContent,
    context: dict[str, JsonValue],
    runtime: ApplicationContext,
    principal: Principal,
    *,
    wrappers: dict[str, list[str]] | None = None,
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
            wrappers=wrappers,
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


async def layout_options(
    template_id: UUID, db: AsyncSession, principal: Principal
) -> dict[str, object]:
    letter = await get_template(template_id, db, principal)
    if letter.is_layout or letter.channel != "email":
        raise ApplicationError(422, "Select an email template")
    projects = [project.id for project in letter.projects]
    query = (
        select(Template)
        .where(Template.is_layout.is_(True))
        .order_by(Template.name, Template.id)
    )
    if projects or not principal.account.platform_admin:
        query = query.where(
            Template.id.in_(
                select(TemplateProject.template_id).where(
                    TemplateProject.project_id.in_(projects)
                )
            )
        )
    layouts = []
    for layout in await db.scalars(query):
        versions = (
            await db.execute(
                select(
                    TemplateVersion.id,
                    TemplateVersion.number,
                    TemplateVersion.locale,
                    TemplateBranch.name,
                )
                .join(TemplateBranch, TemplateVersion.branch_id == TemplateBranch.id)
                .where(TemplateVersion.template_id == layout.id)
                .order_by(TemplateVersion.created_at.desc())
            )
        ).all()
        layouts.append(
            {
                "id": layout.id,
                "name": layout.name,
                "fallback_locale": layout.fallback_locale,
                "versions": [
                    {
                        "id": row.id,
                        "number": row.number,
                        "locale": row.locale,
                        "branch": row.name,
                    }
                    for row in versions
                ],
            }
        )
    targets = []
    for project in letter.projects:
        envs: list[Environment | None] = list(
            await db.scalars(
                select(Environment)
                .where(Environment.project_id == project.id)
                .order_by(Environment.name, Environment.id)
            )
        )
        if not envs:
            envs.append(None)
        for env in envs:
            targets.append(
                {
                    "project_id": project.id,
                    "environment_id": env.id if env else None,
                    "label": f"{project.name} / {env.name}" if env else project.name,
                }
            )
    return {"layouts": layouts, "targets": targets}

from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.resolution import effective
from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.identity.schemas import Principal
from backend.app.features.projects.models import Environment, Membership, Project
from backend.app.features.projects.service import scoped_environment
from backend.app.features.templates.composition import compose, layout_parts
from backend.app.features.templates.models import (
    Template,
    TemplateProject,
    TemplateVersion,
)
from backend.app.features.templates.rendering import (
    DraftContent,
    LayoutReference,
    RenderResult,
    render_message,
)
from backend.app.infrastructure.errors import ApplicationError


async def preview_scope(
    db: AsyncSession,
    principal: Principal,
    template_id: UUID,
    locale: str,
    project_id: UUID | None,
    environment_id: UUID | None,
) -> ScopeInput:
    projects = (
        select(Project.id)
        .join(TemplateProject)
        .where(TemplateProject.template_id == template_id)
        .order_by(Project.name, Project.id)
    )
    if not principal.account.platform_admin:
        projects = projects.join(Membership, Membership.project_id == Project.id).where(
            Membership.account_id == principal.account.id
        )
    if principal.project_ids is not None:
        projects = projects.where(Project.id.in_(principal.project_ids))
    if project_id:
        projects = projects.where(Project.id == project_id)
    selected = await db.scalar(projects.limit(1))
    if selected is None:
        if (
            principal.account.platform_admin
            and project_id is None
            and environment_id is None
            and principal.project_ids is None
        ):
            return ScopeInput(scope="global", locale=locale)
        raise ApplicationError(404, "Preview project is unavailable")
    if environment_id:
        await scoped_environment(db, selected, environment_id)
    else:
        environment_id = await db.scalar(
            select(Environment.id)
            .where(Environment.project_id == selected)
            .order_by(Environment.name, Environment.id)
            .limit(1)
        )
    return ScopeInput(
        scope="environment" if environment_id else "project",
        project_id=selected,
        environment_id=environment_id,
        locale=locale,
    )


async def resolve_layout(
    db: AsyncSession, ref: LayoutReference, target: ScopeInput
) -> TemplateVersion:
    layout = await db.scalar(
        select(Template)
        .where(Template.id == ref.template_id, Template.is_layout.is_(True))
        .with_for_update(read=True)
    )
    if not layout or (
        target.project_id
        and not await db.get(TemplateProject, (layout.id, target.project_id))
    ):
        raise ApplicationError(404, "Email layout is unavailable in this project")
    if ref.version_id:
        return await published_layout(db, layout, ref.version_id, target.locale)
    resolved = await effective(db, layout, target)
    if not resolved:
        raise ApplicationError(
            422, "No active layout for this language and deployment target"
        )
    return resolved[0]


async def published_layout(
    db: AsyncSession, layout: Template, version_id: UUID, locale: str
) -> TemplateVersion:
    saved = await db.get(TemplateVersion, version_id)
    if (
        not saved
        or saved.template_id != layout.id
        or saved.locale not in {locale, layout.fallback_locale}
    ):
        raise ApplicationError(
            422,
            "Choose a published version of this layout in the letter's language or the layout fallback",
        )
    return saved


async def pinned_layout(
    db: AsyncSession, ref: LayoutReference | None, version_id: UUID | None
) -> TemplateVersion | None:
    if not ref and not version_id:
        return None
    saved = await db.get(TemplateVersion, version_id) if version_id else None
    if (
        not ref
        or not saved
        or saved.template_id != ref.template_id
        or (ref.version_id and ref.version_id != saved.id)
    ):
        raise ApplicationError(422, "The accepted layout version is unavailable")
    return saved


async def render_version(
    channel: str,
    draft: DraftContent,
    saved_layout: TemplateVersion | None,
    context: dict[str, JsonValue],
) -> RenderResult:
    wrappers = None
    if saved_layout:
        layout = DraftContent.model_validate(saved_layout.content)
        wrappers = layout_parts(layout)
        draft = compose(draft, layout)
    return await render_message(channel, draft, context, wrappers=wrappers)

"""Workspace deployment inventory, scoped to visible template/project connections."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.inventory_schemas import InventoryRow
from backend.app.features.deployments.models import TemplateDeployment
from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.identity.schemas import Principal
from backend.app.features.projects.models import Environment, Membership, Project
from backend.app.features.templates.models import (
    Template,
    TemplateBranch,
    TemplateProject,
    TemplateVersion,
)
from backend.app.features.templates.versions_service import summary


async def inventory(db: AsyncSession, principal: Principal) -> list[InventoryRow]:
    projects_query = select(Project).order_by(Project.name, Project.id)
    if not principal.account.platform_admin:
        projects_query = projects_query.join(Membership).where(
            Membership.account_id == principal.account.id
        )
    projects = {project.id: project for project in await db.scalars(projects_query)}
    bindings = list(
        await db.scalars(
            select(TemplateProject).where(TemplateProject.project_id.in_(projects))
        )
    )
    visible_ids = {binding.template_id for binding in bindings}
    template_query = select(Template).order_by(Template.name, Template.id)
    if not principal.account.platform_admin:
        template_query = template_query.where(Template.id.in_(visible_ids))
    templates = list(await db.scalars(template_query))
    identifiers = [item.id for item in templates]
    environments = list(
        await db.scalars(
            select(Environment)
            .where(Environment.project_id.in_(projects))
            .order_by(Environment.name, Environment.id)
        )
    )
    pointers = {
        (pointer.template_id, pointer.scope_key, pointer.locale): pointer
        for pointer in await db.scalars(
            select(TemplateDeployment).where(
                TemplateDeployment.template_id.in_(identifiers)
            )
        )
    }
    active_ids = {
        pointer.version_id for pointer in pointers.values() if pointer.version_id
    }
    versions = {
        item.id: await summary(db, item)
        for item in await db.scalars(
            select(TemplateVersion).where(TemplateVersion.id.in_(active_ids))
        )
    }
    branch_locales = list(
        (
            await db.execute(
                select(TemplateBranch.template_id, TemplateBranch.locale).where(
                    TemplateBranch.template_id.in_(identifiers)
                )
            )
        ).all()
    )
    rows = []
    for item in templates:
        locales = sorted(
            {item.fallback_locale}
            | {
                locale
                for template_id, locale in branch_locales
                if template_id == item.id
            }
        )
        targets = [ScopeInput(scope="global")]
        for binding in bindings:
            if binding.template_id != item.id:
                continue
            targets.append(ScopeInput(scope="project", project_id=binding.project_id))
            targets.extend(
                ScopeInput(
                    scope="environment",
                    project_id=binding.project_id,
                    environment_id=env.id,
                )
                for env in environments
                if env.project_id == binding.project_id
            )
        env_names = {env.id: env.name for env in environments}
        for target in targets:
            keys = [target.key]
            if target.scope == "environment":
                keys.append(f"project:{target.project_id}")
            if target.scope != "global":
                keys.append("global")
            for locale in locales:
                requested = target.model_copy(update={"locale": locale})
                direct = pointers.get((item.id, target.key, locale))
                resolved = next(
                    (
                        pointer
                        for candidate in dict.fromkeys([locale, item.fallback_locale])
                        for key in keys
                        if (pointer := pointers.get((item.id, key, candidate)))
                        and pointer.version_id
                    ),
                    None,
                )
                rows.append(
                    InventoryRow(
                        **requested.model_dump(),
                        template_id=item.id,
                        template_name=item.name,
                        template_key=item.key,
                        channel=item.channel,
                        project_name=projects[target.project_id].name
                        if target.project_id
                        else None,
                        environment_name=env_names.get(target.environment_id)
                        if target.environment_id
                        else None,
                        version=versions.get(direct.version_id)
                        if direct and direct.version_id
                        else None,
                        effective_version=versions.get(resolved.version_id)
                        if resolved and resolved.version_id
                        else None,
                        effective_scope=resolved.scope if resolved else None,
                        fallback_used=resolved.locale != locale if resolved else False,
                        updated_at=resolved.updated_at if resolved else None,
                    )
                )
    return rows

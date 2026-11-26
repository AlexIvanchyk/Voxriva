from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.models import TemplateDeployment
from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.templates.models import Template, TemplateVersion
from backend.app.infrastructure.errors import ApplicationError


async def effective(
    db: AsyncSession, item: Template, target: ScopeInput, ignore_key: str | None = None
) -> tuple[TemplateVersion, str, bool] | None:
    keys = [target.key]
    if target.scope == "environment":
        keys.append(f"project:{target.project_id}")
    if target.scope != "global":
        keys.append("global")
    locales = [target.locale] + (
        [item.fallback_locale] if item.fallback_locale != target.locale else []
    )
    rows = list(
        await db.scalars(
            select(TemplateDeployment).where(
                TemplateDeployment.template_id == item.id,
                TemplateDeployment.scope_key.in_(keys),
                TemplateDeployment.locale.in_(locales),
                TemplateDeployment.version_id.is_not(None),
            )
        )
    )
    for locale in locales:
        for key in keys:
            pointer = next(
                (
                    row
                    for row in rows
                    if row.scope_key == key
                    and row.locale == locale
                    and (not (key == ignore_key and locale == target.locale))
                ),
                None,
            )
            if pointer and pointer.version_id:
                resolved = await db.get(TemplateVersion, pointer.version_id)
                if resolved is None or resolved.template_id != item.id:
                    raise ApplicationError(404, "Published version not found")
                return (resolved, pointer.scope, locale != target.locale)
    return None

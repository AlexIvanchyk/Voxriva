"""Check the contracts actually exposed by deployed letters, including inherited slots."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.compatibility import schema_changes
from backend.app.features.deployments.models import TemplateDeployment
from backend.app.features.deployments.resolution import effective
from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.projects.models import Environment
from backend.app.features.templates.composition import compose
from backend.app.features.templates.layouts import resolve_layout
from backend.app.features.templates.models import (
    Template,
    TemplateProject,
    TemplateVersion,
)
from backend.app.features.templates.rendering import DraftContent
from backend.app.infrastructure.errors import ApplicationError

Snapshot = dict[tuple[UUID, UUID, UUID | None, str], tuple[UUID, DraftContent]]


async def dependent_letters(db: AsyncSession, layout_id: UUID) -> Sequence[Template]:
    return (
        await db.scalars(
            select(Template).where(
                Template.id.in_(
                    select(TemplateDeployment.template_id)
                    .join(
                        TemplateVersion,
                        TemplateDeployment.version_id == TemplateVersion.id,
                    )
                    .where(
                        TemplateVersion.content["layout"]["template_id"].as_string()
                        == str(layout_id)
                    )
                )
            )
        )
    ).all()


async def active_contracts(
    db: AsyncSession,
    letters: Sequence[Template],
    target: ScopeInput | None,
    layout_id: UUID | None = None,
) -> Snapshot:
    result: Snapshot = {}
    for letter in letters:
        locales = set(
            await db.scalars(
                select(TemplateDeployment.locale).where(
                    TemplateDeployment.template_id == letter.id,
                    TemplateDeployment.version_id.is_not(None),
                )
            )
        )
        if target:
            locales.add(target.locale)
        projects = select(TemplateProject.project_id).where(
            TemplateProject.template_id == letter.id
        )
        if target and target.project_id:
            projects = projects.where(TemplateProject.project_id == target.project_id)
        for project in await db.scalars(projects):
            environments: list[UUID | None] = (
                [target.environment_id]
                if target and target.environment_id
                else list(
                    await db.scalars(
                        select(Environment.id).where(Environment.project_id == project)
                    )
                )
            )
            if not environments:
                environments.append(None)
            for environment in environments:
                for locale in locales:
                    scope = ScopeInput(
                        scope="environment" if environment else "project",
                        project_id=project,
                        environment_id=environment,
                        locale=locale,
                    )
                    resolved = await effective(db, letter, scope)
                    if not resolved:
                        continue
                    saved = resolved[0]
                    draft = DraftContent.model_validate(saved.content)
                    if layout_id and (
                        not draft.layout or draft.layout.template_id != layout_id
                    ):
                        continue
                    if draft.layout:
                        try:
                            layout = await resolve_layout(
                                db,
                                draft.layout,
                                scope.model_copy(update={"locale": saved.locale}),
                            )
                            draft = compose(
                                draft, DraftContent.model_validate(layout.content)
                            )
                        except ApplicationError as error:
                            raise ApplicationError(
                                409,
                                f"An active email template requires a compatible layout. {error.detail}",
                            ) from error
                    result[(letter.id, project, environment, locale)] = (
                        saved.id,
                        draft,
                    )
    return result


def check_contracts(
    before: Snapshot, after: Snapshot, allow_breaking: bool = False
) -> None:
    if allow_breaking:
        return
    for key in before.keys() & after.keys():
        removed_images = before[key][1].images.keys() - after[key][1].images.keys()
        if removed_images:
            raise ApplicationError(
                409,
                "An active email template would lose a saved image: "
                + ", ".join(sorted(removed_images)),
            )
        issues = schema_changes(before[key][1], after[key][1])
        removed_defaults = (
            before[key][1].runtime_defaults.keys()
            - after[key][1].runtime_defaults.keys()
        )
        if not issues and removed_defaults:
            raise ApplicationError(
                409,
                "An active email template would lose a runtime default: "
                + ", ".join(sorted(removed_defaults)),
            )
        if issues:
            raise ApplicationError(
                409,
                detail={
                    "code": "dependent_template_incompatible",
                    "message": f"An active email template depends on the previous contract: {issues[0].path} — {issues[0].message}.",
                    "issues": [issue.model_dump() for issue in issues],
                },
            )

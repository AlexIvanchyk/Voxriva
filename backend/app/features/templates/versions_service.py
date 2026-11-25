from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.deployments.compatibility import (
    schema_changes,
)
from backend.app.features.identity.models import Account
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import audit, commit
from backend.app.features.templates.models import (
    TemplateBranch,
    TemplateVersion,
)
from backend.app.features.templates.rendering import DraftContent, RenderResult
from backend.app.features.templates.schemas import PreviewInput
from backend.app.features.templates.service import get_branch, lookup, run_preview
from backend.app.features.templates.versions_schemas import (
    BranchInput,
    BranchView,
    LanguageInput,
    PrimaryLanguageInput,
    PublishInput,
    VersionSummary,
    VersionView,
)
from backend.app.infrastructure.context import ApplicationContext
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError


async def author(db: AsyncSession, identifier: UUID) -> str:
    account = await db.get(Account, identifier)
    return account.display_name or account.email if account else "Former member"


async def summary(db: AsyncSession, item: TemplateVersion) -> VersionSummary:
    branch = await db.get(TemplateBranch, item.branch_id)
    return VersionSummary(
        id=item.id,
        branch_id=item.branch_id,
        branch_name=branch.name if branch else "Former branch",
        number=item.number,
        locale=item.locale,
        parent_version_id=item.parent_version_id,
        draft_revision=item.draft_revision,
        message=item.message,
        author=await author(db, item.actor_id),
        created_at=item.created_at,
    )


async def version(
    db: AsyncSession, template_id: UUID, version_id: UUID
) -> TemplateVersion:
    item = await db.scalar(
        select(TemplateVersion).where(
            TemplateVersion.id == version_id, TemplateVersion.template_id == template_id
        )
    )
    if item is None:
        raise ApplicationError(404, "Published version not found")
    return item


async def head(db: AsyncSession, branch_id: UUID) -> TemplateVersion | None:
    result: TemplateVersion | None = await db.scalar(
        select(TemplateVersion)
        .where(TemplateVersion.branch_id == branch_id)
        .order_by(TemplateVersion.number.desc())
        .limit(1)
    )
    return result


async def branches(
    template_id: UUID, db: AsyncSession, principal: Principal
) -> list[BranchView]:
    await lookup(db, principal, template_id)
    results = []
    for branch in await db.scalars(
        select(TemplateBranch)
        .where(TemplateBranch.template_id == template_id)
        .order_by(TemplateBranch.locale, TemplateBranch.name)
    ):
        latest = await head(db, branch.id)
        results.append(
            BranchView(
                id=branch.id,
                name=branch.name,
                locale=branch.locale,
                draft_revision=branch.draft_revision,
                source_version_id=branch.source_version_id,
                head=await summary(db, latest) if latest else None,
            )
        )
    return results


async def primary_language(
    template_id: UUID,
    payload: PrimaryLanguageInput,
    db: AsyncSession,
    principal: Principal,
) -> dict[str, str]:
    item = await lookup(db, principal, template_id, write=True)
    if item.primary_locale != payload.expected_locale:
        raise ApplicationError(
            409, "Primary language changed. Refresh before changing it."
        )
    if not await db.scalar(
        select(TemplateBranch.id)
        .where(
            TemplateBranch.template_id == template_id,
            TemplateBranch.locale == payload.locale,
        )
        .limit(1)
    ):
        raise ApplicationError(422, "Add this language before making it primary")
    item.primary_locale = payload.locale
    audit(db, principal.account.id, "template.primary.update", template_id)
    await commit(db)
    return {"primary_locale": item.primary_locale}


async def add_language(
    template_id: UUID, payload: LanguageInput, db: AsyncSession, principal: Principal
) -> BranchView:
    await lookup(db, principal, template_id, write=True)
    if await db.scalar(
        select(TemplateBranch.id)
        .where(
            TemplateBranch.template_id == template_id,
            TemplateBranch.locale == payload.locale,
        )
        .limit(1)
    ):
        raise ApplicationError(
            409, "This language already exists. Select it in the language picker."
        )
    content = DraftContent().model_dump()
    if payload.source_branch_id:
        source = await get_branch(db, template_id, payload.source_branch_id)
        if source.draft_revision != payload.expected_revision:
            raise ApplicationError(
                409, "Source draft changed. Refresh before copying this language."
            )
        content = DraftContent.model_validate(source.draft).model_dump()
    branch = TemplateBranch(
        id=uuid4(),
        template_id=template_id,
        name="main",
        locale=payload.locale,
        draft=content,
        draft_revision=1,
        updated_at=utcnow(),
    )
    db.add(branch)
    audit(db, principal.account.id, "template.language.create", branch.id)
    await commit(db, "This language already exists")
    return BranchView(
        id=branch.id,
        name="main",
        locale=branch.locale,
        draft_revision=1,
        source_version_id=None,
        head=None,
    )


async def fork(
    template_id: UUID, payload: BranchInput, db: AsyncSession, principal: Principal
) -> BranchView:
    await lookup(db, principal, template_id, write=True)
    source = await version(db, template_id, payload.source_version_id)
    branch = TemplateBranch(
        id=uuid4(),
        template_id=template_id,
        name=payload.name,
        locale=payload.locale or source.locale,
        draft=source.content,
        draft_revision=1,
        source_version_id=source.id,
        updated_at=utcnow(),
    )
    db.add(branch)
    audit(db, principal.account.id, "template.branch.create", branch.id)
    await commit(db, "A branch with this name and locale already exists")
    return BranchView(
        id=branch.id,
        name=branch.name,
        locale=branch.locale,
        draft_revision=1,
        source_version_id=source.id,
        head=None,
    )


async def publish(
    template_id: UUID,
    payload: PublishInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> VersionView:
    item = await lookup(db, principal, template_id, write=True)
    branch = await get_branch(db, template_id, payload.branch_id)
    if branch.draft_revision != payload.expected_revision:
        raise ApplicationError(
            409,
            "The saved draft changed. Reload its latest revision before publishing.",
        )
    content = DraftContent.model_validate(branch.draft)
    if (
        item.channel == "email"
        and (
            not content.subject.strip()
            or not (content.html.strip() or content.text.strip())
        )
        or (
            item.channel == "push"
            and (not content.title.strip() or not content.body.strip())
        )
    ):
        raise ApplicationError(
            422,
            "Complete the subject and HTML/text, or the push title and body, before publishing",
        )
    report = await run_preview(
        item.channel, content, content.preview_context, runtime, principal
    )
    if not report.errors and content.runtime_defaults:
        report = await run_preview(
            item.channel,
            content,
            {
                key: value
                for key, value in content.preview_context.items()
                if key not in content.runtime_defaults
            },
            runtime,
            principal,
        )
    if report.errors:
        raise ApplicationError(
            422,
            detail={
                "code": "invalid_publication",
                "message": "Fix the saved draft's preview errors before publishing",
                "issues": [issue.model_dump() for issue in report.errors],
            },
        )
    previous = await head(db, branch.id)
    if previous and previous.draft_revision == branch.draft_revision:
        raise ApplicationError(
            409, "This saved draft revision has already been published"
        )
    published = TemplateVersion(
        id=uuid4(),
        template_id=template_id,
        branch_id=branch.id,
        number=previous.number + 1 if previous else 1,
        locale=branch.locale,
        content=content.model_dump(),
        draft_revision=branch.draft_revision,
        parent_version_id=previous.id if previous else branch.source_version_id,
        message=payload.message.strip(),
        actor_id=principal.account.id,
        created_at=utcnow(),
    )
    db.add(published)
    audit(db, principal.account.id, "template.publish", published.id)
    await commit(db)
    return VersionView(**(await summary(db, published)).model_dump(), content=content)


async def versions(
    template_id: UUID, db: AsyncSession, principal: Principal
) -> list[VersionSummary]:
    await lookup(db, principal, template_id)
    rows = await db.scalars(
        select(TemplateVersion)
        .where(TemplateVersion.template_id == template_id)
        .order_by(TemplateVersion.created_at.desc(), TemplateVersion.id)
    )
    return [await summary(db, row) for row in rows]


async def diff(
    template_id: UUID, before: UUID, after: UUID, db: AsyncSession, principal: Principal
) -> dict[str, object]:
    await lookup(db, principal, template_id)
    first, second = (
        await version(db, template_id, before),
        await version(db, template_id, after),
    )
    a, b = (
        DraftContent.model_validate(first.content),
        DraftContent.model_validate(second.content),
    )
    return {
        "before": VersionView(**(await summary(db, first)).model_dump(), content=a),
        "after": VersionView(**(await summary(db, second)).model_dump(), content=b),
        "issues": schema_changes(a, b),
    }


async def get_version(
    template_id: UUID, version_id: UUID, db: AsyncSession, principal: Principal
) -> VersionView:
    await lookup(db, principal, template_id)
    item = await version(db, template_id, version_id)
    return VersionView(
        **(await summary(db, item)).model_dump(),
        content=DraftContent.model_validate(item.content),
    )


async def version_preview(
    template_id: UUID,
    version_id: UUID,
    payload: PreviewInput,
    runtime: ApplicationContext,
    db: AsyncSession,
    principal: Principal,
) -> RenderResult:
    template = await lookup(db, principal, template_id)
    item = await version(db, template_id, version_id)
    if payload.draft is not None or payload.branch_id is not None:
        raise ApplicationError(
            422,
            "Published previews use immutable content; supply context or a saved scenario only",
        )
    content = DraftContent.model_validate(item.content)
    context = (
        payload.context if payload.context is not None else content.preview_context
    )
    if payload.scenario is not None:
        if payload.scenario not in content.scenarios:
            raise ApplicationError(422, "Preview scenario not found")
        context = content.scenarios[payload.scenario]
    return await run_preview(
        template.channel, content, context, runtime, principal, authoring=False
    )

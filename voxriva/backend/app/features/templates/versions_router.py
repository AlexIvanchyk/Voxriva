from uuid import UUID

from fastapi import APIRouter, Request

from backend.app.features.identity.dependencies import Database, PrincipalDependency
from backend.app.features.templates import versions_service as service
from backend.app.features.templates.rendering import RenderResult
from backend.app.features.templates.schemas import PreviewInput
from backend.app.features.templates.versions_schemas import (
    BranchInput,
    BranchView,
    LanguageInput,
    PrimaryLanguageInput,
    PublishInput,
    VersionSummary,
    VersionView,
)
from backend.app.infrastructure.http import application_context

root = "/templates/{template_id}"

router = APIRouter(prefix="/api/v1", tags=["Template lifecycle"])


@router.get(f"{root}/branches")
async def branches(
    template_id: UUID, db: Database, principal: PrincipalDependency
) -> list[BranchView]:
    return await service.branches(template_id=template_id, db=db, principal=principal)


@router.put(f"{root}/primary-language")
async def primary_language(
    template_id: UUID,
    payload: PrimaryLanguageInput,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, str]:
    return await service.primary_language(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.post(f"{root}/languages", status_code=201)
async def add_language(
    template_id: UUID,
    payload: LanguageInput,
    db: Database,
    principal: PrincipalDependency,
) -> BranchView:
    return await service.add_language(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.post(f"{root}/branches", status_code=201)
async def fork(
    template_id: UUID,
    payload: BranchInput,
    db: Database,
    principal: PrincipalDependency,
) -> BranchView:
    return await service.fork(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.post(f"{root}/publish", status_code=201)
async def publish(
    template_id: UUID,
    payload: PublishInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> VersionView:
    return await service.publish(
        template_id=template_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.get(f"{root}/versions")
async def versions(
    template_id: UUID, db: Database, principal: PrincipalDependency
) -> list[VersionSummary]:
    return await service.versions(template_id=template_id, db=db, principal=principal)


@router.get(f"{root}/versions/diff")
async def diff(
    template_id: UUID,
    before: UUID,
    after: UUID,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, object]:
    return await service.diff(
        template_id=template_id, before=before, after=after, db=db, principal=principal
    )


@router.get(f"{root}/versions/{{version_id}}")
async def get_version(
    template_id: UUID, version_id: UUID, db: Database, principal: PrincipalDependency
) -> VersionView:
    return await service.get_version(
        template_id=template_id, version_id=version_id, db=db, principal=principal
    )


@router.post(f"{root}/versions/{{version_id}}/preview")
async def version_preview(
    template_id: UUID,
    version_id: UUID,
    payload: PreviewInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> RenderResult:
    return await service.version_preview(
        template_id=template_id,
        version_id=version_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )

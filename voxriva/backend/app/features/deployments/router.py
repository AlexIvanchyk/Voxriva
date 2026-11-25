from uuid import UUID

from fastapi import APIRouter

from backend.app.features.deployments import service
from backend.app.features.deployments.schemas import (
    ChangeInput,
    DeployInput,
    DeploymentMatrix,
    FallbackInput,
    PromoteInput,
    Resolution,
)
from backend.app.features.identity.dependencies import Database, PrincipalDependency
from backend.app.features.templates.locales import Locale

root = "/templates/{template_id}"

router = APIRouter(prefix="/api/v1", tags=["Template lifecycle"])


@router.post(f"{root}/deployments/deploy")
async def deploy(
    template_id: UUID,
    payload: DeployInput,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, object]:
    return await service.deploy(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.post(f"{root}/deployments/promote")
async def promote(
    template_id: UUID,
    payload: PromoteInput,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, object]:
    return await service.promote(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.post(f"{root}/deployments/rollback")
async def rollback(
    template_id: UUID,
    payload: DeployInput,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, object]:
    return await service.rollback(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.post(f"{root}/deployments/clear")
async def clear(
    template_id: UUID,
    payload: ChangeInput,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, object]:
    return await service.clear(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.put(f"{root}/fallback")
async def fallback(
    template_id: UUID,
    payload: FallbackInput,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, str]:
    return await service.fallback(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.get(f"{root}/deployments")
async def matrix(
    template_id: UUID,
    db: Database,
    principal: PrincipalDependency,
    locale: Locale = "en",
) -> DeploymentMatrix:
    return await service.matrix(
        template_id=template_id, db=db, principal=principal, locale=locale
    )


@router.get(
    "/projects/{project_id}/environments/{environment_id}/templates/{template_id}/resolve"
)
async def resolve(
    project_id: UUID,
    environment_id: UUID,
    template_id: UUID,
    db: Database,
    principal: PrincipalDependency,
    locale: Locale = "en",
) -> Resolution:
    return await service.resolve(
        project_id=project_id,
        environment_id=environment_id,
        template_id=template_id,
        db=db,
        principal=principal,
        locale=locale,
    )

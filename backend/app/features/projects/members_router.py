from uuid import UUID

from fastapi import APIRouter, Request

from backend.app.features.identity.dependencies import Database, PrincipalDependency
from backend.app.features.projects import members_service as service
from backend.app.features.projects.members_schemas import (
    DirectoryMember,
    MemberCreate,
    MemberUpdate,
)
from backend.app.infrastructure.http import application_context

router = APIRouter(prefix="/api/v1/members", tags=["Member directory"])


@router.get("")
async def directory(
    db: Database, principal: PrincipalDependency
) -> list[DirectoryMember]:
    return await service.directory(db=db, principal=principal)


@router.post("", status_code=201)
async def add_member(
    payload: MemberCreate,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> DirectoryMember:
    return await service.add_member(
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.patch("/{account_id}")
async def update_member(
    account_id: UUID,
    payload: MemberUpdate,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, str]:
    return await service.update_member(
        account_id=account_id, payload=payload, db=db, principal=principal
    )

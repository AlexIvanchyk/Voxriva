from uuid import UUID

from fastapi import APIRouter, Response

from backend.app.features.identity.dependencies import Database, PrincipalDependency
from backend.app.features.management import service
from backend.app.features.management.schemas import (
    CredentialInput,
    CredentialView,
    IssuedCredential,
)

router = APIRouter(
    prefix="/api/v1/management-credentials", tags=["MCP management credentials"]
)


@router.get("")
async def list_credentials(
    db: Database, principal: PrincipalDependency
) -> list[CredentialView]:
    return await service.credentials(db, principal)


@router.post("", status_code=201)
async def issue_credential(
    payload: CredentialInput, db: Database, principal: PrincipalDependency
) -> IssuedCredential:
    return await service.issue(payload, db, principal)


@router.delete("/{identifier}", status_code=204)
async def revoke_credential(
    identifier: UUID, db: Database, principal: PrincipalDependency
) -> Response:
    await service.revoke(identifier, db, principal)
    return Response(status_code=204)

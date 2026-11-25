import hmac
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from fastapi.responses import PlainTextResponse

from backend.app.features.identity.dependencies import (
    Database,
    PrincipalDependency,
    session_principal,
)
from backend.app.features.notifications import operations_service as service
from backend.app.infrastructure.errors import ApplicationError

router = APIRouter(prefix="/api/v1/operations", tags=["Operations"])


@router.get("")
async def overview(
    db: Database,
    principal: PrincipalDependency,
    request: Request,
    project_id: UUID | None = None,
    environment_id: UUID | None = None,
) -> dict[str, Any]:
    return await service.overview(
        db=db,
        principal=principal,
        settings=request.app.state.settings,
        dependencies=request.app.state.dependencies,
        project_id=project_id,
        environment_id=environment_id,
    )


@router.get("/audit")
async def audit_history(
    db: Database,
    principal: PrincipalDependency,
    project_id: UUID | None = None,
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return await service.audit_history(
        db=db, principal=principal, project_id=project_id, offset=offset
    )


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(db: Database, request: Request) -> str:
    authorization = request.headers.get("Authorization")
    if authorization:
        token = request.app.state.settings.metrics_token
        if (
            token is None
            or not token.get_secret_value()
            or (
                not hmac.compare_digest(
                    authorization.encode(),
                    ("Bearer " + token.get_secret_value()).encode(),
                )
            )
        ):
            raise ApplicationError(401, "Invalid metrics credential")
    else:
        principal = await session_principal(request, db)
        if not principal.account.platform_admin:
            raise ApplicationError(403, "Platform administrator access required")
    return await service.metrics(
        db=db,
        settings=request.app.state.settings,
        dependencies=request.app.state.dependencies,
    )

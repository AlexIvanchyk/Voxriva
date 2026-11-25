from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials

from backend.app.features.identity.dependencies import (
    Database,
    PrincipalDependency,
    session_principal,
)
from backend.app.features.notifications import service
from backend.app.features.notifications.schemas import (
    Accepted,
    ApiProblem,
    NotificationDetail,
    NotificationInput,
    NotificationList,
    ReplayInput,
    State,
    ValidationResult,
)
from backend.app.features.notifications.service import DELIVERY_ERRORS
from backend.app.features.projects.dependencies import bearer, delivery_scope
from backend.app.features.projects.schemas import DeliveryScope
from backend.app.infrastructure.http import application_context

router = APIRouter(prefix="/api/v1/notifications", tags=["Notifications"])


@router.post(
    "/validate",
    summary="Validate runtime input without sending",
    responses=DELIVERY_ERRORS,
)
async def validate_notification(
    payload: NotificationInput,
    request: Request,
    db: Database,
    scope: Annotated[DeliveryScope, Depends(delivery_scope)],
) -> ValidationResult:
    return await service.validate_notification(
        payload=payload, runtime=application_context(request), db=db, scope=scope
    )


@router.post(
    "",
    status_code=202,
    responses={
        **DELIVERY_ERRORS,
        409: {
            "model": ApiProblem,
            "description": "Idempotency key conflicts with an existing request",
        },
    },
)
async def accept(
    payload: NotificationInput,
    request: Request,
    response: Response,
    db: Database,
    scope: Annotated[DeliveryScope, Depends(delivery_scope)],
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern="^[A-Za-z0-9._:-]+$")
    ],
) -> Accepted:
    result = await service.accept(
        payload=payload,
        runtime=application_context(request),
        db=db,
        scope=scope,
        idempotency_key=idempotency_key,
    )
    response.headers["Location"] = result.status_url
    return result


@router.get("")
async def history(
    request: Request,
    db: Database,
    principal: PrincipalDependency,
    project_id: UUID | None = None,
    environment_id: UUID | None = None,
    status: State | None = None,
    channel: Literal["email", "push"] | None = None,
    recipient_email: Annotated[str | None, Query(max_length=320)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationList:
    return await service.history(
        runtime=application_context(request),
        db=db,
        principal=principal,
        project_id=project_id,
        environment_id=environment_id,
        status=status,
        channel=channel,
        recipient_email=recipient_email,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{notification_id}",
    responses={401: {"model": ApiProblem}, 404: {"model": ApiProblem}},
)
async def detail(
    notification_id: UUID,
    request: Request,
    db: Database,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> NotificationDetail:
    scope = (
        await delivery_scope(db, credentials)
        if request.headers.get("Authorization")
        else None
    )
    principal = await session_principal(request, db) if scope is None else None
    return await service.detail(
        notification_id=notification_id,
        runtime=application_context(request),
        db=db,
        principal=principal,
        scope=scope,
    )


@router.post("/{notification_id}/replay", status_code=202)
async def replay_failed(
    notification_id: UUID,
    payload: ReplayInput,
    request: Request,
    response: Response,
    db: Database,
    principal: PrincipalDependency,
) -> Accepted:
    result = await service.replay_failed(
        notification_id=notification_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )
    response.headers["Location"] = result.status_url
    return result

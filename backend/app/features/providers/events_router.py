from uuid import UUID

from fastapi import APIRouter, Request

from backend.app.features.identity.dependencies import Database
from backend.app.features.providers import events_service as service
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.http import application_context

router = APIRouter(prefix="/api/v1/providers", tags=["Provider delivery events"])


@router.post("/{configuration_id}/events/ses", status_code=202)
async def ses_event(
    configuration_id: UUID, request: Request, db: Database
) -> dict[str, str]:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 262144:
            raise ApplicationError(413, "SNS message exceeds 256 KB")
    return await service.ses_event(
        configuration_id=configuration_id,
        body=bytes(body),
        runtime=application_context(request),
        db=db,
    )

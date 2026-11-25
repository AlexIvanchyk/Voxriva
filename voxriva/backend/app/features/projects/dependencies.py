from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select

from backend.app.features.identity.dependencies import Database
from backend.app.features.identity.service import digest
from backend.app.features.projects.models import DeliveryKey, Environment
from backend.app.features.projects.schemas import DeliveryScope
from backend.app.features.projects.service import KEY_FORMAT
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError

bearer = HTTPBearer(auto_error=False, scheme_name="Delivery API key")


async def delivery_scope(
    db: Database,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> DeliveryScope:
    if credentials is not None and KEY_FORMAT.fullmatch(credentials.credentials):
        row = (
            await db.execute(
                select(DeliveryKey.id, Environment.project_id, Environment.id)
                .join(Environment)
                .where(
                    DeliveryKey.token_hash == digest(credentials.credentials),
                    DeliveryKey.revoked_at.is_(None),
                    or_(
                        DeliveryKey.expires_at.is_(None),
                        DeliveryKey.expires_at > utcnow(),
                    ),
                )
            )
        ).one_or_none()
        if row is not None:
            key_id, project_id, environment_id = row
            return DeliveryScope(
                key_id=key_id, project_id=project_id, environment_id=environment_id
            )
    raise ApplicationError(
        401,
        "Invalid or inactive delivery API key",
        headers={"WWW-Authenticate": "Bearer"},
    )

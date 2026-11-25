import hmac
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.features.identity.models import Account, AccountMFA, DashboardSession
from backend.app.features.identity.schemas import Principal
from backend.app.features.identity.service import (
    KEY_FORMAT,
    cookie_name,
    csrf_for,
    digest,
)
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings


async def database_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] | None = request.app.state.session_factory
    if factory is None:
        raise ApplicationError(503, "Dashboard database is unavailable")
    async with factory() as session:
        yield session


Database = Annotated[AsyncSession, Depends(database_session)]


async def session_principal(request: Request, db: Database) -> Principal:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(cookie_name(settings), "")
    if not KEY_FORMAT.fullmatch(token):
        raise ApplicationError(401, "Sign in required")
    account = await db.scalar(
        select(Account)
        .join(DashboardSession, DashboardSession.account_id == Account.id)
        .where(
            DashboardSession.token_hash == digest(token),
            DashboardSession.expires_at > utcnow(),
        )
    )
    if account is None:
        raise ApplicationError(401, "Sign in required")
    if settings.mfa_policy == "required":
        factor = await db.get(AccountMFA, account.id)
        if factor is None or not factor.enabled:
            raise ApplicationError(401, "MFA enrollment required. Sign in again.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(csrf_for(token).encode(), supplied.encode()):
            raise ApplicationError(403, "Invalid CSRF token")
    return Principal(account, token)


PrincipalDependency = Annotated[Principal, Depends(session_principal)]


async def platform_admin(principal: PrincipalDependency) -> Principal:
    if not principal.account.platform_admin:
        raise ApplicationError(403, "Platform administrator access required")
    return principal


PlatformAdmin = Annotated[Principal, Depends(platform_admin)]

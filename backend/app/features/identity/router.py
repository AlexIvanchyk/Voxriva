import time
from typing import Annotated

from fastapi import APIRouter, Header, Request, Response

from backend.app.features.identity import mfa, service
from backend.app.features.identity.dependencies import Database, PrincipalDependency
from backend.app.features.identity.models import AccountMFA
from backend.app.features.identity.schemas import (
    Credentials,
    MFAChallengeView,
    MFACode,
    MFAEnrollment,
    MFAProof,
    MFAVerification,
    SessionView,
)
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings

auth = APIRouter(prefix="/api/v1/auth", tags=["Dashboard access"])


@auth.post("/login")
async def login(
    payload: Credentials,
    request: Request,
    response: Response,
    db: Database,
    client: Annotated[str | None, Header(alias="X-Voxriva-Client")] = None,
) -> SessionView | MFAChallengeView:
    if client != "dashboard":
        raise ApplicationError(403, "Dashboard request header required")
    throttle(request, "password", 20)
    settings = request.app.state.settings
    name = service.cookie_name(settings)
    view, token, duration = await service.login(
        payload,
        db,
        settings,
        request.app.state.password_slots,
        request.cookies.get(name, ""),
    )
    if token:
        session_cookie(response, settings, token, duration)
    else:
        response.delete_cookie(
            name,
            httponly=True,
            secure=settings.secure_session_cookie,
            samesite="strict",
        )
    return view


@auth.get("/session")
async def current_session(principal: PrincipalDependency) -> SessionView:
    return await service.current_session(principal=principal)


@auth.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, db: Database, principal: PrincipalDependency
) -> None:
    await service.logout(db, principal)
    settings = request.app.state.settings
    response.delete_cookie(
        service.cookie_name(settings),
        httponly=True,
        secure=settings.secure_session_cookie,
        samesite="strict",
    )


def session_cookie(
    response: Response, settings: Settings, token: str, duration: int
) -> None:
    response.set_cookie(
        service.cookie_name(settings),
        token,
        max_age=duration,
        httponly=True,
        secure=settings.secure_session_cookie,
        samesite="strict",
    )


@auth.post("/mfa/verify")
async def verify_login(
    payload: MFAVerification,
    request: Request,
    response: Response,
    db: Database,
    client: Annotated[str | None, Header(alias="X-Voxriva-Client")] = None,
) -> SessionView:
    if client != "dashboard":
        raise ApplicationError(403, "Dashboard request header required")
    throttle(request, "factor", 60)
    view, token, duration = await mfa.complete(
        db, payload.challenge, payload.code, request.app.state.settings
    )
    session_cookie(response, request.app.state.settings, token, duration)
    return view


@auth.get("/mfa")
async def mfa_status(
    request: Request, db: Database, principal: PrincipalDependency
) -> dict[str, object]:
    state = await db.get(AccountMFA, principal.account.id)
    return {
        "policy": request.app.state.settings.mfa_policy,
        "enabled": bool(state and state.enabled),
        "recovery_codes_remaining": len(state.recovery_hashes)
        if state and state.enabled
        else 0,
    }


@auth.post("/mfa/setup")
async def mfa_setup(
    payload: MFAProof, request: Request, db: Database, principal: PrincipalDependency
) -> dict[str, str]:
    async with request.app.state.password_slots:
        return await mfa.setup(
            db,
            principal.account.id,
            payload.password,
            request.app.state.settings,
            payload.code,
        )


@auth.post("/mfa/confirm")
async def mfa_confirm(
    payload: MFACode, request: Request, db: Database, principal: PrincipalDependency
) -> dict[str, list[str]]:
    return {
        "recovery_codes": await mfa.confirm(
            db,
            principal.account.id,
            payload.code,
            request.app.state.settings,
            principal.token,
        )
    }


@auth.post("/mfa/recovery-codes")
async def mfa_regenerate(
    payload: MFAProof, request: Request, db: Database, principal: PrincipalDependency
) -> dict[str, list[str]]:
    async with request.app.state.password_slots:
        codes = await mfa.change(
            db,
            principal.account.id,
            payload.password,
            payload.code,
            request.app.state.settings,
            principal.token,
            False,
        )
    return {"recovery_codes": codes}


@auth.post("/mfa/disable", status_code=204)
async def mfa_disable(
    payload: MFAProof, request: Request, db: Database, principal: PrincipalDependency
) -> None:
    async with request.app.state.password_slots:
        await mfa.change(
            db,
            principal.account.id,
            payload.password,
            payload.code,
            request.app.state.settings,
            principal.token,
            True,
        )


@auth.post("/mfa/enroll/setup")
async def required_setup(
    payload: MFAEnrollment,
    request: Request,
    db: Database,
    client: Annotated[str | None, Header(alias="X-Voxriva-Client")] = None,
) -> dict[str, str]:
    if client != "dashboard":
        raise ApplicationError(403, "Dashboard request header required")
    account, state = await mfa.enrollment_challenge(db, payload.challenge)
    return await mfa.start_setup(db, account, state, request.app.state.settings)


@auth.post("/mfa/enroll/confirm")
async def required_confirm(
    payload: MFAVerification,
    request: Request,
    response: Response,
    db: Database,
    client: Annotated[str | None, Header(alias="X-Voxriva-Client")] = None,
) -> dict[str, object]:
    if client != "dashboard":
        raise ApplicationError(403, "Dashboard request header required")
    account, _ = await mfa.enrollment_challenge(db, payload.challenge)
    codes = await mfa.confirm(
        db, account.id, payload.code, request.app.state.settings, "", commit=False
    )
    view, token, duration = await service.issue_session(
        db, account, request.app.state.settings
    )
    session_cookie(response, request.app.state.settings, token, duration)
    return {"session": view, "recovery_codes": codes}


def throttle(request: Request, category: str, limit: int) -> None:
    # Per-process IP burst protection complements the durable, account-wide MFA lock.
    # Trust the socket peer, never arbitrary X-Forwarded-For input.
    now = time.monotonic()
    limits = request.app.state.auth_limits
    if len(limits) > 10000:
        for key in list(limits):
            if limits[key][0] <= now - 60:
                del limits[key]
        if len(limits) > 10000:
            raise ApplicationError(429, "Too many sign-in attempts. Try again later.")
    key = (category, request.client.host if request.client else "unknown")
    began, count = limits.get(key, (now, 0))
    if now - began >= 60:
        began, count = now, 0
    limits[key] = (began, count + 1)
    if count >= limit:
        raise ApplicationError(429, "Too many sign-in attempts. Try again in a minute.")

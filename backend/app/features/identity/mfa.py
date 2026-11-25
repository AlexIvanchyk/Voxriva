"""TOTP lifecycle. Account row locks serialize factor use and recovery redemption."""

import base64
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from cryptography.hazmat.primitives.hashes import SHA1
from cryptography.hazmat.primitives.twofactor import InvalidToken
from cryptography.hazmat.primitives.twofactor.totp import TOTP
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.identity.models import (
    Account,
    AccountMFA,
    DashboardSession,
    MFAChallenge,
)
from backend.app.features.identity.schemas import SessionView
from backend.app.features.identity.service import audit, digest, password_matches
from backend.app.features.providers.adapters.crypto import decrypt, encrypt
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def totp(secret: str) -> TOTP:
    return TOTP(base64.b32decode(secret), 6, SHA1(), 30)


def matching_step(secret: str, code: str, last: int, now: datetime) -> int | None:
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    step = int(now.timestamp()) // 30
    for candidate in (step, step - 1, step + 1):
        if candidate <= last:
            continue
        try:
            totp(secret).verify(code.encode(), candidate * 30)
            return candidate
        except InvalidToken:
            pass
    return None


async def locked(db: AsyncSession, account_id: UUID) -> tuple[Account, AccountMFA]:
    account = await db.scalar(
        select(Account)
        .where(Account.id == account_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if account is None:
        raise ApplicationError(401, "Sign in required")
    state = await db.get(AccountMFA, account.id, populate_existing=True)
    if state is None:
        state = AccountMFA(
            account_id=account.id,
            enabled=False,
            last_step=-1,
            recovery_hashes=[],
            failures=0,
        )
        db.add(state)
        await db.flush()
    if state.locked_until and aware(state.locked_until) > utcnow():
        raise ApplicationError(429, "Too many attempts. Try again in five minutes.")
    if state.locked_until:
        state.failures = 0
        state.locked_until = None
    return account, state


async def reject(db: AsyncSession, state: AccountMFA) -> None:
    audit(db, state.account_id, "mfa.proof_failed", state.account_id)
    state.failures += 1
    if state.failures >= 5:
        state.locked_until = utcnow() + timedelta(minutes=5)
    await db.commit()
    raise ApplicationError(401, "Invalid or already used verification code")


def stored_seeds(settings: Settings, state: AccountMFA) -> dict[str, str]:
    try:
        return decrypt(settings, state.secret or "")
    except ApplicationError:
        raise ApplicationError(
            503,
            "Authenticator verification is unavailable. Contact the installation operator.",
        ) from None


async def verify(
    db: AsyncSession,
    state: AccountMFA,
    code: str,
    settings: Settings,
    recovery: bool = True,
) -> None:
    secret = stored_seeds(settings, state)["totp"]
    step = matching_step(secret, code, state.last_step, utcnow())
    if step is not None:
        state.last_step = step
    else:
        hashed = digest(code.strip().replace("-", "").lower())
        match = (
            next(
                (
                    value
                    for value in state.recovery_hashes
                    if hmac.compare_digest(value, hashed)
                ),
                None,
            )
            if recovery
            else None
        )
        if match is None:
            await reject(db, state)
        state.recovery_hashes = [
            value for value in state.recovery_hashes if value != match
        ]
    state.failures = 0
    state.locked_until = None


def recovery_codes(state: AccountMFA) -> list[str]:
    codes = [secrets.token_hex(10) for _ in range(10)]
    state.recovery_hashes = [digest(code) for code in codes]
    return ["-".join(code[i : i + 5] for i in range(0, 20, 5)) for code in codes]


async def reauthenticate(
    db: AsyncSession,
    account: Account,
    state: AccountMFA,
    password: str,
    code: str,
    settings: Settings,
) -> None:
    if not await password_matches(password, account.password_hash):
        await reject(db, state)
    if state.enabled:
        await verify(db, state, code, settings)


async def invalidate(db: AsyncSession, account: Account, keep: str = "") -> None:
    await db.execute(delete(MFAChallenge).where(MFAChallenge.account_id == account.id))
    await db.execute(
        delete(DashboardSession).where(
            DashboardSession.account_id == account.id,
            DashboardSession.token_hash != digest(keep),
        )
    )


async def setup(
    db: AsyncSession,
    account_id: UUID,
    password: str,
    settings: Settings,
    code: str = "",
) -> dict[str, str]:
    account, state = await locked(db, account_id)
    await reauthenticate(db, account, state, password, code, settings)
    return await start_setup(db, account, state, settings)


async def start_setup(
    db: AsyncSession, account: Account, state: AccountMFA, settings: Settings
) -> dict[str, str]:
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    seeds = stored_seeds(settings, state) if state.enabled else {}
    seeds["pending_totp" if state.enabled else "totp"] = secret
    try:
        state.secret = encrypt(settings, seeds)
    except ApplicationError:
        raise ApplicationError(
            503,
            "Authenticator setup is unavailable. Contact the installation operator.",
        ) from None
    state.setup_expires_at = utcnow() + timedelta(minutes=10)
    if not state.enabled:
        state.last_step = -1
    audit(
        db,
        account.id,
        "mfa.replace_setup" if state.enabled else "mfa.setup",
        account.id,
    )
    await db.commit()
    return {
        "secret": secret,
        "uri": totp(secret).get_provisioning_uri(account.email, "Voxriva"),
    }


async def confirm(
    db: AsyncSession,
    account_id: UUID,
    code: str,
    settings: Settings,
    keep: str,
    commit: bool = True,
) -> list[str]:
    account, state = await locked(db, account_id)
    if not state.setup_expires_at or aware(state.setup_expires_at) <= utcnow():
        raise ApplicationError(409, "Authenticator setup expired. Start setup again.")
    replacing = state.enabled
    seeds = stored_seeds(settings, state)
    secret = seeds.get("pending_totp" if replacing else "totp")
    if secret is None:
        raise ApplicationError(409, "Start authenticator setup again.")
    step = matching_step(secret, code, -1, utcnow())
    if step is None:
        await reject(db, state)
    assert step is not None
    state.last_step = step
    state.secret = encrypt(settings, {"totp": secret})
    state.failures = 0
    state.locked_until = None
    state.enabled = True
    state.setup_expires_at = None
    codes = recovery_codes(state)
    await invalidate(db, account, keep)
    audit(db, account.id, "mfa.replaced" if replacing else "mfa.enabled", account.id)
    if commit:
        await db.commit()
    return codes


async def change(
    db: AsyncSession,
    account_id: UUID,
    password: str,
    code: str,
    settings: Settings,
    keep: str,
    disable: bool,
) -> list[str]:
    account, state = await locked(db, account_id)
    if disable and settings.mfa_policy == "required":
        raise ApplicationError(
            409,
            "This installation requires MFA. Replace your authenticator instead of disabling MFA.",
        )
    if not state.enabled:
        raise ApplicationError(409, "MFA is not enabled")
    await reauthenticate(db, account, state, password, code, settings)
    codes = [] if disable else recovery_codes(state)
    if disable:
        state.enabled = False
        state.secret = None
        state.setup_expires_at = None
        state.recovery_hashes = []
        state.last_step = -1
    await invalidate(db, account, keep)
    audit(
        db,
        account.id,
        "mfa.disabled" if disable else "mfa.recovery_regenerated",
        account.id,
    )
    await db.commit()
    return codes


async def complete(
    db: AsyncSession, challenge: str, code: str, settings: Settings
) -> tuple[SessionView, str, int]:
    from backend.app.features.identity.service import issue_session

    pending = await db.get(MFAChallenge, digest(challenge))
    if pending is None:
        raise ApplicationError(
            401, "Verification expired or unavailable. Sign in again."
        )
    account, state = await locked(db, pending.account_id)
    # Re-read after acquiring account lock: another request may have consumed it.
    pending = await db.get(MFAChallenge, digest(challenge), populate_existing=True)
    if pending is None or aware(pending.expires_at) <= utcnow() or not state.enabled:
        raise ApplicationError(
            401, "Verification expired or unavailable. Sign in again."
        )
    await verify(db, state, code, settings)
    await db.execute(delete(MFAChallenge).where(MFAChallenge.account_id == account.id))
    audit(db, account.id, "mfa.login", account.id)
    return await issue_session(db, account, settings)


async def enrollment_challenge(
    db: AsyncSession, challenge: str
) -> tuple[Account, AccountMFA]:
    pending = await db.get(MFAChallenge, digest(challenge))
    if pending is None:
        raise ApplicationError(
            401, "Verification expired or unavailable. Sign in again."
        )
    account, state = await locked(db, pending.account_id)
    pending = await db.get(MFAChallenge, digest(challenge), populate_existing=True)
    if pending is None or aware(pending.expires_at) <= utcnow() or state.enabled:
        raise ApplicationError(
            401, "Verification expired or unavailable. Sign in again."
        )
    return account, state

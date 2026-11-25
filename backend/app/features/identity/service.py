import asyncio
import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.features.identity.models import (
    Account,
    AuditEvent,
    BootstrapLock,
    DashboardSession,
)
from backend.app.features.identity.schemas import (
    AccountView,
    Credentials,
    MFAChallengeView,
    NewAccount,
    Principal,
    SessionView,
)
from backend.app.infrastructure.database import utcnow
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings

KEY_FORMAT = re.compile("[A-Za-z0-9_-]{43}")
COOKIE_HTTP = "voxriva_session"
COOKIE_HTTPS = "__Host-voxriva_session"
DUMMY_HASH = "00000000000000000000000000000000:0000000000000000000000000000000000000000000000000000000000000000"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_digest(password: str, salt: bytes) -> str:
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=2**17,
        r=8,
        p=1,
        maxmem=160 * 1024 * 1024,
        dklen=32,
    ).hex()


async def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"{salt.hex()}:{await asyncio.to_thread(password_digest, password, salt)}"


async def password_matches(password: str, encoded: str) -> bool:
    salt, expected = encoded.split(":")
    result = await asyncio.to_thread(password_digest, password, bytes.fromhex(salt))
    return hmac.compare_digest(result, expected)


def csrf_for(token: str) -> str:
    return hmac.digest(token.encode(), b"voxriva:dashboard-csrf:v1", "sha256").hex()


def cookie_name(settings: Settings) -> str:
    return COOKIE_HTTPS if settings.secure_session_cookie else COOKIE_HTTP


def audit(
    db: AsyncSession,
    actor: UUID,
    action: str,
    target: UUID,
    project: UUID | None = None,
) -> None:
    db.add(
        AuditEvent(actor_id=actor, action=action, target_id=target, project_id=project)
    )


async def commit(
    db: AsyncSession, conflict: str = "A conflicting record already exists"
) -> None:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise ApplicationError(409, conflict) from None


async def create_initial_admin(db: AsyncSession, payload: NewAccount) -> Account:
    account = Account(
        id=uuid4(),
        email=payload.email,
        password_hash=await hash_password(payload.password),
        platform_admin=True,
    )
    db.add_all([BootstrapLock(id=1), account])
    audit(db, account.id, "account.bootstrap", account.id)
    await commit(db, "The initial platform administrator has already been created")
    return account


def session_view(principal: Principal) -> SessionView:
    return SessionView(
        account=AccountView.model_validate(principal.account),
        csrf_token=csrf_for(principal.token),
    )


async def login(
    payload: Credentials,
    db: AsyncSession,
    settings: Settings,
    password_slots: asyncio.Semaphore,
    previous: str = "",
) -> tuple[SessionView | MFAChallengeView, str, int]:
    account = await db.scalar(select(Account).where(Account.email == payload.email))
    encoded = account.password_hash if account is not None else DUMMY_HASH
    async with password_slots:
        matches = await password_matches(payload.password, encoded)
    if account is None or not matches:
        raise ApplicationError(401, "Incorrect email or password")
    from backend.app.features.identity import mfa
    from backend.app.features.identity.models import MFAChallenge

    account, state = await mfa.locked(db, account.id)
    if KEY_FORMAT.fullmatch(previous):
        await db.execute(
            delete(DashboardSession).where(
                DashboardSession.token_hash == digest(previous)
            )
        )
    await db.execute(delete(MFAChallenge).where(MFAChallenge.account_id == account.id))
    if state.enabled or settings.mfa_policy == "required":
        challenge = secrets.token_urlsafe(32)
        db.add(
            MFAChallenge(
                token_hash=digest(challenge),
                account_id=account.id,
                expires_at=utcnow() + timedelta(minutes=5),
            )
        )
        await db.commit()
        return (
            MFAChallengeView(
                challenge=challenge, enrollment_required=not state.enabled
            ),
            "",
            0,
        )
    return await issue_session(db, account, settings)


async def issue_session(
    db: AsyncSession, account: Account, settings: Settings
) -> tuple[SessionView, str, int]:
    await db.execute(
        delete(DashboardSession).where(
            DashboardSession.account_id == account.id,
            DashboardSession.expires_at <= utcnow(),
        )
    )
    token = secrets.token_urlsafe(32)
    duration = settings.session_hours * 3600
    db.add(
        DashboardSession(
            token_hash=digest(token),
            account_id=account.id,
            expires_at=utcnow() + timedelta(seconds=duration),
        )
    )
    await db.commit()
    return (session_view(Principal(account, token)), token, duration)


async def current_session(principal: Principal) -> SessionView:
    return session_view(principal)


async def logout(db: AsyncSession, principal: Principal) -> None:
    await db.execute(
        delete(DashboardSession).where(
            DashboardSession.token_hash == digest(principal.token)
        )
    )
    await db.commit()

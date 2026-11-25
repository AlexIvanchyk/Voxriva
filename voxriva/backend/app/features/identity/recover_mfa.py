"""Local operator recovery; no HTTP reset endpoint exists."""

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.features.identity import mfa
from backend.app.features.identity.models import Account, AccountMFA
from backend.app.features.identity.service import audit
from backend.app.infrastructure import model_registry as model_registry
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings


async def reset(db: AsyncSession, email: str) -> None:
    # Operator recovery must also work during a failed-attempt lockout.
    account = await db.scalar(
        select(Account).where(Account.email == email).with_for_update()
    )
    if account is None:
        raise ApplicationError(404, "Account not found")
    state = await db.get(AccountMFA, account.id)
    if state:
        state.enabled = False
        state.secret = None
        state.setup_expires_at = None
        state.last_step = -1
        state.recovery_hashes = []
        state.failures = 0
        state.locked_until = None
    await mfa.invalidate(db, account)
    audit(db, account.id, "mfa.operator_reset", account.id)
    await db.commit()


async def recover(database_url: str, email: str) -> None:
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await reset(db, email)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset an account's MFA after verifying its owner out of band; revokes all dashboard sessions."
    )
    parser.add_argument("--email", required=True)
    options = parser.parse_args()
    settings = Settings()
    if not settings.database_url:
        parser.exit(1, "Configure VOXRIVA_DATABASE_URL or its file setting.\n")
    if not sys.stdin.isatty():
        parser.exit(1, "Run recovery in an interactive operator terminal.\n")
    email = options.email.strip().lower()
    if (
        input(
            "Verify the account owner out of band first. Type the account email to reset MFA: "
        )
        .strip()
        .lower()
        != email
    ):
        parser.exit(1, "Recovery cancelled.\n")
    try:
        asyncio.run(recover(settings.database_url, email))
    except ApplicationError as error:
        parser.exit(1, f"{error.detail}\n")
    print(
        "MFA reset; dashboard sessions revoked. The account password is unchanged. Required policy enforces enrollment on next sign-in."
    )


if __name__ == "__main__":
    main()

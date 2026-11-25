import argparse
import asyncio
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.features.identity.schemas import NewAccount
from backend.app.features.identity.service import create_initial_admin
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings


async def bootstrap(database_url: str, account: NewAccount) -> None:
    engine = create_async_engine(database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await create_initial_admin(db, account)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create the first Voxriva platform administrator"
    )
    parser.add_argument("--email", required=True)
    options = parser.parse_args()
    database_url = Settings().database_url
    if not database_url:
        parser.exit(1, "Set VOXRIVA_DATABASE_URL before running bootstrap.\n")
    if not sys.stdin.isatty():
        parser.exit(1, "Run bootstrap in an interactive terminal.\n")
    password = getpass.getpass("Password (at least 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.exit(1, "Passwords do not match.\n")
    try:
        asyncio.run(
            bootstrap(database_url, NewAccount(email=options.email, password=password))
        )
    except ValidationError:
        parser.exit(
            1, "Enter a valid email and a password between 12 and 256 characters.\n"
        )
    except ApplicationError as error:
        parser.exit(1, f"{error.detail}\n")
    print("Platform administrator created.")


if __name__ == "__main__":
    main()

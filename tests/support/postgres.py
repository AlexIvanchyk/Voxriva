"""Opt-in PostgreSQL fixture with a unique, disposable schema per test.

TEST_DATABASE_URL must point to a dedicated test PostgreSQL database. Nothing in
public is changed; only the randomly named schema created here is dropped.
"""

import asyncio
import os
from importlib import import_module
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.features.identity.schemas import NewAccount
from backend.app.features.identity.service import create_initial_admin
from tests.support.administration import ADMIN, PASSWORD


@pytest.fixture
def postgres_store():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Set TEST_DATABASE_URL to run real PostgreSQL locking/transaction tests"
        )
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use postgresql+asyncpg://")
    schema = f"test_voxriva_{uuid4().hex}"
    admin = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={"server_settings": {"search_path": schema}},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    def migrate(connection):
        with Operations.context(MigrationContext.configure(connection)):
            revisions = sorted(
                (Path(__file__).resolve().parents[2] / "migrations/versions").glob(
                    "[0-9]*.py"
                )
            )
            for revision in revisions:
                import_module(f"migrations.versions.{revision.stem}").upgrade()

    async def initialize():
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(migrate)
        async with factory() as db:
            await create_initial_admin(db, NewAccount(email=ADMIN, password=PASSWORD))

    async def cleanup():
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

    try:
        asyncio.run(initialize())
        yield engine, factory
    finally:
        asyncio.run(cleanup())

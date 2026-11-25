"""Application builders, synthetic accounts and a migrated SQLite fixture."""

import asyncio
from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Session

from backend.app.features.identity.dependencies import database_session
from backend.app.features.identity.schemas import NewAccount
from backend.app.features.identity.service import create_initial_admin
from backend.app.infrastructure.settings import Settings

PASSWORD = "Synthetic fixture password"

ADMIN = "admin@example.test"

TENANT = "tenant@example.test"

VIEWER = "viewer@example.test"

ROOT = "/api/v1"

LOGIN_HEADERS = {"X-Voxriva-Client": "dashboard"}


def application(store, secure=False):
    from backend.app.main import create_app

    _, factory = store
    app = create_app(Settings(secure_session_cookie=secure))

    async def local_database():
        async with factory() as session:
            yield session

    app.dependency_overrides[database_session] = local_database
    return app


def sign_in(client, email=ADMIN, password=PASSWORD):
    response = client.post(
        f"{ROOT}/auth/login",
        headers=LOGIN_HEADERS,
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response


def create(client, path, **payload):
    response = client.post(f"{ROOT}{path}", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'access.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    with (
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        for revision in [
            "0002_dashboard_access",
            "0003_templates",
            "0004_project_workspaces",
            "0005_template_lifecycle",
            "0006_providers",
            "0007_notifications",
            "0008_delivery_recovery",
            "0009_cloud_providers",
            "0010_template_languages",
            "0011_notification_recipients",
            "0012_management_credentials",
            "0013_account_mfa",
        ]:
            import_module(f"migrations.versions.{revision}").upgrade()

    class LocalSession(Session):
        def __init__(self, **kwargs):
            super().__init__(**{**kwargs, "bind": engine})

    factory = async_sessionmaker(
        sync_session_class=LocalSession, expire_on_commit=False
    )

    async def bootstrap():
        async with factory() as db:
            await create_initial_admin(db, NewAccount(email=ADMIN, password=PASSWORD))

    asyncio.run(bootstrap())
    yield engine, factory
    engine.dispose()

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.features.identity.schemas import NewAccount
from backend.app.features.identity.service import (
    COOKIE_HTTP,
    COOKIE_HTTPS,
    create_initial_admin,
    digest,
)
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.model_registry import (
    Account,
    AuditEvent,
    DashboardSession,
    DeliveryKey,
    Membership,
    utcnow,
)
from tests.support.administration import (
    ADMIN,
    LOGIN_HEADERS,
    PASSWORD,
    ROOT,
    TENANT,
    VIEWER,
    application,
    create,
    sign_in,
)


def test_session_security_rotation_and_csrf(store):
    app = application(store, secure=True)
    engine, _ = store
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get(f"{ROOT}/projects").status_code == 401
        assert (
            client.post(
                f"{ROOT}/auth/login", json={"email": ADMIN, "password": PASSWORD}
            ).status_code
            == 403
        )
        assert (
            client.post(
                f"{ROOT}/auth/login",
                headers=LOGIN_HEADERS,
                json={"email": ADMIN, "password": "wrong"},
            ).status_code
            == 401
        )
        first = sign_in(client)
        for value in [COOKIE_HTTPS, "Secure", "HttpOnly", "SameSite=strict", "Path=/"]:
            assert value in first.headers["set-cookie"]
        token = client.cookies[COOKIE_HTTPS]
        assert client.get(f"{ROOT}/auth/session").json()["account"]["email"] == ADMIN
        client.headers.pop("X-CSRF-Token")
        assert (
            client.post(f"{ROOT}/projects", json={"name": "Denied"}).status_code == 403
        )
        sign_in(client)
        with Session(engine) as db:
            assert db.get(DashboardSession, digest(token)) is None
        assert client.post(f"{ROOT}/auth/logout").status_code == 204
        assert client.get(f"{ROOT}/projects").status_code == 401


def test_bootstrap_and_validation_do_not_expose_passwords(store):
    _, factory = store

    async def duplicate():
        async with factory() as db:
            with pytest.raises(ApplicationError) as error:
                await create_initial_admin(
                    db, NewAccount(email="other@example.test", password=PASSWORD)
                )
            assert error.value.status_code == 409

    asyncio.run(duplicate())
    with TestClient(application(store)) as client:
        sign_in(client)
        project = create(client, "/projects", name="Storefront")
        response = client.post(
            f"{ROOT}/projects/{project['id']}/members",
            json={"email": VIEWER, "password": "tiny-secret", "role": "viewer"},
        )
        assert response.status_code == 422
        assert "tiny-secret" not in response.text
        assert response.headers["cache-control"] == "no-store"
        assert client.get(f"{ROOT}/organizations").status_code == 404
        assert (
            client.post(
                f"{ROOT}/accounts", json={"email": VIEWER, "password": PASSWORD}
            ).status_code
            == 404
        )


def test_project_isolation_roles_and_atomic_member_creation(store):
    app = application(store)
    engine, _ = store
    with TestClient(app) as admin:
        sign_in(admin)
        a = create(admin, "/projects", name="Storefront")
        b = create(admin, "/projects", name="Private app")
        first, other = (f"/projects/{project['id']}" for project in [a, b])
        member = create(
            admin,
            f"{first}/members",
            email=TENANT,
            display_name="Taylor Example",
            password=PASSWORD,
            role="project_admin",
        )
        assert (
            member["display_name"] == "Taylor Example"
            and member["role"] == "project_admin"
        )
        assert "password" not in member and not member["inherited"]
        env = create(admin, f"{other}/environments", name="production")
        with TestClient(app) as tenant:
            sign_in(tenant, TENANT)
            assert [row["id"] for row in tenant.get(f"{ROOT}/projects").json()] == [
                a["id"]
            ]
            assert tenant.get(f"{ROOT}{other}").status_code == 404
            assert tenant.get(f"{ROOT}{other}/members").status_code == 404
            assert (
                tenant.get(f"{ROOT}{first}/environments/{env['id']}").status_code == 404
            )
            assert tenant.get(f"{ROOT}/system/status").status_code == 403
            assert (
                tenant.post(f"{ROOT}/projects", json={"name": "Denied"}).status_code
                == 403
            )
            # Project admins can create a user and membership in one operation.
            viewer = create(
                tenant,
                f"{first}/members",
                email=VIEWER,
                password=PASSWORD,
                role="viewer",
            )
            assert (
                tenant.patch(
                    f"{ROOT}{first}/members/{member['account_id']}",
                    json={"role": "viewer"},
                ).status_code
                == 403
            )
            with TestClient(app) as reader:
                sign_in(reader, VIEWER)
                assert reader.get(f"{ROOT}{first}/members").status_code == 200
                assert (
                    reader.post(
                        f"{ROOT}{first}/environments", json={"name": "Denied"}
                    ).status_code
                    == 403
                )
                assert (
                    reader.post(
                        f"{ROOT}{first}/members",
                        json={
                            "email": "no@example.test",
                            "role": "viewer",
                            "password": PASSWORD,
                        },
                    ).status_code
                    == 403
                )
                assert (
                    tenant.patch(
                        f"{ROOT}{first}/members/{viewer['account_id']}",
                        json={"role": "operator"},
                    ).status_code
                    == 200
                )
                assert reader.get(f"{ROOT}{first}").json()["role"] == "operator"
                assert (
                    tenant.delete(
                        f"{ROOT}{first}/members/{viewer['account_id']}"
                    ).status_code
                    == 204
                )
                assert reader.get(f"{ROOT}{first}").status_code == 404
        with Session(engine) as db:
            assert db.scalar(select(Account).where(Account.email == VIEWER)) is not None
            assert db.scalar(select(func.count()).select_from(Membership)) == 1
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "account.create")
                )
                == 2
            )


def test_existing_users_keep_password_and_profile_when_granted_another_project(store):
    engine, _ = store
    with TestClient(application(store)) as client:
        sign_in(client)
        a = create(client, "/projects", name="A")
        b = create(client, "/projects", name="B")
        path = f"/projects/{a['id']}/members"
        user = create(
            client,
            path,
            email=VIEWER,
            display_name="Original name",
            password=PASSWORD,
            role="viewer",
        )
        with Session(engine) as db:
            original_hash = db.get(Account, UUID(user["account_id"])).password_hash
            count = db.scalar(select(func.count()).select_from(AuditEvent))
        duplicate = client.post(
            f"{ROOT}{path}", json={"email": VIEWER, "role": "viewer"}
        )
        assert duplicate.status_code == 409
        rejected = client.post(
            f"{ROOT}/projects/{b['id']}/members",
            json={
                "email": VIEWER,
                "password": "Different synthetic password",
                "role": "project_admin",
            },
        )
        assert rejected.status_code == 409
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(AuditEvent)) == count
        second = create(
            client,
            f"/projects/{b['id']}/members",
            email=VIEWER,
            role="operator",
            display_name="Ignored overwrite",
        )
        assert (
            second["account_id"] == user["account_id"]
            and second["display_name"] == "Original name"
        )
        with Session(engine) as db:
            assert (
                db.get(Account, UUID(user["account_id"])).password_hash == original_hash
            )
        inherited = client.get(f"{ROOT}{path}").json()
        assert any(
            row["email"] == ADMIN
            and row["inherited"]
            and row["role"] == "platform_admin"
            for row in inherited
        )
        assert (
            client.post(
                f"{ROOT}{path}", json={"email": "new@example.test", "role": "viewer"}
            ).status_code
            == 422
        )
        with Session(engine) as db:
            assert (
                db.scalar(select(Account).where(Account.email == "new@example.test"))
                is None
            )


def test_keys_return_secret_once_and_expire_revoke_and_cascade(store):
    engine, _ = store
    app = application(store)
    with TestClient(app) as client, TestClient(app) as delivery:
        sign_in(client)
        project = create(client, "/projects", name="Commerce")
        base = f"/projects/{project['id']}"
        env = create(client, f"{base}/environments", name="dev")
        production = create(client, f"{base}/environments", name="prod")
        path = f"{base}/environments/{env['id']}/keys"
        key = create(client, path, name="Integration")
        delivery.headers["Authorization"] = f"Bearer {key['key']}"
        assert delivery.get(f"{ROOT}/delivery/scope").json() == {
            "key_id": key["id"],
            "project_id": project["id"],
            "environment_id": env["id"],
        }
        assert delivery.get(f"{ROOT}/projects").status_code == 401
        assert delivery.get(f"{ROOT}/templates").status_code == 401
        listed = client.get(f"{ROOT}{path}").json()[0]
        assert "key" not in listed and "token_hash" not in listed
        assert (
            client.delete(
                f"{ROOT}{base}/environments/{production['id']}/keys/{key['id']}"
            ).status_code
            == 404
        )
        with engine.begin() as connection:
            connection.execute(
                update(DeliveryKey)
                .where(DeliveryKey.id == UUID(key["id"]))
                .values(expires_at=utcnow() - timedelta(seconds=1))
            )
        assert delivery.get(f"{ROOT}/delivery/scope").status_code == 401
        new = create(client, path, name="New", expires_in_days=None)
        delivery.headers["Authorization"] = f"Bearer {new['key']}"
        assert delivery.get(f"{ROOT}/delivery/scope").status_code == 200
        assert client.delete(f"{ROOT}{path}/{new['id']}").status_code == 204
        assert delivery.get(f"{ROOT}/delivery/scope").status_code == 401
        last = create(client, path, name="Cascade")
        delivery.headers["Authorization"] = f"Bearer {last['key']}"
        assert (
            client.delete(f"{ROOT}{base}/environments/{env['id']}").status_code == 204
        )
        assert delivery.get(f"{ROOT}/delivery/scope").status_code == 401


def test_expired_dashboard_session_is_rejected(store):
    engine, _ = store
    with TestClient(application(store)) as client:
        sign_in(client)
        with engine.begin() as connection:
            connection.execute(
                update(DashboardSession)
                .where(
                    DashboardSession.token_hash == digest(client.cookies[COOKIE_HTTP])
                )
                .values(expires_at=utcnow() - timedelta(seconds=1))
            )
        assert client.get(f"{ROOT}/auth/session").status_code == 401


def test_project_crud_conflicts_and_key_inventory_scope(store):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        a = create(admin, "/projects", name="A")
        b = create(admin, "/projects", name="B")
        create(
            admin,
            f"/projects/{a['id']}/members",
            email=TENANT,
            password=PASSWORD,
            role="project_admin",
        )
        create(admin, f"/projects/{b['id']}/members", email=TENANT, role="viewer")
        assert admin.post(f"{ROOT}/projects", json={"name": "A"}).status_code == 409
        assert (
            admin.patch(f"{ROOT}/projects/{a['id']}", json={"name": "B"}).status_code
            == 409
        )
        assert admin.get(f"{ROOT}/projects/{a['id']}").json()["name"] == "A"
        envs = []
        for project in [a, b]:
            env = create(admin, f"/projects/{project['id']}/environments", name="dev")
            envs.append(env)
            create(
                admin,
                f"/projects/{project['id']}/environments/{env['id']}/keys",
                name="Integration",
            )
        with TestClient(app) as tenant:
            sign_in(tenant, TENANT)
            inventory = tenant.get(f"{ROOT}/api-keys").json()
            assert [env["id"] for env in inventory["environments"]] == [envs[0]["id"]]
            assert len(inventory["keys"]) == 1
            assert (
                tenant.get(f"{ROOT}/projects/{b['id']}/environments").status_code == 200
            )
            assert (
                tenant.patch(
                    f"{ROOT}/projects/{a['id']}", json={"name": "Renamed"}
                ).status_code
                == 200
            )
            assert tenant.delete(f"{ROOT}/projects/{a['id']}").status_code == 204
            assert tenant.get(f"{ROOT}/projects/{a['id']}").status_code == 404

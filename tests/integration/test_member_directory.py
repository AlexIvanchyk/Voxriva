from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.model_registry import Account, Membership
from tests.support.administration import PASSWORD, ROOT, application, create, sign_in


def grant(project, role="viewer"):
    return {"project_id": project["id"], "role": role}


def test_create_account_and_multiple_project_roles_in_one_transaction(store):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        a, b = (
            create(admin, "/projects", name="Alpha"),
            create(admin, "/projects", name="Beta"),
        )
        response = admin.post(
            f"{ROOT}/members",
            json={
                "email": "multi@example.test",
                "display_name": "Multi Example",
                "password": PASSWORD,
                "projects": [grant(a, "project_admin"), grant(b, "viewer")],
            },
        )
        assert response.status_code == 201, response.text
        member = response.json()
        assert {(item["project_id"], item["role"]) for item in member["projects"]} == {
            (a["id"], "project_admin"),
            (b["id"], "viewer"),
        }
        directory = admin.get(f"{ROOT}/members").json()
        assert (
            len([item for item in directory if item["email"] == "multi@example.test"])
            == 1
        )
        assert "password" not in str(directory)
        with TestClient(app) as user:
            sign_in(user, "multi@example.test")
            assert (
                user.post(
                    f"{ROOT}/projects/{a['id']}/environments", json={"name": "dev"}
                ).status_code
                == 201
            )
            assert (
                user.post(
                    f"{ROOT}/projects/{b['id']}/environments", json={"name": "denied"}
                ).status_code
                == 403
            )


def test_existing_profile_is_retained_and_conflicting_multi_grant_is_atomic(store):
    engine, _ = store
    with TestClient(application(store)) as admin:
        sign_in(admin)
        a, b, c = [
            create(admin, "/projects", name=name) for name in ["Alpha", "Beta", "Gamma"]
        ]
        first = create(
            admin,
            "/members",
            email="existing@example.test",
            display_name="Original Example",
            password=PASSWORD,
            projects=[grant(a)],
        )
        second = create(
            admin,
            "/members",
            email="existing@example.test",
            display_name="Ignored name",
            projects=[grant(b, "operator")],
        )
        assert (
            second["account_id"] == first["account_id"]
            and second["display_name"] == "Original Example"
        )
        conflict = admin.post(
            f"{ROOT}/members",
            json={
                "email": "existing@example.test",
                "projects": [grant(c), grant(a, "project_admin")],
            },
        )
        assert conflict.status_code == 409
        duplicate = admin.post(
            f"{ROOT}/members",
            json={
                "email": "duplicate@example.test",
                "password": PASSWORD,
                "projects": [grant(c), grant(c)],
            },
        )
        assert duplicate.status_code == 422
        existing = next(
            item
            for item in admin.get(f"{ROOT}/members").json()
            if item["email"] == "existing@example.test"
        )
        assert {
            (item["project_id"], item["role"]) for item in existing["projects"]
        } == {(a["id"], "viewer"), (b["id"], "operator")}
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Account)
                    .where(Account.email == "existing@example.test")
                )
                == 1
            )
        with TestClient(admin.app) as user:
            sign_in(user, "existing@example.test")


def test_multi_grant_authorizes_every_target_and_directory_never_leaks_private_access(
    store,
):
    engine, _ = store
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        a, b = (
            create(admin, "/projects", name="Visible"),
            create(admin, "/projects", name="Private"),
        )
        create(
            admin,
            "/members",
            email="manager@example.test",
            password=PASSWORD,
            projects=[grant(a, "project_admin")],
        )
        shared = create(
            admin,
            "/members",
            email="shared@example.test",
            password=PASSWORD,
            projects=[grant(a), grant(b, "project_admin")],
        )
        create(
            admin,
            "/members",
            email="private@example.test",
            password=PASSWORD,
            projects=[grant(b)],
        )
        create(admin, f"/projects/{a['id']}/environments", name="visible-dev")
        create(admin, f"/projects/{b['id']}/environments", name="private-dev")
        with TestClient(app) as manager:
            sign_in(manager, "manager@example.test")
            failed = manager.post(
                f"{ROOT}/members",
                json={
                    "email": "atomic@example.test",
                    "password": PASSWORD,
                    "projects": [grant(a), grant(b)],
                },
            )
            assert failed.status_code == 404
            rows = manager.get(f"{ROOT}/members").json()
            assert not any(item["email"] == "private@example.test" for item in rows)
            visible_shared = next(
                item for item in rows if item["account_id"] == shared["account_id"]
            )
            assert [item["project_id"] for item in visible_shared["projects"]] == [
                a["id"]
            ]
            assert visible_shared["projects"][0]["role"] == "viewer"
            assert b["id"] not in str(rows) and "Private" not in str(rows)
            environments = manager.get(f"{ROOT}/environments").json()
            assert (
                len(environments) == 1
                and environments[0]["project_id"] == a["id"]
                and environments[0]["editable"]
            )
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Account)
                    .where(Account.email == "atomic@example.test")
                )
                == 0
            )
            assert db.scalar(select(func.count()).select_from(Membership)) == 4
        with TestClient(app) as anonymous:
            assert anonymous.get(f"{ROOT}/members").status_code == 401


def test_account_without_project_access_cannot_read_directory_administrator_emails(
    store,
):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        project = create(admin, "/projects", name="Temporary access")
        member = create(
            admin,
            "/members",
            email="removed@example.test",
            password=PASSWORD,
            projects=[grant(project)],
        )
        assert (
            admin.delete(
                f"{ROOT}/projects/{project['id']}/members/{member['account_id']}"
            ).status_code
            == 204
        )
        with TestClient(app) as former_member:
            sign_in(former_member, "removed@example.test")
            assert former_member.get(f"{ROOT}/members").json() == []
            assert former_member.get(f"{ROOT}/environments").json() == []


def test_edit_member_updates_name_roles_and_project_access_atomically(store):
    with TestClient(application(store)) as admin:
        sign_in(admin)
        a, b, c = [
            create(admin, "/projects", name=name)
            for name in ["Edit Alpha", "Edit Beta", "Edit Gamma"]
        ]
        member = create(
            admin,
            "/members",
            email="edit@example.test",
            display_name="Before",
            password=PASSWORD,
            projects=[grant(a), grant(b)],
        )
        body = {
            "expected_display_name": "Before",
            "display_name": "After",
            "expected_projects": [grant(a), grant(b)],
            "projects": [grant(a, "operator"), grant(c, "template_editor")],
        }
        response = admin.patch(f"{ROOT}/members/{member['account_id']}", json=body)
        assert response.status_code == 200, response.text
        updated = next(
            item
            for item in admin.get(f"{ROOT}/members").json()
            if item["account_id"] == member["account_id"]
        )
        assert (
            updated["display_name"] == "After"
            and updated["email"] == "edit@example.test"
        )
        assert {(item["project_id"], item["role"]) for item in updated["projects"]} == {
            (a["id"], "operator"),
            (c["id"], "template_editor"),
        }
        assert (
            admin.patch(f"{ROOT}/members/{member['account_id']}", json=body).status_code
            == 409
        )
        assert (
            admin.patch(
                f"{ROOT}/members/{member['account_id']}",
                json={
                    "expected_display_name": "After",
                    "email": "changed@example.test",
                },
            ).status_code
            == 422
        )
        assert (
            admin.patch(
                f"{ROOT}/members/{member['account_id']}",
                json={
                    "expected_display_name": "After",
                    "expected_projects": body["projects"],
                    "projects": [],
                },
            ).status_code
            == 200
        )


def test_edit_member_preserves_hidden_project_access_and_guards_shared_names_and_self_roles(
    store,
):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        a, b = (
            create(admin, "/projects", name="Managed"),
            create(admin, "/projects", name="Hidden"),
        )
        manager = create(
            admin,
            "/members",
            email="edit-manager@example.test",
            password=PASSWORD,
            display_name="Manager",
            projects=[grant(a, "project_admin")],
        )
        target = create(
            admin,
            "/members",
            email="edit-target@example.test",
            password=PASSWORD,
            display_name="Shared",
            projects=[grant(a), grant(b)],
        )
        with TestClient(app) as user:
            sign_in(user, "edit-manager@example.test")
            path = f"{ROOT}/members/{target['account_id']}"
            assert (
                user.patch(
                    path,
                    json={
                        "expected_display_name": "Shared",
                        "display_name": "Denied",
                        "expected_projects": [grant(a)],
                        "projects": [],
                    },
                ).status_code
                == 403
            )
            assert (
                user.patch(
                    path,
                    json={
                        "expected_display_name": "Shared",
                        "expected_projects": [grant(a)],
                        "projects": [grant(a, "operator")],
                    },
                ).status_code
                == 200
            )
            assert (
                user.patch(
                    path,
                    json={
                        "expected_display_name": "Shared",
                        "expected_projects": [grant(a, "operator")],
                        "projects": [grant(b, "project_admin")],
                    },
                ).status_code
                == 403
            )
            own = f"{ROOT}/members/{manager['account_id']}"
            assert (
                user.patch(
                    own,
                    json={
                        "expected_display_name": "Manager",
                        "display_name": "My name",
                    },
                ).status_code
                == 200
            )
            assert (
                user.patch(
                    own, json={"expected_display_name": "My name", "projects": []}
                ).status_code
                == 403
            )
        updated = next(
            item
            for item in admin.get(f"{ROOT}/members").json()
            if item["account_id"] == target["account_id"]
        )
        assert updated["display_name"] == "Shared"
        assert {(item["project_id"], item["role"]) for item in updated["projects"]} == {
            (a["id"], "operator"),
            (b["id"], "viewer"),
        }

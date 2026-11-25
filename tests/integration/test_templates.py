import asyncio

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.model_registry import AuditEvent, TemplateBranch
from tests.support.administration import PASSWORD, ROOT, application, create, sign_in
from tests.support.templates import content, render


def test_library_lifecycle_preview_conflicts_and_no_preview_writes(store):
    engine, _ = store
    with TestClient(application(store)) as client:
        sign_in(client)
        project = create(client, "/projects", name="Northwind")
        draft = content(scenarios={"Long": {"name": "Long Synthetic Example"}})
        item = create(
            client,
            "/templates",
            name="Welcome",
            key="welcome",
            channel="email",
            project_ids=[project["id"]],
            draft=draft.model_dump(),
        )
        assert (
            client.post(
                f"{ROOT}/templates",
                json={"name": "Duplicate", "key": "welcome", "channel": "email"},
            ).status_code
            == 409
        )
        target = f"{ROOT}/templates/{item['id']}"
        with Session(engine) as db:
            before = db.scalar(select(func.count()).select_from(AuditEvent))
        preview = client.post(f"{target}/preview", json={}).json()
        expected = render(draft, draft.preview_context).model_dump()
        assert preview["rendered"] == expected["rendered"]
        assert preview["errors"] == expected["errors"]
        assert any(
            issue["code"] == "unused_variable" for issue in preview["diagnostics"]
        )
        assert (
            client.post(f"{target}/preview", json={"scenario": "Long"}).json()[
                "rendered"
            ]["subject"]
            == "Hello Long Synthetic Example"
        )
        assert (
            client.post(f"{target}/preview", json={"context": {}}).json()["errors"][0][
                "code"
            ]
            == "required"
        )
        assert (
            client.post(f"{target}/preview", json={"scenario": "Missing"}).status_code
            == 422
        )
        draft.subject = "Unsaved {{ name }}"
        assert (
            client.post(f"{target}/preview", json={"draft": draft.model_dump()})
            .json()["rendered"]["subject"]
            .startswith("Unsaved")
        )
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(AuditEvent)) == before
            assert (
                db.scalar(select(TemplateBranch)).draft["subject"] == "Hello {{ name }}"
            )
        for revision, status in [(1, 200), (1, 409)]:
            assert (
                client.put(
                    f"{target}/draft",
                    json={"draft": draft.model_dump(), "expected_revision": revision},
                ).status_code
                == status
            )
        draft.html = "{% if %}"
        assert (
            client.put(
                f"{target}/draft",
                json={"draft": draft.model_dump(), "expected_revision": 2},
            ).status_code
            == 200
        )
        invalid_preview = client.post(f"{target}/preview", json={}).json()
        assert invalid_preview["rendered"] is None
        assert invalid_preview["errors"][0]["code"] == "syntax"
        assert any(
            issue["field"] == "html" and issue["code"] == "syntax"
            for issue in invalid_preview["diagnostics"]
        )
        assert client.delete(target).status_code == 204
        assert client.get(target).status_code == 404


def test_shared_library_permissions_bindings_and_project_deletion(store):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        a = create(admin, "/projects", name="Storefront")
        b = create(admin, "/projects", name="Private app")
        create(
            admin,
            f"/projects/{a['id']}/members",
            email="editor@example.test",
            password=PASSWORD,
            role="template_editor",
        )
        shared = create(
            admin,
            "/templates",
            name="Shared",
            key="shared",
            channel="email",
            project_ids=[a["id"], b["id"]],
        )
        private = create(
            admin,
            "/templates",
            name="Private",
            key="private",
            channel="push",
            project_ids=[b["id"]],
        )
        unassigned = create(
            admin, "/templates", name="Unassigned", key="unassigned", channel="email"
        )
        assert (
            unassigned["draft"]["subject"] == ""
            and unassigned["draft"]["preview_context"] == {}
            and unassigned["draft"]["scenarios"] == {}
        )
        endpoint = f"{ROOT}/templates/{shared['id']}"
        with TestClient(app) as editor:
            sign_in(editor, "editor@example.test")
            listed = editor.get(f"{ROOT}/templates").json()
            assert [item["id"] for item in listed] == [shared["id"]]
            assert [item["id"] for item in listed[0]["projects"]] == [a["id"]]
            assert not listed[0]["editable"] and not listed[0]["manage_bindings"]
            assert editor.get(f"{ROOT}/templates/{private['id']}").status_code == 404
            assert editor.get(f"{ROOT}/templates/{unassigned['id']}").status_code == 404
            assert (
                editor.get(f"{ROOT}/templates?project_id={b['id']}").status_code == 404
            )
            assert editor.post(f"{endpoint}/preview", json={}).status_code == 200
            assert (
                editor.post(
                    f"{endpoint}/preview", json={"draft": content().model_dump()}
                ).status_code
                == 403
            )
            assert (
                editor.put(
                    f"{endpoint}/projects", json={"project_ids": [a["id"]]}
                ).status_code
                == 403
            )
            own = create(
                editor,
                "/templates",
                name="Own",
                key="own",
                channel="push",
                project_ids=[a["id"]],
            )
            assert own["editable"]
            assert (
                editor.post(
                    f"{ROOT}/templates",
                    json={
                        "name": "Denied",
                        "key": "denied",
                        "channel": "email",
                        "project_ids": [b["id"]],
                    },
                ).status_code
                == 404
            )
            assert (
                editor.post(
                    f"{ROOT}/templates",
                    json={"name": "Orphan", "key": "orphan", "channel": "email"},
                ).status_code
                == 403
            )
            create(
                admin,
                f"/projects/{b['id']}/members",
                email="editor@example.test",
                role="template_editor",
            )
            assert editor.get(endpoint).json()["editable"]
            assert (
                editor.put(
                    f"{endpoint}/draft",
                    json={"draft": content().model_dump(), "expected_revision": 1},
                ).status_code
                == 200
            )
            editor.headers.pop("X-CSRF-Token")
            assert editor.post(f"{endpoint}/preview", json={}).status_code == 403
        assert (
            admin.put(
                f"{endpoint}/projects", json={"project_ids": [a["id"], a["id"]]}
            ).status_code
            == 422
        )
        assert (
            admin.put(f"{endpoint}/projects", json={"project_ids": [a["id"]]}).json()[
                "project_count"
            ]
            == 1
        )
        assert admin.delete(f"{ROOT}/projects/{a['id']}").status_code == 204
        assert admin.get(endpoint).json()["project_count"] == 0
        assert admin.get(endpoint).json()["draft"]["subject"] == "Hello {{ name }}"


def test_preview_rate_concurrency_and_input_bounds(store):
    from collections import deque
    from time import monotonic
    from uuid import UUID

    app = application(store)
    with TestClient(app) as client:
        account = sign_in(client).json()["account"]["id"]
        item = create(
            client, "/templates", name="Preview", key="preview", channel="push"
        )
        endpoint = f"{ROOT}/templates/{item['id']}/preview"
        app.state.preview_limits[UUID(account)] = deque([monotonic()] * 60)
        limited = client.post(endpoint, json={})
        assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
        app.state.preview_limits[UUID(account)] = deque([monotonic() - 61])
        assert client.post(endpoint, json={}).status_code == 200
        app.state.preview_slots = asyncio.Semaphore(0)
        assert client.post(endpoint, json={}).status_code == 429
        oversized = content().model_dump()
        oversized["scenarios"] = {str(i): {} for i in range(21)}
        assert (
            client.put(
                f"{ROOT}/templates/{item['id']}/draft",
                json={"draft": oversized, "expected_revision": 1},
            ).status_code
            == 422
        )

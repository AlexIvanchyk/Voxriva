"""Dashboard credential permissions remain separate from delivery administration."""

import pytest
from fastapi.testclient import TestClient

from tests.support.administration import PASSWORD, ROOT, application, create, sign_in

pytestmark = pytest.mark.integration


def test_editor_management_keys_are_owned_scoped_and_csrf_protected(store):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        editable = create(admin, "/projects", name="Fictional Studio")
        readable = create(admin, "/projects", name="Fictional Library")
        env = create(admin, f"/projects/{editable['id']}/environments", name="test")
        create(
            admin,
            "/members",
            email="key-editor@example.test",
            display_name="Synthetic Editor",
            password=PASSWORD,
            projects=[
                {"project_id": editable["id"], "role": "template_editor"},
                {"project_id": readable["id"], "role": "viewer"},
            ],
        )
        create(
            admin,
            "/members",
            email="key-viewer@example.test",
            display_name="Synthetic Viewer",
            password=PASSWORD,
            projects=[{"project_id": editable["id"], "role": "viewer"}],
        )
        with TestClient(app) as editor:
            sign_in(editor, "key-editor@example.test")
            payload = {
                "name": "My editor",
                "project_ids": [editable["id"]],
                "scopes": ["templates:read", "templates:write"],
                "expires_in_days": 30,
            }
            csrf = editor.headers.pop("X-CSRF-Token")
            assert (
                editor.post(f"{ROOT}/management-credentials", json=payload).status_code
                == 403
            )
            editor.headers["X-CSRF-Token"] = csrf
            assert (
                editor.post(
                    f"{ROOT}/management-credentials",
                    json={**payload, "expires_in_days": 91},
                ).status_code
                == 422
            )
            assert (
                editor.post(
                    f"{ROOT}/management-credentials",
                    json={**payload, "project_ids": [editable["id"], readable["id"]]},
                ).status_code
                == 403
            )
            issued = create(editor, "/management-credentials", **payload)
            listing = editor.get(f"{ROOT}/management-credentials")
            assert [item["id"] for item in listing.json()] == [
                issued["credential"]["id"]
            ]
            assert (
                issued["token"] not in listing.text and "token_hash" not in listing.text
            )
            assert admin.get(f"{ROOT}/management-credentials").json() == []
            assert editor.get(f"{ROOT}/api-keys").json() == {
                "environments": [],
                "keys": [],
            }
            assert (
                editor.post(
                    f"{ROOT}/projects/{editable['id']}/environments/{env['id']}/keys",
                    json={"name": "Forbidden delivery"},
                ).status_code
                == 403
            )
            with TestClient(app) as viewer:
                sign_in(viewer, "key-viewer@example.test")
                assert viewer.get(f"{ROOT}/management-credentials").json() == []
                assert (
                    viewer.delete(
                        f"{ROOT}/management-credentials/{issued['credential']['id']}"
                    ).status_code
                    == 404
                )
                assert (
                    viewer.post(
                        f"{ROOT}/management-credentials", json=payload
                    ).status_code
                    == 403
                )
                read = create(
                    viewer,
                    "/management-credentials",
                    **{**payload, "scopes": ["templates:read"]},
                )
                assert read["credential"]["scopes"] == ["templates:read"]
            assert (
                editor.delete(
                    f"{ROOT}/management-credentials/{issued['credential']['id']}"
                ).status_code
                == 204
            )
            assert (
                editor.get(f"{ROOT}/management-credentials").json()[0]["revoked_at"]
                is not None
            )

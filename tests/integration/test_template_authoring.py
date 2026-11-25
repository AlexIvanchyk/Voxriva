import asyncio
import copy

import pytest
from fastapi.testclient import TestClient

from backend.app.features.templates.authoring import rename_draft
from backend.app.features.templates.rendering import DraftContent, render_message
from tests.support.administration import PASSWORD, ROOT, application, create, sign_in
from tests.support.lifecycle import setup
from tests.support.templates import content


def test_primary_language_can_start_blank_and_translations_need_no_publication(store):
    with TestClient(application(store)) as client:
        sign_in(client)
        template = create(
            client,
            "/templates",
            name="Ukrainian first",
            key="uk-first",
            channel="email",
            locale="UK",
        )
        assert (
            template["locale"]
            == template["primary_locale"]
            == template["fallback_locale"]
            == "uk"
        )
        assert (
            template["languages"] == ["uk"]
            and template["draft"]["preview_context"] == {}
        )
        assert template["draft"]["subject"] == template["draft"]["html"] == ""
        base = f"/templates/{template['id']}"
        english = create(client, base + "/languages", locale="EN")
        assert (
            english["name"] == "main"
            and english["locale"] == "en"
            and english["head"] is None
        )
        current = client.get(ROOT + base).json()
        assert current["locale"] == "uk" and current["languages"] == ["en", "uk"]
        assert (
            client.post(ROOT + base + "/languages", json={"locale": "EN"}).status_code
            == 409
        )
        assert client.get(ROOT + base + "/versions").json() == []


def test_copy_language_is_scoped_and_revision_guarded_and_primary_does_not_change_fallback(
    store,
):
    with TestClient(application(store)) as client:
        sign_in(client)
        _, _, _, template = setup(client)
        base = f"/templates/{template['id']}"
        payload = {
            "locale": "uk",
            "source_branch_id": template["branch_id"],
            "expected_revision": 2,
        }
        assert client.post(ROOT + base + "/languages", json=payload).status_code == 409
        copied = create(
            client, base + "/languages", **{**payload, "expected_revision": 1}
        )
        ukrainian = client.get(ROOT + base, params={"branch_id": copied["id"]}).json()
        assert (
            ukrainian["draft"] == template["draft"] and ukrainian["draft_revision"] == 1
        )
        foreign = create(
            client, "/templates", name="Foreign", key="foreign", channel="email"
        )
        assert (
            client.post(
                ROOT + base + "/languages",
                json={
                    "locale": "de",
                    "source_branch_id": foreign["branch_id"],
                    "expected_revision": 1,
                },
            ).status_code
            == 404
        )
        assert (
            client.put(
                ROOT + base + "/primary-language",
                json={"locale": "uk", "expected_locale": "en"},
            ).status_code
            == 200
        )
        current = client.get(ROOT + base).json()
        assert (
            current["locale"] == current["primary_locale"] == "uk"
            and current["fallback_locale"] == "en"
        )
        assert (
            client.put(
                ROOT + base + "/primary-language",
                json={"locale": "en", "expected_locale": "en"},
            ).status_code
            == 409
        )
        assert (
            client.put(
                ROOT + base + "/primary-language",
                json={"locale": "fr", "expected_locale": "uk"},
            ).status_code
            == 422
        )


def test_editor_actions_keep_existing_access_boundaries(store):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        project, _, _, template = setup(admin)
        create(
            admin,
            f"/projects/{project['id']}/members",
            email="authoring-viewer@example.test",
            password=PASSWORD,
            role="viewer",
        )
        with TestClient(app) as viewer:
            sign_in(viewer, "authoring-viewer@example.test", PASSWORD)
            base = f"{ROOT}/templates/{template['id']}"
            assert (
                viewer.post(base + "/languages", json={"locale": "uk"}).status_code
                == 403
            )
            assert (
                viewer.put(
                    base + "/primary-language",
                    json={"locale": "en", "expected_locale": "en"},
                ).status_code
                == 403
            )
            assert (
                viewer.post(
                    base + "/variables/rename",
                    json={
                        "old_name": "name",
                        "new_name": "person",
                        "draft": template["draft"],
                    },
                ).status_code
                == 403
            )


def test_rename_preview_updates_root_references_saved_data_and_schema_without_persisting(
    store,
):
    with TestClient(application(store)) as client:
        sign_in(client)
        template = create(
            client,
            "/templates",
            name="Rename",
            key="rename",
            channel="email",
            draft=content().model_dump(),
        )
        draft = copy.deepcopy(template["draft"])
        draft["runtime_defaults"] = {"name": "Default"}
        draft["scenarios"] = {"sample": {"name": "Sample"}}
        draft["html"] = "name: {{ name }} {{ 'name' }}"
        base = f"{ROOT}/templates/{template['id']}"
        response = client.post(
            base + "/variables/rename",
            json={"draft": draft, "old_name": "name", "new_name": "first_name"},
        )
        assert response.status_code == 200, response.text
        changed = response.json()["draft"]
        assert changed["html"] == "name: {{ first_name }} {{ 'name' }}"
        assert changed["variable_schema"]["required"] == ["first_name"]
        assert changed["runtime_defaults"] == {"first_name": "Default"}
        assert changed["scenarios"]["sample"] == {"first_name": "Sample"}
        assert "first_name" in changed["preview_context"]
        assert client.get(base).json()["draft"] == template["draft"]
        saved = client.put(
            base + "/draft",
            json={
                "draft": changed,
                "expected_revision": 1,
                "branch_id": template["branch_id"],
            },
        )
        assert saved.status_code == 200 and saved.json()["draft_revision"] == 2


@pytest.mark.parametrize(
    "source,old,new,expected",
    [
        (
            "{{ name }}\r\n{{ person.name }} {{ 'name' }}",
            "name",
            "first_name",
            "{{ first_name }}\r\n{{ person.name }} {{ 'name' }}",
        ),
        (
            "{{ upper }} {% filter upper %}x{% endfilter %}",
            "upper",
            "heading",
            "{{ heading }} {% filter upper %}x{% endfilter %}",
        ),
        (
            "{{ defined }} {{ name is not defined }}",
            "defined",
            "flag",
            "{{ flag }} {{ name is not defined }}",
        ),
        (
            " A \n {%- if name -%}{{ name }}{% endif %}\n",
            "name",
            "person",
            " A \n {%- if person -%}{{ person }}{% endif %}\n",
        ),
    ],
)
def test_rename_retains_literals_filters_attributes_tests_and_whitespace(
    source, old, new, expected
):
    draft = DraftContent(
        subject=source,
        variable_schema={"type": "object", "properties": {old: {"type": "string"}}},
    ).model_dump()
    assert rename_draft("email", draft, old, new)["draft"]["subject"] == expected


@pytest.mark.parametrize(
    "source",
    [
        "{% for name in names %}{{ name }}{% endfor %}",
        "{% set name = 'local' %}{{ name }}",
        "{% macro name() %}x{% endmacro %}{{ name }}",
    ],
)
def test_rename_refuses_ambiguous_local_bindings(source):
    draft = DraftContent(
        subject=source,
        variable_schema={"type": "object", "properties": {"name": {"type": "string"}}},
    ).model_dump()
    with pytest.raises(ValueError, match="local template binding"):
        rename_draft("email", draft, "name", "person")


def test_authoring_diagnostics_locate_errors_and_reject_unknown_formats_without_changing_runtime():
    draft = content()
    draft.variable_schema["properties"]["name"]["format"] = "typo-email"
    runtime = asyncio.run(render_message("email", draft, draft.preview_context))
    assert not runtime.errors
    editor = asyncio.run(
        render_message("email", draft, draft.preview_context, authoring=True)
    )
    assert (
        editor.errors[0].code == "unknown_format"
        and editor.diagnostics[0]["path"][-1] == "format"
    )
    draft.variable_schema["properties"]["name"].pop("format")
    draft.html = "<h1>Hello</h1>\n{% if %}"
    editor = asyncio.run(
        render_message("email", draft, draft.preview_context, authoring=True)
    )
    assert any(
        note["field"] == "html" and note["line"] == 2 and note["code"] == "syntax"
        for note in editor.diagnostics
    )
    draft.html = "{{ undeclared }}"
    editor = asyncio.run(
        render_message("email", draft, draft.preview_context, authoring=True)
    )
    assert any(
        note["name"] == "undeclared" and note["code"] == "undeclared_variable"
        for note in editor.diagnostics
    )
    assert any(
        note["name"] == "age" and note["code"] == "unused_variable"
        for note in editor.diagnostics
    )


def test_publication_checks_do_not_create_versions_for_invalid_saved_format(store):
    with TestClient(application(store)) as client:
        sign_in(client)
        draft = content().model_dump()
        draft["variable_schema"]["properties"]["name"]["format"] = "typo-email"
        template = create(
            client,
            "/templates",
            name="Bad format",
            key="bad-format",
            channel="email",
            draft=draft,
        )
        response = client.post(
            f"{ROOT}/templates/{template['id']}/publish",
            json={"branch_id": template["branch_id"], "expected_revision": 1},
        )
        assert response.status_code == 422
        assert client.get(f"{ROOT}/templates/{template['id']}/versions").json() == []


def test_large_utf8_language_content_fits_the_same_byte_limits_for_preview_and_rename():
    from backend.app.features.templates.authoring import rename_bounded

    draft = DraftContent(
        subject="Привіт {{ name }}",
        html="я" * 25000 + " {{ name }}",
        text="я" * 15000,
        variable_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        preview_context={"name": "Оля"},
    )
    report = asyncio.run(
        render_message("email", draft, draft.preview_context, authoring=True)
    )
    assert not report.errors and report.rendered["subject"] == "Привіт Оля"
    renamed = asyncio.run(rename_bounded("email", draft.model_dump(), "name", "person"))
    assert renamed["draft"]["subject"] == "Привіт {{ person }}"
    assert renamed["draft"]["text"] == draft.text

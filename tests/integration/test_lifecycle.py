from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.infrastructure.model_registry import (
    AuditEvent,
    DeploymentEvent,
    TemplateBranch,
    TemplateDeployment,
    TemplateVersion,
)
from tests.support.administration import PASSWORD, ROOT, application, create, sign_in
from tests.support.lifecycle import draft, mutate, publish, setup, target


def test_publication_is_immutable_and_does_not_deploy(store):
    engine, _ = store
    with TestClient(application(store)) as client:
        sign_in(client)
        project, dev, _, template = setup(client)
        first = publish(client, template)
        base = f"{ROOT}/templates/{template['id']}"
        assert first["number"] == 1 and first["parent_version_id"] is None
        assert not any(
            row["effective_version"]
            for row in client.get(f"{base}/deployments").json()["rows"]
        )
        assert (
            client.get(
                f"{ROOT}/projects/{project['id']}/environments/{dev['id']}/templates/{template['id']}/resolve"
            ).status_code
            == 404
        )
        updated = draft("Updated {{ name }}")
        saved = client.put(
            f"{base}/draft",
            json={
                "draft": updated.model_dump(),
                "expected_revision": 1,
                "branch_id": template["branch_id"],
            },
        )
        assert saved.status_code == 200
        assert (
            client.get(f"{base}/versions/{first['id']}").json()["content"]["subject"]
            == "Hello {{ name }}"
        )
        second = publish(client, template, revision=2)
        assert second["number"] == 2 and second["parent_version_id"] == first["id"]
        assert (
            client.post(
                f"{base}/publish",
                json={"branch_id": template["branch_id"], "expected_revision": 2},
            ).status_code
            == 409
        )
        assert client.delete(base).status_code == 409
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(TemplateDeployment)) == 0
            with pytest.raises(IntegrityError):
                db.execute(
                    update(TemplateVersion)
                    .where(TemplateVersion.id == UUID(first["id"]))
                    .values(message="tampered")
                )
                db.commit()
            db.rollback()
            with pytest.raises(IntegrityError):
                db.delete(db.get(TemplateVersion, UUID(second["id"])))
                db.commit()
            db.rollback()


def test_fork_drafts_lineage_diff_and_published_preview_are_scoped(store):
    engine, _ = store
    with TestClient(application(store)) as client:
        sign_in(client)
        _, _, _, template = setup(client)
        first = publish(client, template)
        base = f"{ROOT}/templates/{template['id']}"
        branch = create(
            client,
            f"/templates/{template['id']}/branches",
            name="candidate",
            source_version_id=first["id"],
        )
        initial = client.get(f"{base}?branch_id={branch['id']}").json()
        assert initial["draft"] == first["content"]
        changed = draft("Candidate {{ name }}")
        assert (
            client.put(
                f"{base}/draft",
                json={
                    "branch_id": branch["id"],
                    "expected_revision": 1,
                    "draft": changed.model_dump(),
                },
            ).status_code
            == 200
        )
        assert client.get(base).json()["draft"]["subject"] == "Hello {{ name }}"
        candidate = publish(client, template, branch["id"], 2)
        assert (
            candidate["number"] == 1 and candidate["parent_version_id"] == first["id"]
        )
        comparison = client.get(
            f"{base}/versions/diff?before={first['id']}&after={candidate['id']}"
        ).json()
        assert (
            comparison["before"]["content"]["subject"]
            != comparison["after"]["content"]["subject"]
        )
        assert comparison["issues"] == []
        with Session(engine) as db:
            before = db.scalar(select(func.count()).select_from(AuditEvent))
        preview = client.post(
            f"{base}/versions/{first['id']}/preview",
            json={"context": {"name": "Frozen Example"}},
        )
        assert preview.json()["rendered"]["subject"] == "Hello Frozen Example"
        assert (
            client.post(
                f"{base}/versions/{first['id']}/preview",
                json={"draft": changed.model_dump()},
            ).status_code
            == 422
        )
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(AuditEvent)) == before
        foreign = create(
            client, "/templates", name="Other", key="other", channel="push"
        )
        assert (
            client.get(
                f"{ROOT}/templates/{foreign['id']}/versions/{first['id']}"
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"{ROOT}/templates/{foreign['id']}/branches",
                json={"name": "stolen", "source_version_id": first["id"]},
            ).status_code
            == 404
        )
        assert client.get(f"{base}?branch_id={uuid4()}").status_code == 404


def test_resolution_precedence_promotion_rollback_and_stale_generations(store):
    engine, _ = store
    with TestClient(application(store)) as client:
        sign_in(client)
        project, dev, prod, template = setup(client)
        v1 = publish(client, template)
        base = f"{ROOT}/templates/{template['id']}"
        client.put(
            f"{base}/draft",
            json={
                "draft": draft("Version two {{ name }}").model_dump(),
                "expected_revision": 1,
            },
        )
        v2 = publish(client, template, revision=2)
        assert (
            mutate(
                client,
                template,
                scope="global",
                locale="en",
                expected_generation=0,
                version_id=v1["id"],
            ).status_code
            == 200
        )
        resolve = f"{ROOT}/projects/{project['id']}/environments/{prod['id']}/templates/{template['id']}/resolve"
        assert client.get(resolve).json()["scope"] == "global"
        assert (
            mutate(client, template, **target(project), version_id=v2["id"]).status_code
            == 200
        )
        assert client.get(resolve).json()["scope"] == "project"
        assert client.get(resolve).json()["version"]["id"] == v2["id"]
        assert (
            mutate(
                client, template, **target(project, prod), version_id=v1["id"]
            ).status_code
            == 200
        )
        assert (
            mutate(
                client, template, **target(project, dev), version_id=v2["id"]
            ).status_code
            == 200
        )
        assert client.get(resolve).json()["scope"] == "environment"
        promote = {
            "source": {
                key: value
                for key, value in target(project, dev).items()
                if key != "expected_generation"
            },
            "target": target(project, prod, 1),
            "expected_source_generation": 1,
        }
        assert mutate(client, template, action="promote", **promote).status_code == 200
        assert client.get(resolve).json()["version"]["id"] == v2["id"]
        assert (
            mutate(
                client,
                template,
                action="rollback",
                **target(project, prod, 2),
                version_id=v1["id"],
            ).status_code
            == 200
        )
        assert client.get(resolve).json()["version"]["id"] == v1["id"]
        assert (
            mutate(
                client, template, **target(project, prod, 1), version_id=v2["id"]
            ).status_code
            == 409
        )
        assert (
            mutate(
                client, template, action="clear", **target(project, prod, 3)
            ).status_code
            == 200
        )
        assert (
            client.get(resolve).json()["version"]["id"] == v2["id"]
            and client.get(resolve).json()["scope"] == "project"
        )
        assert (
            mutate(
                client, template, **target(project, prod, 0), version_id=v1["id"]
            ).status_code
            == 409
        )
        assert (
            mutate(
                client,
                template,
                **target(project, prod, 4),
                version_id=v1["id"],
                expected_effective_version_id=v1["id"],
            ).status_code
            == 409
        )
        promote["expected_source_generation"] = 99
        promote["target"] = target(project, prod, 4)
        assert mutate(client, template, action="promote", **promote).status_code == 409
        assert (
            client.put(f"{base}/projects", json={"project_ids": []}).status_code == 409
        )
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(DeploymentEvent)) == 7
            event = db.scalar(select(DeploymentEvent))
            with pytest.raises(IntegrityError):
                db.execute(
                    update(DeploymentEvent)
                    .where(DeploymentEvent.id == event.id)
                    .values(action="tampered")
                )
                db.commit()
            db.rollback()


def test_locale_fallback_is_explicit_and_locale_first(store):
    with TestClient(application(store)) as client:
        sign_in(client)
        project, dev, _, template = setup(client)
        en = publish(client, template)
        base = f"{ROOT}/templates/{template['id']}"
        uk_branch = create(
            client,
            f"/templates/{template['id']}/branches",
            name="translation",
            source_version_id=en["id"],
            locale="UK",
        )
        uk = publish(client, template, uk_branch["id"])
        assert uk["locale"] == "uk"
        assert (
            mutate(client, template, **target(project), version_id=en["id"]).status_code
            == 200
        )
        assert (
            mutate(
                client,
                template,
                scope="global",
                locale="uk",
                expected_generation=0,
                version_id=uk["id"],
            ).status_code
            == 200
        )
        resolve = f"{ROOT}/projects/{project['id']}/environments/{dev['id']}/templates/{template['id']}/resolve"
        localized = client.get(f"{resolve}?locale=uk").json()
        assert (
            localized["version"]["id"] == uk["id"]
            and localized["scope"] == "global"
            and not localized["fallback_used"]
        )
        missing = client.get(f"{resolve}?locale=uk-UA").json()
        assert (
            missing["version"]["id"] == en["id"] and missing["fallback_used"]
        )  # No implicit uk-UA → uk fallback.
        assert (
            mutate(
                client,
                template,
                **target(project, dev, locale="uk"),
                version_id=en["id"],
            ).status_code
            == 422
        )
        assert (
            client.put(
                f"{base}/fallback", json={"locale": "uk", "expected_locale": "en"}
            ).status_code
            == 409
        )
        assert (
            client.put(
                f"{base}/fallback",
                json={
                    "locale": "uk",
                    "expected_locale": "en",
                    "acknowledge_active_change": True,
                },
            ).status_code
            == 200
        )
        assert client.get(f"{resolve}?locale=fr").json()["version"]["id"] == uk["id"]
        assert (
            client.put(
                f"{base}/fallback",
                json={
                    "locale": "en",
                    "expected_locale": "en",
                    "acknowledge_active_change": True,
                },
            ).status_code
            == 409
        )


def test_breaking_schema_requires_explicit_acknowledgement_on_deploy_and_rollback(
    store,
):
    with TestClient(application(store)) as client:
        sign_in(client)
        project, dev, _, template = setup(client)
        first = publish(client, template)
        assert (
            mutate(
                client, template, **target(project, dev), version_id=first["id"]
            ).status_code
            == 200
        )
        content = draft()
        content.variable_schema["properties"]["code"] = {"type": "string"}
        content.variable_schema["required"].append("code")
        content.preview_context["code"] = "SYNTHETIC"
        base = f"{ROOT}/templates/{template['id']}"
        client.put(
            f"{base}/draft",
            json={"expected_revision": 1, "draft": content.model_dump()},
        )
        second = publish(client, template, revision=2)
        rejected = mutate(
            client, template, **target(project, dev, 1), version_id=second["id"]
        )
        assert (
            rejected.status_code == 409
            and rejected.json()["detail"]["issues"][0]["code"] == "required_added"
        )
        assert (
            mutate(
                client,
                template,
                **target(project, dev, 1),
                version_id=second["id"],
                allow_breaking=True,
            ).status_code
            == 200
        )
        assert (
            mutate(
                client,
                template,
                action="rollback",
                **target(project, dev, 2),
                version_id=first["id"],
            ).status_code
            == 409
        )
        assert (
            mutate(
                client,
                template,
                action="rollback",
                **target(project, dev, 2),
                version_id=first["id"],
                allow_breaking=True,
            ).status_code
            == 200
        )


def test_role_boundaries_and_scope_lookup_cannot_cross_projects(store):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        project, dev, _, template = setup(admin)
        private = create(admin, "/projects", name="Private")
        other_env = create(
            admin, f"/projects/{private['id']}/environments", name="secret"
        )
        create(
            admin,
            f"/projects/{project['id']}/members",
            email="manager@example.test",
            password=PASSWORD,
            role="project_admin",
        )
        create(
            admin,
            f"/projects/{project['id']}/members",
            email="editor@example.test",
            password=PASSWORD,
            role="template_editor",
        )
        published = publish(admin, template)
        with TestClient(app) as manager:
            sign_in(manager, "manager@example.test")
            assert (
                mutate(
                    manager,
                    template,
                    **target(project, dev),
                    version_id=published["id"],
                ).status_code
                == 200
            )
            assert (
                mutate(
                    manager,
                    template,
                    **target(private, other_env),
                    version_id=published["id"],
                ).status_code
                == 404
            )
            assert (
                mutate(
                    manager,
                    template,
                    **target(project, other_env),
                    version_id=published["id"],
                ).status_code
                == 404
            )
            assert (
                mutate(
                    manager,
                    template,
                    scope="global",
                    locale="en",
                    expected_generation=0,
                    version_id=published["id"],
                ).status_code
                == 403
            )
            rows = manager.get(f"{ROOT}/templates/{template['id']}/deployments").json()[
                "rows"
            ]
            assert not any(row["project_id"] == private["id"] for row in rows)
        with TestClient(app) as editor:
            sign_in(editor, "editor@example.test")
            assert (
                mutate(
                    editor,
                    template,
                    **target(project, dev, 1),
                    version_id=published["id"],
                ).status_code
                == 403
            )
            assert (
                editor.get(
                    f"{ROOT}/projects/{project['id']}/environments/{dev['id']}/templates/{template['id']}/resolve"
                ).status_code
                == 200
            )
            assert (
                editor.get(
                    f"{ROOT}/projects/{private['id']}/environments/{other_env['id']}/templates/{template['id']}/resolve"
                ).status_code
                == 404
            )


def test_invalid_draft_publication_has_no_version_or_deployment_side_effects(store):
    engine, _ = store
    with TestClient(application(store)) as client:
        sign_in(client)
        template = create(
            client, "/templates", name="Blank", key="blank", channel="email"
        )
        base = f"{ROOT}/templates/{template['id']}"
        assert (
            client.post(
                f"{base}/publish",
                json={"branch_id": template["branch_id"], "expected_revision": 1},
            ).status_code
            == 422
        )
        content = draft()
        content.preview_context = {}
        client.put(
            f"{base}/draft",
            json={"expected_revision": 1, "draft": content.model_dump()},
        )
        result = client.post(
            f"{base}/publish",
            json={"branch_id": template["branch_id"], "expected_revision": 2},
        )
        assert (
            result.status_code == 422
            and result.json()["detail"]["code"] == "invalid_publication"
        )
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(TemplateVersion)) == 0
            assert db.scalar(select(func.count()).select_from(TemplateDeployment)) == 0
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "template.publish")
                )
                == 0
            )
            assert db.scalar(select(func.count()).select_from(TemplateBranch)) == 1


def test_invalid_runtime_defaults_cannot_hide_behind_valid_preview_values(store):
    with TestClient(application(store)) as client:
        sign_in(client)
        _, _, _, template = setup(client)
        content = draft()
        content.runtime_defaults = {"name": 42}
        base = f"{ROOT}/templates/{template['id']}"
        assert (
            client.put(
                f"{base}/draft",
                json={"expected_revision": 1, "draft": content.model_dump()},
            ).status_code
            == 200
        )
        response = client.post(
            f"{base}/publish",
            json={"branch_id": template["branch_id"], "expected_revision": 2},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["issues"][0]["code"] == "type"


def test_workspace_deployment_inventory_matches_scoped_resolution_and_hides_private_projects(
    store,
):
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        project, dev, prod, template = setup(admin)
        private = create(admin, "/projects", name="Private inventory")
        secret = create(admin, f"/projects/{private['id']}/environments", name="secret")
        shared = admin.put(
            f"{ROOT}/templates/{template['id']}/projects",
            json={"project_ids": [project["id"], private["id"]]},
        )
        assert shared.status_code == 200
        published = publish(admin, template)
        assert (
            mutate(
                admin,
                template,
                scope="global",
                locale="en",
                expected_generation=0,
                version_id=published["id"],
            ).status_code
            == 200
        )
        assert (
            mutate(
                admin, template, **target(private, secret), version_id=published["id"]
            ).status_code
            == 200
        )
        fork = create(
            admin,
            f"/templates/{template['id']}/branches",
            name="translation",
            locale="uk",
            source_version_id=published["id"],
        )
        translated = publish(admin, template, fork["id"])
        assert (
            mutate(
                admin,
                template,
                **target(project, dev, locale="uk"),
                version_id=translated["id"],
            ).status_code
            == 200
        )
        push = create(
            admin,
            "/templates",
            name="Push inventory",
            key="push-inventory",
            channel="push",
            project_ids=[project["id"]],
        )
        hidden = create(
            admin,
            "/templates",
            name="Private template",
            key="private-inventory",
            channel="push",
            project_ids=[private["id"]],
        )
        create(
            admin,
            f"/projects/{project['id']}/members",
            email="inventory@example.test",
            password=PASSWORD,
            role="viewer",
        )
        with TestClient(app) as member:
            sign_in(member, "inventory@example.test")
            response = member.get(f"{ROOT}/deployments")
            assert response.status_code == 200, response.text
            rows = response.json()
            assert {row["template_id"] for row in rows} == {template["id"], push["id"]}
            assert not any(
                row["project_id"] == private["id"]
                or row["environment_id"] == secret["id"]
                or row["template_id"] == hidden["id"]
                for row in rows
            )
            assert {row["channel"] for row in rows} == {"email", "push"}
            for locale in ["en", "uk"]:
                matrix = member.get(
                    f"{ROOT}/templates/{template['id']}/deployments?locale={locale}"
                ).json()["rows"]
                actual = [
                    row
                    for row in rows
                    if row["template_id"] == template["id"] and row["locale"] == locale
                ]
                assert len(actual) == len(matrix)
                for expected in matrix:
                    row = next(
                        row
                        for row in actual
                        if (row["scope"], row["project_id"], row["environment_id"])
                        == (
                            expected["scope"],
                            expected["project_id"],
                            expected["environment_id"],
                        )
                    )
                    for field in [
                        "version",
                        "effective_version",
                        "effective_scope",
                        "fallback_used",
                    ]:
                        assert row[field] == expected[field]
            uk_prod = next(
                row
                for row in rows
                if row["environment_id"] == prod["id"] and row["locale"] == "uk"
            )
            assert (
                uk_prod["effective_version"]["id"] == published["id"]
                and uk_prod["fallback_used"]
            )
        with TestClient(app) as anonymous:
            assert anonymous.get(f"{ROOT}/deployments").status_code == 401

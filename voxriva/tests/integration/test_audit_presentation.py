from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.features.identity.models import Account, AuditEvent
from tests.support.administration import PASSWORD, ROOT, application, create, sign_in


def test_audit_references_respect_current_access_and_keep_deleted_ids(store):
    engine, _ = store
    app = application(store)
    with TestClient(app) as admin:
        sign_in(admin)
        visible = create(admin, "/projects", name="Visible workspace")
        hidden = create(admin, "/projects", name="Hidden workspace")
        for project, email in [
            (visible, "manager@example.test"),
            (hidden, "hidden@example.test"),
        ]:
            create(
                admin,
                f"/projects/{project['id']}/members",
                email=email,
                password=PASSWORD,
                display_name=email.split("@")[0],
                role="project_admin",
            )
        template = create(
            admin,
            "/templates",
            name="Visible template",
            key="visible",
            channel="email",
            project_ids=[visible["id"]],
        )
        secret = create(
            admin,
            "/templates",
            name="Hidden template name",
            key="hidden",
            channel="email",
            project_ids=[hidden["id"]],
        )
        with Session(engine) as db:
            actor = db.scalar(
                select(Account).where(Account.email == "hidden@example.test")
            )
            deleted = uuid4()
            for target in [UUID(template["id"]), UUID(secret["id"]), deleted]:
                db.add(
                    AuditEvent(
                        actor_id=actor.id,
                        project_id=UUID(visible["id"]),
                        action="template.deploy",
                        target_id=target,
                        legacy_scope={
                            "secret": "DO-NOT-RETURN",
                            "organization_name": "PRIVATE",
                        },
                    )
                )
            actor_id = str(actor.id)
            db.commit()
        with TestClient(app) as manager:
            sign_in(manager, "manager@example.test")
            result = manager.get(f"{ROOT}/operations/audit").json()
            rows = [
                row for row in result["items"] if row["action"] == "template.deploy"
            ]
            assert len(rows) == 3
            assert all(row["project_name"] == "Visible workspace" for row in rows)
            assert all(
                row["actor"]
                == {"label": "Deleted or unavailable account", "href": None}
                for row in rows
            )
            assert all(row["actor_id"] == actor_id for row in rows)
            by_id = {row["target_id"]: row for row in rows}
            assert by_id[template["id"]]["target"] == {
                "label": "Visible template",
                "href": f"/templates/{template['id']}",
            }
            for identifier in [secret["id"], str(deleted)]:
                assert by_id[identifier]["target"] == {
                    "label": "Deleted or unavailable template",
                    "href": None,
                }
            assert by_id[str(deleted)]["action_label"] == "Template version deployed"
            assert "Hidden template name" not in str(result)
            assert "DO-NOT-RETURN" not in str(result) and "PRIVATE" not in str(result)
            assert (
                manager.get(
                    f"{ROOT}/operations/audit?project_id={hidden['id']}"
                ).status_code
                == 404
            )
        admin_rows = admin.get(f"{ROOT}/operations/audit").json()["items"]
        event = next(
            row
            for row in admin_rows
            if row["target_id"] == secret["id"] and row["action"] == "template.deploy"
        )
        assert event["target"]["label"] == "Hidden template name"
        assert event["actor"]["label"] == "hidden"
        create(
            admin,
            f"/projects/{visible['id']}/members",
            email="viewer@example.test",
            password=PASSWORD,
            role="viewer",
        )
        with TestClient(app) as viewer:
            sign_in(viewer, "viewer@example.test")
            assert viewer.get(f"{ROOT}/operations/audit").json() == {
                "total": 0,
                "items": [],
            }

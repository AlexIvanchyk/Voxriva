from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.model_registry import Notification, NotificationOutbox
from tests.support.administration import ROOT, application
from tests.support.lifecycle import mutate, publish, target
from tests.support.notifications import body, prepare


def test_phone_publication_preview_generation_and_runtime_contract_parity(store):
    app = application(store)
    with TestClient(app) as client:
        project, env, _, template, _, _, headers = prepare(client, app)
        base = f"{ROOT}/templates/{template['id']}"
        draft = template["draft"]
        draft["variable_schema"]["properties"]["name"] = {
            "type": "string",
            "format": "phone",
            "x-voxriva-phone-version": 1,
        }
        draft["preview_context"] = {"name": "02083661177"}
        saved = client.put(
            base + "/draft", json={"draft": draft, "expected_revision": 1}
        )
        assert saved.status_code == 200, saved.text
        # Invalid fixtures can be saved without losing work, but cannot be published.
        rejected = client.post(
            base + "/publish",
            json={"branch_id": template["branch_id"], "expected_revision": 2},
        )
        assert rejected.status_code == 422
        assert len(client.get(base + "/versions").json()) == 1
        preview = client.post(base + "/preview", json={"draft": draft}).json()
        assert preview["errors"][0]["path"] == ["context", "name"]
        generated = client.post(
            base + "/preview", json={"draft": draft, "generate_example": True}
        ).json()
        assert generated["errors"] == []
        assert generated["rendered"]["context"] == {"name": "+12025550123"}
        # Generating does not mutate any saved draft or fixtures.
        assert client.get(base).json()["draft"] == draft
        draft["preview_context"] = {"name": "+442083661177"}
        saved = client.put(
            base + "/draft", json={"draft": draft, "expected_revision": 2}
        )
        assert saved.status_code == 200
        version = publish(client, template, revision=3)
        assert (
            mutate(
                client,
                template,
                **target(project, env, generation=1),
                version_id=version["id"],
                allow_breaking=True,
            ).status_code
            == 200
        )
        auth = {"Authorization": headers["Authorization"]}
        with Session(store[0]) as db:
            before = [
                db.scalar(select(func.count()).select_from(model))
                for model in (Notification, NotificationOutbox)
            ]
        for number, valid in [("02083661177", False), ("+442083661177", True)]:
            payload = body(template, context={"name": number})
            checked = client.post(
                f"{ROOT}/notifications/validate", json=payload, headers=auth
            )
            assert checked.status_code == (200 if valid else 422), checked.text
            if not valid:
                accepted = client.post(
                    f"{ROOT}/notifications", json=payload, headers=headers
                )
                assert accepted.status_code == 422
                assert "E.164" in checked.text and "E.164" in accepted.text
        with Session(store[0]) as db:
            after = [
                db.scalar(select(func.count()).select_from(model))
                for model in (Notification, NotificationOutbox)
            ]
        assert before == after

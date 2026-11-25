import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.features.notifications.delivery import consume, publish_once
from backend.app.features.providers.adapters.smtp import SMTPProvider
from backend.app.features.templates.images import ImageContent, image_schema
from backend.app.infrastructure.model_registry import Notification, NotificationOutbox
from backend.app.shared.provider_contract import ProviderResult
from tests.support.administration import ROOT, application, create, sign_in
from tests.support.images import image_value
from tests.support.lifecycle import mutate, publish, target
from tests.support.notifications import body, count, prepare


def test_image_upload_permissions_content_validation_and_no_preview_side_effects(store):
    engine, _ = store
    app = application(store)
    with TestClient(app) as client:
        project, _, _, template, _, _, headers = prepare(client, app)
        path = f"{ROOT}/templates/{template['id']}/images/validate"
        assert client.post(path, json=image_value()).json() == image_value()
        for invalid in (
            {**image_value(), "media_type": "text/html"},
            {**image_value(), "content_base64": "AAAA"},
            image_value(size=(4097, 1)),
        ):
            result = client.post(path, json=invalid)
            assert result.status_code == 422
            assert "content_base64" not in str(result.json().get("input", ""))
        create(
            client,
            f"/projects/{project['id']}/members",
            email="image-viewer@example.test",
            password="Fictional image password",
            role="viewer",
        )
        with TestClient(app) as viewer:
            sign_in(viewer, "image-viewer@example.test", "Fictional image password")
            assert viewer.post(path, json=image_value()).status_code == 403
        with TestClient(app) as anonymous:
            assert anonymous.post(path, json=image_value()).status_code == 401
            assert (
                anonymous.post(
                    path,
                    json=image_value(),
                    headers={"Authorization": headers["Authorization"]},
                ).status_code
                == 401
            )
        draft = template["draft"]
        draft["images"] = {"logo": image_value()}
        draft["html"] = '<img src="voxriva-image:logo">'
        preview = client.post(
            f"{ROOT}/templates/{template['id']}/preview", json={"draft": draft}
        )
        assert preview.status_code == 200 and not preview.json()["errors"]
        assert (
            preview.json()["rendered"]["images"][0]["content_base64"]
            == image_value()["content_base64"]
        )
        assert count(engine, Notification) == count(engine, NotificationOutbox) == 0


def test_images_pin_immutable_versions_queued_bytes_idempotency_and_terminal_cleanup(
    store, monkeypatch
):
    engine, factory = store
    app = application(store)
    sent = []

    def send(self, message):
        sent.append(message)
        return ProviderResult(
            status="accepted", message="Synthetic", message_id="synthetic-image"
        )

    monkeypatch.setattr(SMTPProvider, "send", send)
    with TestClient(app) as client:
        project, dev, _, template, _, _, headers = prepare(client, app)
        base = f"{ROOT}/templates/{template['id']}"
        draft = template["draft"]
        draft["images"] = {"logo": image_value("red")}
        draft["html"] = '<img src="voxriva-image:logo"><img src="{{ banner }}">'
        draft["variable_schema"]["properties"]["banner"] = image_schema()
        draft["variable_schema"]["required"].append("banner")
        draft["preview_context"]["banner"] = image_value("green")
        draft["runtime_defaults"] = {"banner": image_value("blue")}
        assert (
            client.put(
                base + "/draft", json={"draft": draft, "expected_revision": 1}
            ).status_code
            == 200
        )
        version = publish(client, template, revision=2)
        assert (
            mutate(
                client,
                template,
                **target(project, dev, generation=1),
                version_id=version["id"],
            ).status_code
            == 200
        )
        invalid = body(
            template,
            context={
                "name": "Fictional",
                "banner": {**image_value(), "content_base64": "AAAA"},
            },
        )
        assert (
            client.post(
                f"{ROOT}/notifications", json=invalid, headers=headers
            ).status_code
            == 422
        )
        assert count(engine, Notification) == count(engine, NotificationOutbox) == 0
        payload = body(
            template, context={"name": "Fictional", "banner": image_value("yellow")}
        )
        response = client.post(f"{ROOT}/notifications", json=payload, headers=headers)
        assert response.status_code == 202, response.text
        identifier = UUID(response.json()["id"])
        assert client.post(
            f"{ROOT}/notifications", json=payload, headers=headers
        ).json()["replayed"]
        changed = body(
            template, context={"name": "Fictional", "banner": image_value("purple")}
        )
        assert (
            client.post(
                f"{ROOT}/notifications", json=changed, headers=headers
            ).status_code
            == 409
        )
        draft["images"]["logo"] = image_value("black")
        draft["runtime_defaults"]["banner"] = image_value("black")
        assert (
            client.put(
                base + "/draft", json={"draft": draft, "expected_revision": 2}
            ).status_code
            == 200
        )
        assert client.get(base + f"/versions/{version['id']}").json()["content"][
            "images"
        ]["logo"] == image_value("red")
        # A new application instance reads persisted image bytes after an API restart.
        restarted = application(store)
        with TestClient(restarted) as other:
            sign_in(other)
            assert other.get(base).json()["draft"]["images"]["logo"] == image_value(
                "black"
            )
        with Session(engine) as db:
            item = db.get(Notification, identifier)
            assert image_value("yellow")["content_base64"] not in item.encrypted_payload

        async def run():
            async def broker(value):
                assert value == str(identifier)

            assert await publish_once(factory, broker)
            await consume(
                factory, app.state.settings, {"smtp": SMTPProvider}, identifier
            )

        asyncio.run(run())
        assert len(sent) == 1
        expected = {
            ImageContent.model_validate(image_value(color)).cid: image_value(color)[
                "content_base64"
            ]
            for color in ("red", "yellow")
        }
        assert {image.cid: image.content_base64 for image in sent[0].images} == expected
        with Session(engine) as db:
            item = db.get(Notification, identifier)
            assert item.status == "sent" and item.encrypted_payload is None

        # Expiry removes image-bearing runtime payloads without a provider call.
        from datetime import timedelta

        from backend.app.infrastructure.database import utcnow

        expiring = client.post(
            f"{ROOT}/notifications",
            json=payload,
            headers={**headers, "Idempotency-Key": "expiring-image"},
        )
        assert expiring.status_code == 202
        expired_id = UUID(expiring.json()["id"])
        with Session(engine) as db:
            item = db.get(Notification, expired_id)
            item.expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        asyncio.run(
            consume(factory, app.state.settings, {"smtp": SMTPProvider}, expired_id)
        )
        assert len(sent) == 1
        with Session(engine) as db:
            item = db.get(Notification, expired_id)
            assert item.status == "failed" and item.encrypted_payload is None

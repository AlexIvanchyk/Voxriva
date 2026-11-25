import json
import runpy
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.features.providers.adapters.smtp import SMTPProvider
from backend.app.infrastructure.model_registry import (
    AuditEvent,
    Notification,
    NotificationAttempt,
    NotificationOutbox,
    ProviderEvent,
)
from tests.support.administration import ROOT, application
from tests.support.cloud_providers import DEVICE, push_setup
from tests.support.notifications import body, prepare


def totals(engine):
    with Session(engine) as db:
        return [
            db.scalar(select(func.count()).select_from(model))
            for model in [
                Notification,
                NotificationOutbox,
                NotificationAttempt,
                AuditEvent,
                ProviderEvent,
            ]
        ]


def test_validation_uses_acceptance_preflight_without_writes_or_transport_calls(
    store, monkeypatch
):
    app = application(store)

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Read-only validation must never send or test a connection"
        )

    monkeypatch.setattr(SMTPProvider, "send", forbidden)
    monkeypatch.setattr(SMTPProvider, "test_connection", forbidden)
    with TestClient(app) as client:
        _, env, _, template, version, provider, headers = prepare(client, app)
        before = totals(store[0])
        auth = {"Authorization": headers["Authorization"]}
        path = f"{ROOT}/notifications/validate"
        result = client.post(path, json=body(template), headers=auth)
        assert result.status_code == 200, result.text
        assert result.json()["valid"] and result.json()["environment_id"] == env["id"]
        assert (
            result.json()["template_version_id"] == version["id"]
            and result.json()["provider_revision_id"] == provider["latest"]["id"]
        )
        assert (
            "recipient.private" not in result.text and "RuntimeOnly" not in result.text
        )
        assert (
            client.post(path, json=body(template, context={}), headers=auth).status_code
            == 422
        )
        assert client.post(path, json=body(template)).status_code == 401
        assert (
            client.post(
                path, json=body(template), headers={"Authorization": "Bearer invalid"}
            ).status_code
            == 401
        )
        assert totals(store[0]) == before
        sent = client.post(
            f"{ROOT}/notifications", json=body(template), headers=headers
        )
        assert (
            sent.status_code == 202
            and sent.json()["template_version_id"]
            == result.json()["template_version_id"]
        )
        assert totals(store[0])[:3] == [1, 1, 0]


def test_push_validation_is_bounded_and_never_uses_preview_data(store):
    app = application(store)
    with TestClient(app) as client:
        template, headers = push_setup(client, app)
        before = totals(store[0])
        payload = {
            "template_key": template["key"],
            "device_token": DEVICE,
            "context": {"name": "Runtime"},
        }
        result = client.post(
            f"{ROOT}/notifications/validate", headers=headers, json=payload
        )
        assert result.status_code == 200 and result.json()["channel"] == "push"
        assert DEVICE not in result.text
        assert (
            client.post(
                f"{ROOT}/notifications/validate",
                headers=headers,
                json={**payload, "context": {}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{ROOT}/notifications/validate",
                headers=headers,
                json={**payload, "context": {"name": "x" * 5000}},
            ).status_code
            == 422
        )
        assert totals(store[0]) == before


def test_delivery_v1_contract_has_no_unreviewed_drift():
    root = Path(__file__).parents[2]
    generated = runpy.run_path(str(root / "scripts/freeze-delivery-contract.py"))[
        "contract"
    ]()
    assert generated == json.loads(
        (root / "contracts/delivery-v1.openapi.json").read_text()
    )

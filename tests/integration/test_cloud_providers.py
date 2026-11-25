import asyncio
import base64
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.features.notifications.delivery import consume
from backend.app.features.notifications.recovery import reconcile
from backend.app.features.providers.adapters.fcm import FCMConfig, FCMProvider
from backend.app.features.providers.adapters.ses import SESConfig, SESProvider
from backend.app.features.providers.events_service import verify_sns
from backend.app.infrastructure.model_registry import (
    Notification,
    ProviderEvent,
    utcnow,
)
from backend.app.shared.provider_contract import (
    EmailMessage,
    ProviderError,
    ProviderResult,
    PushMessage,
)
from tests.support.administration import ROOT, application, create, sign_in
from tests.support.cloud_providers import DEVICE, push_setup
from tests.support.lifecycle import mutate, publish, setup, target
from tests.support.notifications import body
from tests.support.providers import enable_crypto

TOPIC = "arn:aws:sns:us-east-1:123456789012:voxriva-delivery"
CERT_URL = "https://sns.us-east-1.amazonaws.com/SimpleNotificationService-test.pem"


@pytest.fixture(scope="module")
def signer():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def envelope(signer, event="Delivery", occurred=None, external_id=None, **changes):
    payload = {
        "Type": "Notification",
        "MessageId": external_id or str(uuid4()),
        "TopicArn": TOPIC,
        "Timestamp": utcnow().isoformat(),
        "SignatureVersion": "2",
        "SigningCertURL": CERT_URL,
        "Message": json.dumps(
            {
                "eventType": event,
                "mail": {
                    "messageId": "aws-message-1",
                    "destination": ["PRIVATE@example.test"],
                },
                event.lower(): {
                    "timestamp": (occurred or utcnow()).isoformat(),
                    "recipient": "PRIVATE@example.test",
                },
            }
        ),
        **changes,
    }
    fields = [
        "Message",
        "MessageId",
        *(["Subject"] if "Subject" in payload else []),
        "Timestamp",
        "TopicArn",
        "Type",
    ]
    if payload["Type"] == "SubscriptionConfirmation":
        fields = [
            "Message",
            "MessageId",
            "SubscribeURL",
            "Timestamp",
            "Token",
            "TopicArn",
            "Type",
        ]
    canonical = "".join(name + "\n" + payload[name] + "\n" for name in fields).encode()
    payload["Signature"] = base64.b64encode(
        signer[0].sign(canonical, padding.PKCS1v15(), hashes.SHA256())
    ).decode()
    return payload


def test_ses_pins_sdk_timeout_disables_sdk_retries_and_normalizes_errors(monkeypatch):
    seen = []

    class Client:
        failure = None

        def get_account(self):
            return {"SendingEnabled": True}

        def send_email(self, **kwargs):
            seen.append(kwargs)
            if self.failure:
                raise self.failure
            return {"MessageId": "aws-message-1"}

        def close(self):
            pass

    client = Client()

    class SDK:
        def __init__(self, **kwargs):
            assert kwargs["aws_access_key_id"] == "synthetic-id"

        def client(self, service, config):
            assert service == "sesv2" and config.retries == {"total_max_attempts": 1}
            assert config.connect_timeout == config.read_timeout == 10
            return client

    monkeypatch.setattr(
        "backend.app.features.providers.adapters.ses.boto3.Session", SDK
    )
    provider = SESProvider(
        SESConfig(
            sender="sender@example.test",
            auth_mode="access_keys",
            access_key_id="synthetic-id",
            secret_access_key="synthetic-secret",
            configuration_set="events",
        )
    )
    assert provider.test_connection().status == "connected" and not seen
    assert (
        provider.send(
            EmailMessage(
                recipient="demo@example.test",
                subject="Hello",
                text="Text",
                html="<b>HTML</b>",
            )
        ).message_id
        == "aws-message-1"
    )
    assert (
        seen[0]["ConfigurationSetName"] == "events"
        and seen[0]["Content"]["Simple"]["Body"]["Html"]["Data"] == "<b>HTML</b>"
    )
    client.failure = ClientError(
        {
            "Error": {"Code": "TooManyRequestsException", "Message": "RAW-SECRET"},
            "ResponseMetadata": {"HTTPStatusCode": 429},
        },
        "SendEmail",
    )
    with pytest.raises(ProviderError) as error:
        provider.send(
            EmailMessage(recipient="demo@example.test", subject="Hello", text="Text")
        )
    assert (
        error.value.retryable
        and not error.value.uncertain
        and error.value.retry_after == 60
    )
    client.failure = ReadTimeoutError(
        endpoint_url="https://email.us-east-1.amazonaws.com"
    )
    with pytest.raises(ProviderError) as error:
        provider.send(
            EmailMessage(recipient="demo@example.test", subject="Hello", text="Text")
        )
    assert error.value.uncertain and not error.value.retryable


def test_fcm_actual_wire_contract_validate_only_error_codes_and_ambiguous_timeout(
    monkeypatch,
):
    calls, answer = [], [200, {}, {}]

    def handle(request):
        assert (
            request.url.host == "fcm.googleapis.com"
            and request.headers["Authorization"] == "Bearer synthetic-oauth"
        )
        calls.append(json.loads(request.content))
        if answer[0] == "timeout":
            raise httpx.ReadTimeout("RAW-SECRET", request=request)
        return httpx.Response(
            answer[0],
            json=answer[1] or {"name": "projects/firebase-demo/messages/synthetic-id"},
            headers=answer[2],
        )

    original = httpx.Client
    monkeypatch.setattr(
        "backend.app.features.providers.adapters.fcm.httpx.Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(FCMProvider, "access_token", lambda self: "synthetic-oauth")
    provider = FCMProvider(FCMConfig(project_id="firebase-demo", auth_mode="default"))
    message = PushMessage(
        token=DEVICE, title="Hello", body="Body", data={"screen": "home"}
    )
    assert (
        provider.validate(message).status == "connected" and calls[-1]["validate_only"]
    )
    assert (
        provider.send(message).status == "accepted" and not calls[-1]["validate_only"]
    )
    assert calls[-1]["message"]["token"] == DEVICE and calls[-1]["message"]["data"] == {
        "screen": "home"
    }
    answer[:] = [429, {"error": {}}, {"Retry-After": "120"}]
    with pytest.raises(ProviderError) as error:
        provider.send(message)
    assert (
        error.value.code == "rate_limited"
        and error.value.retry_after == 120
        and not error.value.uncertain
    )
    answer[:] = [404, {"error": {"details": [{"errorCode": "UNREGISTERED"}]}}, {}]
    with pytest.raises(ProviderError) as error:
        provider.send(message)
    assert error.value.code == "device_unregistered" and not error.value.retryable
    answer[:] = ["timeout", {}, {}]
    with pytest.raises(ProviderError) as error:
        provider.send(message)
    assert (
        error.value.uncertain
        and not error.value.retryable
        and "RAW-SECRET" not in str(error.value)
    )


def test_cloud_settings_secrets_are_write_only_and_untrusted_oauth_endpoint_is_rejected(
    store, signer
):
    app = application(store)
    private = (
        signer[0]
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    info = {
        "type": "service_account",
        "client_email": "demo@firebase-demo.iam.gserviceaccount.com",
        "private_key": private,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    with TestClient(app) as client:
        enable_crypto(app)
        sign_in(client)
        types = client.get(f"{ROOT}/providers/types").json()
        assert {row["key"] for row in types} >= {"smtp", "aws_ses", "firebase_fcm"}
        provider = create(
            client,
            "/providers",
            name="Firebase",
            provider_type="firebase_fcm",
            config={
                "project_id": "firebase-demo",
                "service_account_json": json.dumps(info),
            },
        )
        assert provider["latest"]["configured_secrets"] == [
            "service_account_json"
        ] and "private_key" not in json.dumps(provider)
        bad = client.post(
            f"{ROOT}/providers",
            json={
                "name": "Bad credentials",
                "provider_type": "firebase_fcm",
                "config": {
                    "project_id": "firebase-demo",
                    "service_account_json": json.dumps(
                        {**info, "token_uri": "http://127.0.0.1/private"}
                    ),
                },
            },
        )
        assert (
            bad.status_code == 422
            and "PRIVATE KEY" not in bad.text
            and "127.0.0.1" not in bad.text
        )
        assert (
            client.post(
                f"{ROOT}/providers",
                json={
                    "name": "Missing AWS secret",
                    "provider_type": "aws_ses",
                    "config": {
                        "sender": "sender@example.test",
                        "auth_mode": "access_keys",
                        "access_key_id": "synthetic",
                    },
                },
            ).status_code
            == 422
        )


def test_push_acceptance_context_pins_masked_history_and_expired_replay(
    store, monkeypatch
):
    engine, factory = store
    app = application(store)
    sent = []

    def send(self, message):
        sent.append(message)
        return ProviderResult(
            status="accepted",
            message="Accepted",
            message_id="projects/firebase-demo/messages/1",
        )

    monkeypatch.setattr(FCMProvider, "send", send)
    with TestClient(app) as client:
        template, headers = push_setup(client, app)
        payload = {
            "template_key": template["key"],
            "device_token": DEVICE,
            "context": {"name": "RuntimeOnly"},
        }
        assert (
            client.post(
                f"{ROOT}/notifications",
                headers=headers,
                json={**payload, "context": {}},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{ROOT}/notifications",
                headers=headers,
                json={**payload, "recipient": "wrong@example.test"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{ROOT}/notifications",
                headers=headers,
                json={**payload, "context": {"name": "x" * 4000}},
            ).status_code
            == 422
        )
        accepted = client.post(f"{ROOT}/notifications", headers=headers, json=payload)
        assert accepted.status_code == 202, accepted.text
        identifier = UUID(accepted.json()["id"])
        asyncio.run(
            consume(
                factory, app.state.settings, {"firebase_fcm": FCMProvider}, identifier
            )
        )
        asyncio.run(
            consume(
                factory, app.state.settings, {"firebase_fcm": FCMProvider}, identifier
            )
        )
        assert (
            len(sent) == 1
            and sent[0].title == "Hello RuntimeOnly"
            and sent[0].data == {"screen": "home"}
        )
        detail = client.get(f"{ROOT}/notifications/{identifier}")
        assert (
            detail.json()["status"] == "sent"
            and DEVICE not in detail.text
            and "RuntimeOnly" not in detail.text
        )
        # Expired historical failure requires a new device token and actual runtime context.
        with Session(engine) as db:
            row = db.get(Notification, identifier)
            row.status, row.expires_at = "failed", utcnow() - timedelta(days=1)
            db.commit()
        payload = {
            "replay_key": "push-replay",
            "expected_updated_at": detail.json()["updated_at"],
            "device_token": DEVICE,
            "context": {"name": "NewRuntime"},
        }
        replay = client.post(f"{ROOT}/notifications/{identifier}/replay", json=payload)
        assert replay.status_code == 202, replay.text
        assert (
            DEVICE not in client.get(f"{ROOT}/notifications/{replay.json()['id']}").text
        )


def test_sns_signature_tamper_and_ssrf_are_rejected_before_fetch(monkeypatch, signer):
    calls = []
    monkeypatch.setattr(
        "backend.app.features.providers.events_service.certificate",
        lambda url: calls.append(url) or signer[1],
    )
    signed = envelope(signer, Subject="SES event")
    verify_sns(signed, {TOPIC})
    assert calls == [CERT_URL]
    with pytest.raises(Exception):
        verify_sns({**signed, "Message": "tampered"}, {TOPIC})
    calls.clear()
    for url in [
        "http://sns.us-east-1.amazonaws.com/SimpleNotificationService-test.pem",
        "https://sns.us-east-1.amazonaws.com.evil.test/SimpleNotificationService-test.pem",
        "https://sns.us-east-1.amazonaws.com:443/SimpleNotificationService-test.pem",
        "https://sns.us-east-1.amazonaws.com/%2e%2e/key.pem",
        "https://127.0.0.1/cert.pem",
    ]:
        with pytest.raises(ValueError):
            verify_sns({**signed, "SigningCertURL": url}, {TOPIC})
    assert not calls
    with pytest.raises(ValueError):
        verify_sns(signed, {TOPIC + "-other"})


def test_verified_ses_events_early_delivery_duplicate_out_of_order_and_subscription(
    store, monkeypatch, signer
):
    engine, factory = store
    app = application(store)
    monkeypatch.setattr(
        "backend.app.features.providers.events_service.certificate",
        lambda url: signer[1],
    )
    monkeypatch.setattr(
        SESProvider,
        "send",
        lambda self, message: ProviderResult(
            status="accepted", message="Accepted", message_id="aws-message-1"
        ),
    )
    confirmations = []
    monkeypatch.setattr(
        SESProvider,
        "confirm_subscription",
        lambda self, topic, token: confirmations.append((topic, token)),
    )
    with TestClient(app) as client:
        enable_crypto(app)
        sign_in(client)
        project, dev, _, template = setup(client)
        version = publish(client, template)
        assert (
            mutate(
                client, template, **target(project, dev), version_id=version["id"]
            ).status_code
            == 200
        )
        provider = create(
            client,
            "/providers",
            name="SES",
            provider_type="aws_ses",
            project_id=project["id"],
            config={
                "sender": "sender@example.test",
                "configuration_set": "events",
                "sns_topic_arn": TOPIC,
            },
        )
        assert (
            client.put(
                f"{ROOT}/providers/bindings",
                json={
                    "scope": "project",
                    "project_id": project["id"],
                    "channel": "email",
                    "revision_id": provider["latest"]["id"],
                    "expected_generation": 0,
                },
            ).status_code
            == 200
        )
        key = create(
            client,
            f"/projects/{project['id']}/environments/{dev['id']}/keys",
            name="SES key",
        )
        accepted = client.post(
            f"{ROOT}/notifications",
            headers={
                "Authorization": f"Bearer {key['key']}",
                "Idempotency-Key": "ses-events",
            },
            json=body(template),
        ).json()
        identifier, path = (
            UUID(accepted["id"]),
            f"{ROOT}/providers/{provider['id']}/events/ses",
        )
        delivery_time = utcnow() - timedelta(seconds=10)
        signed = envelope(signer, occurred=delivery_time)
        assert (
            client.post(path, json={**signed, "Signature": "invalid"}).status_code
            == 403
        )
        assert client.post(path, json=signed).json()["status"] == "recorded"
        assert client.post(path, json=signed).json()["status"] == "duplicate"
        assert client.get(accepted["status_url"]).json()["status"] == "queued"
        asyncio.run(
            consume(factory, app.state.settings, {"aws_ses": SESProvider}, identifier)
        )
        asyncio.run(reconcile(factory, app.state.settings))
        assert client.get(accepted["status_url"]).json()["status"] == "delivered"
        # An older delivery arriving after a newer bounce cannot undo that bounce.
        bounce = envelope(
            signer, event="Bounce", occurred=delivery_time + timedelta(seconds=2)
        )
        assert client.post(path, json=bounce).status_code == 202
        assert (
            client.post(
                path,
                json=envelope(signer, occurred=delivery_time + timedelta(seconds=1)),
            ).status_code
            == 202
        )
        detail = client.get(accepted["status_url"])
        assert (
            detail.json()["status"] == "bounced"
            and len(detail.json()["provider_events"]) == 3
        )
        assert "PRIVATE" not in detail.text
        with Session(engine) as db:
            assert "PRIVATE" not in str(
                [row.__dict__ for row in db.scalars(select(ProviderEvent))]
            )
        confirmation = envelope(
            signer,
            Type="SubscriptionConfirmation",
            SubscribeURL="https://not-fetched.example.test/private",
            Token="synthetic-sns-token",
        )
        assert (
            client.post(path, json=confirmation).json()["status"]
            == "subscription_confirmed"
        )
        assert confirmations == [(TOPIC, "synthetic-sns-token")]


def test_installed_example_plugin_is_discovered_in_dashboard_metadata(
    store, tmp_path, monkeypatch
):
    source, destination = tmp_path / "source", tmp_path / "installed"
    shutil.copytree(Path(__file__).parents[2] / "examples/provider-plugin", source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(destination),
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    monkeypatch.syspath_prepend(str(destination))
    with TestClient(application(store)) as client:
        sign_in(client)
        types = client.get(f"{ROOT}/providers/types").json()
        example = next(row for row in types if row["key"] == "example_smtp")
        assert (
            example["name"] == "Example SMTP plugin"
            and example["schema"]["properties"]["password"]["writeOnly"]
        )


def test_fcm_oauth_transport_failure_is_safe_to_retry_without_sending(monkeypatch):
    from google.auth.exceptions import TransportError

    class Credentials:
        def refresh(self, request):
            raise TransportError("RAW-SECRET")

    monkeypatch.setattr(
        "backend.app.features.providers.adapters.fcm.google.auth.default",
        lambda **kwargs: (Credentials(), "firebase-demo"),
    )
    provider = FCMProvider(FCMConfig(project_id="firebase-demo", auth_mode="default"))
    with pytest.raises(ProviderError) as error:
        provider.access_token()
    assert (
        error.value.retryable
        and not error.value.uncertain
        and "RAW-SECRET" not in str(error.value)
    )

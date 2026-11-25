from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.features.providers.adapters.crypto import decrypt, encrypt
from backend.app.features.providers.adapters.registry import (
    discover,
    metadata,
    secret_fields,
)
from backend.app.features.providers.adapters.smtp import SMTPProvider
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.model_registry import ProviderRevision
from backend.app.infrastructure.settings import Settings
from backend.app.shared.provider_contract import ProviderError, ProviderResult
from tests.support.administration import PASSWORD, ROOT, application, create, sign_in
from tests.support.providers import config, enable_crypto, provider

SECRET = "fictional-smtp-password-123"


def test_provider_revisions_encrypt_redact_keep_rotate_and_pin_credentials(store):
    engine, _ = store
    app = application(store)
    with TestClient(app) as client:
        enable_crypto(app)
        sign_in(client)
        project = create(client, "/projects", name="Provider demo")
        item = provider(
            client, project["id"], username="synthetic", password=SECRET, tls="starttls"
        )
        assert item["latest"]["configured_secrets"] == ["password"]
        assert "password" not in item["latest"]["config"]
        base = f"{ROOT}/providers/{item['id']}"
        binding = {
            "scope": "project",
            "project_id": project["id"],
            "channel": "email",
            "revision_id": item["latest"]["id"],
            "expected_generation": 0,
        }
        assert client.put(f"{ROOT}/providers/bindings", json=binding).status_code == 200
        keep = client.post(
            f"{base}/revisions", json={"expected_revision": 1, "config": {"port": 2525}}
        )
        assert keep.status_code == 201, keep.text
        rotated = client.post(
            f"{base}/revisions",
            json={
                "expected_revision": 2,
                "config": {"password": "replacement-fictional-password"},
            },
        )
        assert rotated.status_code == 201
        assert rotated.json()["latest"]["number"] == 3
        stale = client.post(
            f"{base}/revisions",
            json={
                "expected_revision": 2,
                "config": {"password": "stale-fictional-password"},
            },
        )
        assert stale.status_code == 409
        for path in [
            f"{ROOT}/providers",
            f"{base}/revisions",
            f"{ROOT}/providers/bindings",
        ]:
            response = client.get(path)
            assert response.status_code == 200
            assert (
                SECRET not in response.text
                and "replacement-fictional-password" not in response.text
            )
        rows = client.get(f"{ROOT}/providers/bindings").json()
        assert (
            next(
                row
                for row in rows
                if row["project_id"] == project["id"] and row["channel"] == "email"
            )["direct"]["revision"]
            == 1
        )
        with Session(engine) as db:
            revisions = list(
                db.scalars(select(ProviderRevision).order_by(ProviderRevision.number))
            )
            assert [
                decrypt(app.state.settings, row.encrypted_secrets)["password"]
                for row in revisions
            ] == [SECRET, SECRET, "replacement-fictional-password"]
            assert all(
                SECRET not in row.encrypted_secrets
                and SECRET not in str(row.public_config)
                for row in revisions
            )
            with pytest.raises(IntegrityError, match="immutable"):
                db.execute(
                    update(ProviderRevision)
                    .where(ProviderRevision.id == revisions[0].id)
                    .values(public_config={})
                )
            db.rollback()
        assert (
            client.put(
                f"{ROOT}/providers/bindings",
                json={
                    **binding,
                    "revision_id": rotated.json()["latest"]["id"],
                    "expected_generation": 1,
                },
            ).status_code
            == 200
        )
        assert client.put(f"{ROOT}/providers/bindings", json=binding).status_code == 409
        cleared = client.post(
            f"{base}/revisions",
            json={
                "expected_revision": 3,
                "config": {"username": ""},
                "clear_secrets": ["password"],
            },
        )
        assert cleared.status_code == 201
        assert cleared.json()["latest"]["configured_secrets"] == []


def test_provider_permissions_bindings_and_resolution_never_cross_projects(store):
    app = application(store)
    with TestClient(app) as admin:
        enable_crypto(app)
        sign_in(admin)
        a = create(admin, "/projects", name="Visible")
        b = create(admin, "/projects", name="Private")
        dev = create(admin, f"/projects/{a['id']}/environments", name="dev")
        secret_env = create(admin, f"/projects/{b['id']}/environments", name="secret")
        shared = provider(admin)
        own = provider(admin, a["id"])
        private = provider(admin, b["id"])
        create(
            admin,
            f"/projects/{a['id']}/members",
            email="manager@example.test",
            password=PASSWORD,
            role="project_admin",
        )
        create(
            admin,
            f"/projects/{a['id']}/members",
            email="reader@example.test",
            password=PASSWORD,
            role="viewer",
        )
        assert (
            admin.put(
                f"{ROOT}/providers/bindings",
                json={
                    "scope": "global",
                    "channel": "email",
                    "revision_id": shared["latest"]["id"],
                    "expected_generation": 0,
                },
            ).status_code
            == 200
        )
        with TestClient(app) as manager:
            sign_in(manager, "manager@example.test")
            assert {item["id"] for item in manager.get(f"{ROOT}/providers").json()} == {
                shared["id"],
                own["id"],
            }
            assert not next(
                item
                for item in manager.get(f"{ROOT}/providers").json()
                if item["id"] == shared["id"]
            )["editable"]
            assert (
                manager.get(f"{ROOT}/providers/{private['id']}/revisions").status_code
                == 404
            )
            assert (
                manager.post(
                    f"{ROOT}/providers/{shared['id']}/test-connection",
                    json={"revision_id": shared["latest"]["id"]},
                ).status_code
                == 403
            )
            target = {
                "scope": "environment",
                "project_id": a["id"],
                "environment_id": dev["id"],
                "channel": "email",
                "expected_generation": 0,
            }
            assert (
                manager.put(
                    f"{ROOT}/providers/bindings",
                    json={**target, "revision_id": private["latest"]["id"]},
                ).status_code
                == 404
            )
            assert (
                manager.put(
                    f"{ROOT}/providers/bindings",
                    json={
                        **target,
                        "environment_id": secret_env["id"],
                        "revision_id": own["latest"]["id"],
                    },
                ).status_code
                == 404
            )
            assert (
                manager.put(
                    f"{ROOT}/providers/bindings",
                    json={
                        **target,
                        "channel": "push",
                        "revision_id": own["latest"]["id"],
                    },
                ).status_code
                == 422
            )
            inherited = next(
                row
                for row in manager.get(f"{ROOT}/providers/bindings").json()
                if row["environment_id"] == dev["id"] and row["channel"] == "email"
            )
            assert (
                inherited["effective"]["revision_id"] == shared["latest"]["id"]
                and inherited["effective_scope"] == "global"
            )
            assert (
                manager.put(
                    f"{ROOT}/providers/bindings",
                    json={**target, "revision_id": own["latest"]["id"]},
                ).status_code
                == 200
            )
            resolved = next(
                row
                for row in manager.get(f"{ROOT}/providers/bindings").json()
                if row["environment_id"] == dev["id"] and row["channel"] == "email"
            )
            assert (
                resolved["effective"]["revision_id"] == own["latest"]["id"]
                and resolved["effective_scope"] == "environment"
            )
            assert not any(
                row["project_id"] == b["id"]
                for row in manager.get(f"{ROOT}/providers/bindings").json()
            )
            response = manager.get(
                f"{ROOT}/providers/resolve",
                params={
                    "project_id": a["id"],
                    "environment_id": dev["id"],
                    "channel": "email",
                },
            )
            assert (
                response.status_code == 200
                and response.json()["provider"]["revision_id"] == own["latest"]["id"]
            )
            assert (
                manager.get(
                    f"{ROOT}/providers/resolve",
                    params={
                        "project_id": a["id"],
                        "environment_id": secret_env["id"],
                        "channel": "email",
                    },
                ).status_code
                == 404
            )
        with TestClient(app) as reader:
            sign_in(reader, "reader@example.test")
            assert reader.get(f"{ROOT}/providers").status_code == 200
            assert (
                reader.post(
                    f"{ROOT}/providers/{own['id']}/revisions",
                    json={"expected_revision": 1, "config": {}},
                ).status_code
                == 403
            )
            assert (
                reader.post(
                    f"{ROOT}/providers/{own['id']}/send-test",
                    json={
                        "revision_id": own["latest"]["id"],
                        "recipient": "sample@example.test",
                    },
                ).status_code
                == 403
            )
            assert (
                reader.post(
                    f"{ROOT}/providers",
                    json={
                        "name": "Denied",
                        "provider_type": "smtp",
                        "project_id": a["id"],
                        "config": config(),
                    },
                ).status_code
                == 403
            )
        assert (
            admin.put(
                f"{ROOT}/providers/bindings",
                json={
                    "scope": "global",
                    "channel": "email",
                    "revision_id": own["latest"]["id"],
                    "expected_generation": 1,
                },
            ).status_code
            == 404
        )


def test_provider_tests_are_explicit_rate_limited_and_redact_transport_errors(
    store, monkeypatch
):
    app = application(store)
    calls = []

    def connection(self):
        calls.append("connection")
        return ProviderResult(
            status="connected", message="Connection succeeded; no email was sent."
        )

    def send(self, message):
        calls.append(message.recipient)
        return ProviderResult(status="accepted", message="Test accepted.")

    monkeypatch.setattr(SMTPProvider, "test_connection", connection)
    monkeypatch.setattr(SMTPProvider, "send", send)
    with TestClient(app) as client:
        enable_crypto(app)
        sign_in(client)
        item = provider(client)
        assert calls == []
        base = f"{ROOT}/providers/{item['id']}"
        payload = {"revision_id": item["latest"]["id"]}
        assert client.get(f"{ROOT}/providers").status_code == 200
        assert client.post(f"{base}/test-connection", json=payload).status_code == 200
        assert calls == ["connection"]
        assert (
            client.post(
                f"{base}/send-test",
                json={**payload, "recipient": "synthetic@example.test"},
            ).status_code
            == 200
        )
        assert calls == ["connection", "synthetic@example.test"]
        assert (
            client.post(
                f"{base}/send-test",
                json={**payload, "recipient": "bad\r\nBcc: victim@example.test"},
            ).status_code
            == 422
        )

        def failing(self):
            raise RuntimeError(
                f"smtp://synthetic:{SECRET}@mailpit raw transport details"
            )

        monkeypatch.setattr(SMTPProvider, "test_connection", failing)
        failure = client.post(f"{base}/test-connection", json=payload)
        assert (
            failure.status_code == 502
            and SECRET not in failure.text
            and "raw transport" not in failure.text
        )

        def rejected(self):
            raise ProviderError(SECRET)

        monkeypatch.setattr(SMTPProvider, "test_connection", rejected)
        failure = client.post(f"{base}/test-connection", json=payload)
        assert failure.status_code == 502 and SECRET not in failure.text
        for _ in range(6):
            assert (
                client.post(f"{base}/test-connection", json=payload).status_code == 502
            )
        assert client.post(f"{base}/test-connection", json=payload).status_code == 429


def test_provider_validation_missing_key_and_keyring_rotation(store):
    app = application(store)
    with TestClient(app) as client:
        sign_in(client)
        response = client.post(
            f"{ROOT}/providers",
            json={"name": "Unencrypted", "provider_type": "smtp", "config": config()},
        )
        assert response.status_code == 503
        enable_crypto(app)
        bad = client.post(
            f"{ROOT}/providers",
            json={
                "name": "Invalid",
                "provider_type": "smtp",
                "config": config(password=SECRET),
            },
        )
        assert bad.status_code == 422 and SECRET not in bad.text
        app.state.settings.smtp_allowed_hosts = ["mailpit"]
        assert (
            client.post(
                f"{ROOT}/providers",
                json={
                    "name": "Denied host",
                    "provider_type": "smtp",
                    "config": config(host="not-allowed.example.test"),
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{ROOT}/providers",
                json={
                    "name": "Unknown",
                    "provider_type": "not-installed",
                    "config": {},
                },
            ).status_code
            == 422
        )
        item = provider(client)
        assert (
            client.post(
                f"{ROOT}/providers/{item['id']}/revisions",
                json={"expected_revision": 1, "config": {}, "clear_secrets": ["host"]},
            ).status_code
            == 422
        )
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings = Settings(provider_encryption_keys=SecretStr(old))
    ciphertext = encrypt(settings, {"password": SECRET})
    settings.provider_encryption_keys = SecretStr(f"{new},{old}")
    assert decrypt(settings, ciphertext) == {"password": SECRET}
    latest = encrypt(settings, {"password": "new"})
    assert Fernet(new.encode()).decrypt(latest.encode())
    settings.provider_encryption_keys = SecretStr(new)
    with pytest.raises(ApplicationError) as error:
        decrypt(settings, ciphertext)
    assert error.value.status_code == 503


def test_provider_discovery_rejects_duplicate_invalid_interfaces_and_exposes_schema(
    monkeypatch,
):
    monkeypatch.setattr(
        "backend.app.features.providers.adapters.registry.entry_points",
        lambda **kwargs: [],
    )
    assert discover()["smtp"] is SMTPProvider
    schema = metadata(SMTPProvider)
    assert schema["schema"]["properties"]["password"]["writeOnly"]
    assert schema["capabilities"]["delivery_confirmation"] is False
    monkeypatch.setattr(
        "backend.app.features.providers.adapters.registry.entry_points",
        lambda **kwargs: [SimpleNamespace(load=lambda: SMTPProvider)],
    )
    with pytest.raises(RuntimeError, match="Duplicate"):
        discover()

    class Example(SMTPProvider):
        key = "example_smtp"

    monkeypatch.setattr(
        "backend.app.features.providers.adapters.registry.entry_points",
        lambda **kwargs: [SimpleNamespace(load=lambda: Example)],
    )
    assert discover()["example_smtp"] is Example
    from backend.app.shared.provider_contract import ProviderConfig

    class OptionalSecret(ProviderConfig):
        token: SecretStr | None = None

    class SecretAdapter(SMTPProvider):
        config_model = OptionalSecret

    assert metadata(SecretAdapter)["schema"]["properties"]["token"]["writeOnly"]
    assert secret_fields(SecretAdapter) == {"token"}

    class Newer(SMTPProvider):
        interface_version = 999
        key = "future"

    monkeypatch.setattr(
        "backend.app.features.providers.adapters.registry.entry_points",
        lambda **kwargs: [SimpleNamespace(load=lambda: Newer)],
    )
    with pytest.raises(RuntimeError, match="unsupported"):
        discover()


def test_smtp_connection_probe_never_sends_and_tls_authentication_is_explicit(
    monkeypatch,
):
    import smtplib
    import ssl

    from backend.app.features.providers.adapters.smtp import SMTPConfig
    from backend.app.shared.provider_contract import EmailMessage

    calls = []

    class Transport:
        def __init__(self, host, port, timeout, **kwargs):
            calls.append(("connect", host, port, timeout))

        def ehlo_or_helo_if_needed(self):
            calls.append("hello")

        def starttls(self, context):
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
            calls.append("starttls")

        def ehlo(self):
            calls.append("ehlo")

        def login(self, username, password):
            assert username == "synthetic" and password == SECRET
            calls.append("login")

        def noop(self):
            calls.append("noop")
            return 250, b"ok"

        def send_message(self, message, from_addr, to_addrs):
            assert from_addr == "sender@example.test" and to_addrs == [
                "synthetic@example.test"
            ]
            assert message["Subject"] == "Synthetic test" and message.is_multipart()
            calls.append("send")
            return {}

        def close(self):
            calls.append("close")

    monkeypatch.setattr(smtplib, "SMTP", Transport)
    provider = SMTPProvider(
        SMTPConfig.model_validate(
            config(port=587, tls="starttls", username="synthetic", password=SECRET)
        )
    )
    assert provider.test_connection().status == "connected"
    assert calls == [
        ("connect", "mailpit", 587, 5),
        "hello",
        "starttls",
        "ehlo",
        "login",
        "noop",
        "close",
    ]
    calls.clear()
    assert (
        provider.send(
            EmailMessage(
                recipient="synthetic@example.test",
                subject="Synthetic test",
                text="Synthetic body",
                html="<p>Synthetic body</p>",
            )
        ).status
        == "accepted"
    )
    assert "send" in calls

    def rejected(self, username, password):
        raise smtplib.SMTPAuthenticationError(535, SECRET.encode())

    monkeypatch.setattr(Transport, "login", rejected)
    with pytest.raises(ProviderError) as error:
        provider.test_connection()
    assert error.value.code == "authentication_failed" and SECRET not in str(
        error.value
    )

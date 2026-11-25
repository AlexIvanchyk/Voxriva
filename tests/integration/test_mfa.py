"""Fictional accounts only. Exercise HTTP gating and actual persisted factor state."""

import asyncio
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, update

from backend.app.features.identity import mfa
from backend.app.features.identity.models import Account, AccountMFA, MFAChallenge
from backend.app.features.identity.service import digest
from backend.app.infrastructure.database import utcnow
from tests.support.administration import (
    ADMIN,
    LOGIN_HEADERS,
    PASSWORD,
    application,
    sign_in,
)


def configure(client, policy="optional"):
    client.app.state.settings.provider_encryption_keys = SecretStr(
        Fernet.generate_key().decode()
    )
    client.app.state.settings.mfa_policy = policy


def login(client):
    return client.post(
        "/api/v1/auth/login",
        headers=LOGIN_HEADERS,
        json={"email": ADMIN, "password": PASSWORD},
    )


def otp(secret, offset=0):
    return (
        mfa.totp(secret)
        .generate((int(utcnow().timestamp()) // 30 + offset) * 30)
        .decode()
    )


def setup(client):
    response = client.post("/api/v1/auth/mfa/setup", json={"password": PASSWORD})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["uri"].startswith("otpauth://totp/")
    return data["secret"]


def enroll(client):
    sign_in(client)
    secret = setup(client)
    response = client.post("/api/v1/auth/mfa/confirm", json={"code": otp(secret)})
    assert response.status_code == 200, response.text
    return secret, response.json()["recovery_codes"]


def mutate(store, model, **values):
    async def run():
        async with store[1]() as db:
            await db.execute(update(model).values(**values))
            await db.commit()

    asyncio.run(run())


def test_optional_enrollment_login_gate_and_one_time_recovery(store):
    with TestClient(application(store)) as client:
        configure(client)
        secret, codes = enroll(client)
        assert len(set(codes)) == 10

        async def inspect():
            async with store[1]() as db:
                state = (await db.scalars(select(AccountMFA))).one()
                assert secret not in state.secret
                assert codes[0] not in str(state.recovery_hashes)
                assert digest(codes[0].replace("-", "")) in state.recovery_hashes

        asyncio.run(inspect())
        # Correct password alone revokes the previous session and grants no permission.
        result = login(client)
        assert result.status_code == 200
        assert (
            result.json()["mfa_required"] and not result.json()["enrollment_required"]
        )
        challenge = result.json()["challenge"]
        assert client.get("/api/v1/auth/session").status_code == 401
        assert client.get("/api/v1/projects").status_code == 401
        payload = {"challenge": challenge, "code": codes[0]}
        assert client.post("/api/v1/auth/mfa/verify", json=payload).status_code == 403
        response = client.post(
            "/api/v1/auth/mfa/verify", headers=LOGIN_HEADERS, json=payload
        )
        assert response.status_code == 200
        assert "csrf_token" in response.json()
        assert (
            client.post(
                "/api/v1/auth/mfa/verify", headers=LOGIN_HEADERS, json=payload
            ).status_code
            == 401
        )
        challenge = login(client).json()["challenge"]
        payload["challenge"] = challenge
        assert (
            client.post(
                "/api/v1/auth/mfa/verify", headers=LOGIN_HEADERS, json=payload
            ).status_code
            == 401
        )
        payload["code"] = codes[1]
        assert (
            client.post(
                "/api/v1/auth/mfa/verify", headers=LOGIN_HEADERS, json=payload
            ).status_code
            == 200
        )
        assert client.get("/api/v1/auth/mfa").json()["recovery_codes_remaining"] == 8


def test_wrong_expired_replayed_totp_and_lockout(store):
    with TestClient(application(store)) as client:
        configure(client)
        secret, codes = enroll(client)
        challenge = login(client).json()["challenge"]

        # Enrollment consumed this step; same code cannot log in again.
        async def accepted_step():
            async with store[1]() as db:
                return (await db.scalars(select(AccountMFA))).one().last_step

        used_step = asyncio.run(accepted_step())
        reused = mfa.totp(secret).generate(used_step * 30).decode()
        expired = mfa.totp(secret).generate((used_step - 3) * 30).decode()
        for code in (reused, expired, "invalid"):
            response = client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": code},
            )
            assert response.status_code == 401
        # Cross-challenge guessing cannot reset the durable account failure counter.
        challenge = login(client).json()["challenge"]
        for _ in range(2):
            assert (
                client.post(
                    "/api/v1/auth/mfa/verify",
                    headers=LOGIN_HEADERS,
                    json={"challenge": challenge, "code": "invalid"},
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": codes[0]},
            ).status_code
            == 429
        )
        mutate(store, AccountMFA, locked_until=utcnow() - timedelta(seconds=1))
        mutate(store, MFAChallenge, expires_at=utcnow() - timedelta(seconds=1))
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": codes[0]},
            ).status_code
            == 401
        )
        challenge = login(client).json()["challenge"]
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": otp(secret, 1)},
            ).status_code
            == 200
        )


def test_setup_expiration_csrf_regenerate_disable_and_session_revocation(store):
    app = application(store)
    with TestClient(app) as client, TestClient(app) as other:
        configure(client)
        sign_in(client)
        sign_in(other)
        secret = setup(client)
        mutate(store, AccountMFA, setup_expires_at=utcnow() - timedelta(seconds=1))
        assert (
            client.post(
                "/api/v1/auth/mfa/confirm", json={"code": otp(secret)}
            ).status_code
            == 409
        )
        assert client.get("/api/v1/auth/mfa").json()["enabled"] is False
        secret = setup(client)
        codes = client.post(
            "/api/v1/auth/mfa/confirm", json={"code": otp(secret)}
        ).json()["recovery_codes"]
        assert other.get("/api/v1/auth/session").status_code == 401
        proof = {"password": PASSWORD, "code": codes[0]}
        csrf = client.headers.pop("X-CSRF-Token")
        assert (
            client.post("/api/v1/auth/mfa/recovery-codes", json=proof).status_code
            == 403
        )
        client.headers["X-CSRF-Token"] = csrf
        response = client.post("/api/v1/auth/mfa/recovery-codes", json=proof)
        assert response.status_code == 200
        new_codes = response.json()["recovery_codes"]
        assert not set(codes) & set(new_codes)
        assert (
            client.post(
                "/api/v1/auth/mfa/disable",
                json={"password": PASSWORD, "code": codes[1]},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/mfa/disable",
                json={"password": "incorrect", "code": new_codes[0]},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/auth/mfa/disable",
                json={"password": PASSWORD, "code": new_codes[0]},
            ).status_code
            == 204
        )
        assert client.get("/api/v1/auth/mfa").json()["enabled"] is False
        assert "csrf_token" in login(client).json()


def test_required_policy_existing_sessions_and_restricted_enrollment(store):
    with TestClient(application(store)) as client:
        configure(client)
        sign_in(client)
        client.app.state.settings.mfa_policy = "required"
        assert client.get("/api/v1/auth/session").status_code == 401
        challenge = login(client).json()["challenge"]
        assert client.get("/api/v1/projects").status_code == 401
        # Enrollment challenge cannot be used as a completed second factor.
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": "123456"},
            ).status_code
            == 401
        )
        response = client.post(
            "/api/v1/auth/mfa/enroll/setup",
            headers=LOGIN_HEADERS,
            json={"challenge": challenge},
        )
        assert response.status_code == 200
        secret = response.json()["secret"]
        assert client.get("/api/v1/auth/session").status_code == 401
        response = client.post(
            "/api/v1/auth/mfa/enroll/confirm",
            headers=LOGIN_HEADERS,
            json={"challenge": challenge, "code": otp(secret)},
        )
        assert response.status_code == 200
        result = response.json()
        assert client.get("/api/v1/auth/session").status_code == 200
        client.headers["X-CSRF-Token"] = result["session"]["csrf_token"]
        assert (
            client.post(
                "/api/v1/auth/mfa/disable",
                json={"password": PASSWORD, "code": result["recovery_codes"][0]},
            ).status_code
            == 409
        )
        assert not login(client).json()["enrollment_required"]


def test_keyring_missing_fails_closed_and_secrets_not_in_errors(store):
    with TestClient(application(store)) as client:
        sign_in(client)
        assert (
            client.post(
                "/api/v1/auth/mfa/setup", json={"password": PASSWORD}
            ).status_code
            == 503
        )
        assert client.get("/api/v1/auth/mfa").json()["enabled"] is False
        configure(client)
        secret = setup(client)
        response = client.post("/api/v1/auth/mfa/confirm", json={"code": "invalid"})
        assert response.status_code == 401
        assert secret not in response.text


@pytest.mark.postgres
def test_postgres_recovery_and_challenge_redemption_is_atomic(postgres_store):
    async def run():
        factory = postgres_store[1]
        from backend.app.infrastructure.settings import Settings

        settings = Settings(
            provider_encryption_keys=SecretStr(Fernet.generate_key().decode())
        )
        async with factory() as db:
            account = (await db.scalars(select(Account))).one()
            secret = (await mfa.setup(db, account.id, PASSWORD, settings))["secret"]
            codes = await mfa.confirm(db, account.id, otp(secret), settings, "")
            db.add(
                MFAChallenge(
                    token_hash=digest("x" * 43),
                    account_id=account.id,
                    expires_at=utcnow() + timedelta(minutes=5),
                )
            )
            await db.commit()

        async def redeem():
            from backend.app.infrastructure.errors import ApplicationError

            async with factory() as db:
                try:
                    await mfa.complete(db, "x" * 43, codes[0], settings)
                    return 200
                except ApplicationError as error:
                    return error.status_code

        assert sorted(await asyncio.gather(redeem(), redeem())) == [200, 401]
        # A recovery code is also serialized across two distinct challenges.
        async with factory() as db:
            for token in ("a" * 43, "b" * 43):
                db.add(
                    MFAChallenge(
                        token_hash=digest(token),
                        account_id=account.id,
                        expires_at=utcnow() + timedelta(minutes=5),
                    )
                )
            await db.commit()

        async def another(token):
            from backend.app.infrastructure.errors import ApplicationError

            async with factory() as db:
                try:
                    await mfa.complete(db, token, codes[1], settings)
                    return 200
                except ApplicationError as error:
                    return error.status_code

        assert sorted(await asyncio.gather(another("a" * 43), another("b" * 43))) == [
            200,
            401,
        ]

    asyncio.run(run())


def test_key_rotation_and_operator_lost_device_recovery(store):
    from backend.app.features.identity.models import AuditEvent
    from backend.app.features.identity.recover_mfa import reset

    with TestClient(application(store)) as client:
        configure(client)
        _, codes = enroll(client)
        old_key = client.app.state.settings.provider_encryption_keys.get_secret_value()
        client.app.state.settings.provider_encryption_keys = SecretStr(
            Fernet.generate_key().decode() + "," + old_key
        )
        challenge = login(client).json()["challenge"]
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": codes[0]},
            ).status_code
            == 200
        )
        # Losing the retained key fails closed, even for recovery proofs.
        client.app.state.settings.provider_encryption_keys = SecretStr(
            Fernet.generate_key().decode()
        )
        challenge = login(client).json()["challenge"]
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": codes[1]},
            ).status_code
            == 503
        )
        mutate(
            store, AccountMFA, locked_until=utcnow() + timedelta(minutes=5), failures=5
        )

        async def operator_reset():
            async with store[1]() as db:
                await reset(db, ADMIN)
                state = (await db.scalars(select(AccountMFA))).one()
                assert (
                    not state.enabled
                    and state.secret is None
                    and state.recovery_hashes == []
                )
                assert state.locked_until is None
                assert (
                    await db.scalar(
                        select(AuditEvent).where(
                            AuditEvent.action == "mfa.operator_reset"
                        )
                    )
                    is not None
                )

        asyncio.run(operator_reset())
        assert client.get("/api/v1/auth/session").status_code == 401
        assert (
            client.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": codes[1]},
            ).status_code
            == 401
        )
        client.app.state.settings.mfa_policy = "required"
        assert login(client).json()["enrollment_required"] is True
        assert client.get("/api/v1/projects").status_code == 401


def test_required_authenticator_replacement_keeps_old_factor_until_confirmation(store):
    app = application(store)
    with TestClient(app) as client, TestClient(app) as other:
        configure(client)
        _, codes = enroll(client)
        client.app.state.settings.mfa_policy = "required"
        proof = {"password": PASSWORD, "code": codes[0]}
        pending = client.post("/api/v1/auth/mfa/setup", json=proof)
        assert pending.status_code == 200
        new_secret = pending.json()["secret"]
        # Old authenticator/recovery material remains active during pending setup.
        challenge = login(other).json()["challenge"]
        assert (
            other.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": codes[1]},
            ).status_code
            == 200
        )
        # Expired replacement preserves current MFA instead of disabling it.
        mutate(store, AccountMFA, setup_expires_at=utcnow() - timedelta(seconds=1))
        assert (
            client.post(
                "/api/v1/auth/mfa/confirm", json={"code": otp(new_secret)}
            ).status_code
            == 409
        )
        assert client.get("/api/v1/auth/mfa").json()["enabled"] is True
        pending = client.post(
            "/api/v1/auth/mfa/setup", json={"password": PASSWORD, "code": codes[2]}
        )
        assert pending.status_code == 200
        new_secret = pending.json()["secret"]
        assert (
            client.post(
                "/api/v1/auth/mfa/confirm", json={"code": "invalid"}
            ).status_code
            == 401
        )
        response = client.post(
            "/api/v1/auth/mfa/confirm", json={"code": otp(new_secret)}
        )
        assert response.status_code == 200
        new_codes = response.json()["recovery_codes"]
        assert not set(new_codes) & set(codes)
        assert other.get("/api/v1/auth/session").status_code == 401
        challenge = login(other).json()["challenge"]
        assert (
            other.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": codes[3]},
            ).status_code
            == 401
        )
        assert (
            other.post(
                "/api/v1/auth/mfa/verify",
                headers=LOGIN_HEADERS,
                json={"challenge": challenge, "code": new_codes[0]},
            ).status_code
            == 200
        )

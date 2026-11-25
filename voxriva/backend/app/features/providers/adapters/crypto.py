import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings


def cipher(settings: Settings) -> MultiFernet:
    raw = (
        settings.provider_encryption_keys.get_secret_value()
        if settings.provider_encryption_keys
        else None
    )
    if raw is None and settings.provider_encryption_key_file:
        try:
            raw = settings.provider_encryption_key_file.read_text().strip()
        except OSError:
            raise ApplicationError(
                503, "Provider encryption key is unavailable"
            ) from None
    if not raw:
        raise ApplicationError(
            503, "Configure a provider encryption key before storing credentials"
        )
    try:
        return MultiFernet([Fernet(key.strip().encode()) for key in raw.split(",")])
    except (ValueError, TypeError):
        raise ApplicationError(503, "Provider encryption keys are invalid") from None


def encrypt(settings: Settings, data: dict[str, Any]) -> str:
    return cipher(settings).encrypt(json.dumps(data).encode()).decode()


def decrypt(settings: Settings, data: str) -> dict[str, Any]:
    try:
        result: dict[str, Any] = json.loads(cipher(settings).decrypt(data.encode()))
        return result
    except (InvalidToken, ValueError):
        raise ApplicationError(
            503,
            "Stored provider credentials cannot be decrypted with the configured keys",
        ) from None


def fingerprints(settings: Settings, payload: str) -> list[str]:
    """Keyed request hashes survive normal keyring rotation without retaining payloads."""
    import base64
    import hashlib
    import hmac

    cipher(settings)
    raw = (
        settings.provider_encryption_keys.get_secret_value()
        if settings.provider_encryption_keys
        else None
    )
    if raw is None and settings.provider_encryption_key_file:
        raw = settings.provider_encryption_key_file.read_text().strip()
    assert raw
    return [
        hmac.new(
            base64.urlsafe_b64decode(key.strip()),
            b"voxriva:notification:v1:" + payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        for key in raw.split(",")
    ]

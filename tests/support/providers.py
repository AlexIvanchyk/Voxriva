"""Synthetic SMTP configuration and ephemeral encryption keys."""

from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.support.administration import create


def config(**changes):
    return {
        "host": "mailpit",
        "port": 1025,
        "tls": "none",
        "sender": "sender@example.test",
        **changes,
    }


def provider(client, project=None, **settings):
    return create(
        client,
        "/providers",
        name="Synthetic SMTP",
        provider_type="smtp",
        project_id=project,
        config=config(**settings),
    )


def enable_crypto(app):
    app.state.settings.provider_encryption_keys = SecretStr(
        Fernet.generate_key().decode()
    )

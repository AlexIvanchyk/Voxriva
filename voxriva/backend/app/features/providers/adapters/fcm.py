"""FCM HTTP v1 with Google OAuth credentials and no implicit message retries."""

import json
import re
from collections.abc import Callable
from typing import Any, ClassVar, Literal, Self, cast

import google.auth
import httpx
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request as OAuthRequest
from google.oauth2 import service_account
from pydantic import Field, SecretStr, model_validator
from pydantic_core import PydanticCustomError

from backend.app.shared.provider_contract import (
    BaseProvider,
    Capabilities,
    ProviderConfig,
    ProviderError,
    ProviderResult,
    PushMessage,
    RenderedMessage,
)

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def account_info(value: str) -> dict[str, Any]:
    info = json.loads(value)
    if (
        not isinstance(info, dict)
        or info.get("type") != "service_account"
        or info.get("token_uri", TOKEN_URI) != TOKEN_URI
    ):
        raise ValueError(
            "Use a Google service account with the standard OAuth token endpoint"
        )
    if info.get("universe_domain", "googleapis.com") != "googleapis.com":
        raise ValueError("Unsupported Google universe")
    return {**info, "token_uri": TOKEN_URI}


class FCMConfig(ProviderConfig):
    project_id: str = Field(
        pattern="^[a-z][a-z0-9-]{4,61}[a-z0-9]$", title="Firebase project ID"
    )
    auth_mode: Literal["service_account", "default"] = Field(
        default="service_account",
        title="Authentication",
        description="Use an encrypted service account JSON or Application Default Credentials on the worker.",
    )
    service_account_json: SecretStr | None = Field(
        default=None,
        title="Service account JSON",
        json_schema_extra={"format": "textarea"},
    )
    timeout: int = Field(default=10, ge=1, le=15, title="Network timeout (seconds)")

    @model_validator(mode="after")
    def credentials(self) -> Self:
        secret = (
            self.service_account_json.get_secret_value()
            if self.service_account_json
            else ""
        )
        if self.auth_mode == "service_account":
            if not secret or len(secret) > 32000:
                raise PydanticCustomError(
                    "fcm_credentials", "Service account JSON is required"
                )
            try:
                cast(
                    Callable[..., Any],
                    service_account.Credentials.from_service_account_info,
                )(account_info(secret), scopes=[SCOPE])
            except Exception:
                raise PydanticCustomError(
                    "fcm_credentials",
                    "Invalid Google service account JSON or private key",
                ) from None
        elif secret:
            raise PydanticCustomError(
                "fcm_credentials", "Remove stored JSON for workload credentials"
            )
        return self


def retry_after(value: str | None) -> float:
    from datetime import UTC, datetime
    from email.utils import parsedate_to_datetime

    if value:
        try:
            return min(3600, max(0, float(value)))
        except ValueError:
            try:
                return min(
                    3600,
                    max(
                        0,
                        (
                            parsedate_to_datetime(value) - datetime.now(UTC)
                        ).total_seconds(),
                    ),
                )
            except (ValueError, TypeError, OverflowError):
                pass
    return 60


class FCMProvider(BaseProvider):
    key = "firebase_fcm"
    name = "Firebase Cloud Messaging"
    channel: ClassVar[Literal["email", "push"]] = "push"
    config_model = FCMConfig
    capabilities = Capabilities(validate_only=True)

    def access_token(self) -> str:
        config = FCMConfig.model_validate(self.config)
        try:
            if config.auth_mode == "service_account":
                credentials = cast(
                    Callable[..., Any],
                    service_account.Credentials.from_service_account_info,
                )(
                    account_info(
                        config.service_account_json.get_secret_value()
                        if config.service_account_json
                        else ""
                    ),
                    scopes=[SCOPE],
                )
            else:
                credentials, _ = google.auth.default(scopes=[SCOPE])
            transport = OAuthRequest()

            def bounded_request(**kwargs: Any) -> Any:
                kwargs["timeout"] = config.timeout
                return transport(**kwargs)

            try:
                credentials.refresh(bounded_request)
            finally:
                transport.session.close()
            if not credentials.token:
                raise ValueError("Missing access token")
            return str(credentials.token)
        except TransportError:
            raise ProviderError("connection_failed", True, uncertain=False) from None
        except GoogleAuthError as error:
            raise ProviderError(
                "authentication_failed", bool(error.retryable), uncertain=False
            ) from None
        except Exception:
            raise ProviderError("authentication_failed", uncertain=False) from None

    def test_connection(self) -> ProviderResult:
        self.access_token()
        return ProviderResult(
            status="connected",
            message="Google OAuth authentication succeeded. This does not verify FCM send permission or a device token. Use Validate test push for a non-delivering request.",
        )

    def validate(self, message: RenderedMessage) -> ProviderResult:
        return self.request(message, validate_only=True)

    def send(self, message: RenderedMessage) -> ProviderResult:
        return self.request(message, validate_only=False)

    def request(
        self, message: RenderedMessage, *, validate_only: bool
    ) -> ProviderResult:
        if not isinstance(message, PushMessage):
            raise ProviderError("unsupported_channel", uncertain=False)
        config = FCMConfig.model_validate(self.config)
        payload = {
            "message": {
                "token": message.token,
                "notification": {"title": message.title, "body": message.body},
                "data": message.data,
            },
            "validate_only": validate_only,
        }
        if len(json.dumps(payload, ensure_ascii=False).encode()) > 4096:
            raise ProviderError("invalid_message", uncertain=False)
        token = self.access_token()
        try:
            with httpx.Client(
                timeout=config.timeout, trust_env=False, follow_redirects=False
            ) as client:
                response = client.post(
                    f"https://fcm.googleapis.com/v1/projects/{config.project_id}/messages:send",
                    headers={"Authorization": "Bearer " + token},
                    json=payload,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ProviderError("connection_failed", True, uncertain=False) from None
        except httpx.HTTPError:
            raise ProviderError("connection_failed", uncertain=True) from None
        if response.status_code != 200:
            if response.status_code in {429, 500, 503}:
                raise ProviderError(
                    "rate_limited"
                    if response.status_code == 429
                    else "service_unavailable",
                    True,
                    uncertain=False,
                    retry_after=max(
                        60 if response.status_code == 429 else 1,
                        retry_after(response.headers.get("Retry-After")),
                    ),
                )
            try:
                details = response.json().get("error", {}).get("details", [])
                provider_codes = {
                    entry.get("errorCode")
                    for entry in details
                    if isinstance(entry, dict)
                }
            except (ValueError, AttributeError, TypeError):
                provider_codes = set()
            code = "message_rejected"
            if response.status_code == 401:
                code = "authentication_failed"
            elif response.status_code == 403:
                code = "permission_denied"
            elif response.status_code == 404 and "UNREGISTERED" in provider_codes:
                code = "device_unregistered"
            elif response.status_code == 400:
                code = "invalid_message"
            raise ProviderError(
                code,
                uncertain=response.status_code >= 500
                or 300 <= response.status_code < 400,
            )
        try:
            identifier = response.json().get("name")
        except ValueError:
            identifier = None
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(
                "projects/[A-Za-z0-9_-]+/messages/[A-Za-z0-9%:._-]+", identifier
            )
            or len(identifier) > 200
        ):
            raise ProviderError("send_outcome_unknown")
        return ProviderResult(
            status="connected" if validate_only else "accepted",
            message="FCM validated the push without delivery."
            if validate_only
            else "FCM accepted the push. Device delivery is not confirmed.",
            message_id=None if validate_only else identifier,
        )

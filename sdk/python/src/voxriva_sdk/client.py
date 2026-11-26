"""HTTPX clients: one immutable request body and idempotency key per send call."""
import asyncio
import json
import math
import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx

from .errors import (
    ApiError,
    AuthenticationError,
    ConflictError,
    InputError,
    NotFoundError,
    PermissionDeniedError,
    ProtocolError,
    RateLimitError,
    ServiceUnavailableError,
    TransportError,
    ValidationError,
    ValidationIssue,
)
from .models import (
    Accepted,
    JsonValue,
    Liveness,
    Notification,
    Readiness,
    ValidationResult,
    obj,
    parse_accepted,
    parse_notification,
    parse_validation,
)

T = TypeVar("T")
RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay: float = 0.25
    max_delay: float = 30

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 10:
            raise InputError("max_attempts must be an integer from 1 to 10.")
        if not all(math.isfinite(value) and value >= 0 for value in [self.initial_delay, self.max_delay]):
            raise InputError("Retry delays must be finite, nonnegative numbers.")


def retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        result = float(value)
    except ValueError:
        try:
            timestamp = parsedate_to_datetime(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            result = (timestamp-datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0, result) if math.isfinite(result) else None


def issues(response: httpx.Response) -> tuple[ValidationIssue, ...]:
    if response.status_code != 422:
        return ()
    try:
        detail = response.json().get("detail", [])
        entries = detail.get("issues", []) if isinstance(detail, dict) else detail
        if not isinstance(entries, list):
            return ()
        result = []
        for entry in entries[:30]:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path", entry.get("loc", []))
            if not isinstance(path, list):
                continue
            result.append(ValidationIssue(tuple(part for part in path if isinstance(part, (str, int))),
                                          str(entry.get("code", entry.get("type", "invalid")))[:100], str(entry.get("message", entry.get("msg", "Invalid value")))[:300]))
        return tuple(result)
    except (ValueError, AttributeError, TypeError):
        return ()


def api_error(response: httpx.Response, attempt: int, key: str | None) -> ApiError:
    kind = {401: AuthenticationError, 403: PermissionDeniedError, 404: NotFoundError, 409: ConflictError,
            422: ValidationError, 429: RateLimitError}.get(response.status_code, ServiceUnavailableError if response.status_code >= 500 else ApiError)
    return kind(response.status_code, attempts=attempt, idempotency_key=key, retry_after=retry_after(response), issues=issues(response))


class _Base:
    def __init__(self, base_url: str, api_key: str, *, timeout: float | httpx.Timeout, retry_policy: RetryPolicy) -> None:
        try:
            parsed = urlsplit(base_url)
            valid_url = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
            _ = parsed.port
        except ValueError:
            valid_url = False
        if not valid_url:
            raise InputError("base_url must be an installation HTTP(S) URL without credentials, query or fragment.")
        if not api_key or len(api_key) > 4096 or not re.fullmatch(r"[\x21-\x7e]+", api_key):
            raise InputError("Supply a nonempty environment API key without whitespace.")
        if isinstance(timeout, (int, float)) and (not math.isfinite(timeout) or timeout <= 0):
            raise InputError("timeout must be positive and finite.")
        self._root, self._api_key = base_url.rstrip("/"), api_key
        self._timeout, self._retry = timeout, retry_policy

    def notification_url(self, notification_id: str | UUID) -> str:
        try:
            identifier = UUID(str(notification_id))
        except (ValueError, TypeError, AttributeError):
            raise InputError("notification_id must be a UUID.") from None
        return f"{self._root}/notifications/{identifier}"

    def _key(self, supplied: str | None) -> str:
        value = str(uuid4()) if supplied is None else supplied
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value):
            raise InputError("Use an idempotency key of 1–128 letters, digits, dots, underscores, colons or hyphens.")
        return value

    def _body(self, template_key: str, recipient: str | None, device_token: str | None,
              context: Mapping[str, JsonValue] | None, locale: str) -> bytes:
        if (recipient is None) == (device_token is None):
            raise InputError("Supply exactly one email recipient or device token.")
        if context is not None and not isinstance(context, Mapping):
            raise InputError("Runtime context must be a JSON object.")
        payload: dict[str, Any] = {"template_key": template_key, "locale": locale, "context": dict(context or {})}
        payload["recipient" if recipient is not None else "device_token"] = recipient if recipient is not None else device_token
        try:
            # Encode once. A caller mutating its context during retries cannot change this request.
            return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise InputError("Runtime context must contain finite JSON values.") from None

    def _headers(self, key: str | None, public: bool) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "voxriva-sdk/0.2.0"}
        if not public:
            headers["Authorization"] = "Bearer "+self._api_key
        if key:
            headers["Idempotency-Key"] = key
        return headers

    def _delay(self, attempt: int, response: httpx.Response | None = None) -> float | None:
        if attempt >= self._retry.max_attempts:
            return None
        requested = retry_after(response) if response is not None else None
        if requested is not None and requested > self._retry.max_delay:
            return None  # Do not shorten a server-requested wait to fit the local budget.
        jitter = random.uniform(0, min(self._retry.max_delay, self._retry.initial_delay * 2**(attempt-1)))
        return max(jitter, requested or 0)

    def _json(self, response: httpx.Response, key: str | None) -> dict[str, Any]:
        try:
            return obj(response.json())
        except (ValueError, TypeError, ProtocolError):
            raise ProtocolError("The API returned an invalid JSON response.", idempotency_key=key) from None

    def _parse(self, row: dict[str, Any], parser: Callable[[dict[str, Any]], T], key: str | None = None) -> T:
        try:
            return parser(row)
        except (ValueError, TypeError, KeyError, AttributeError, ProtocolError):
            raise ProtocolError("The API response does not match the delivery contract.", idempotency_key=key) from None

    def _accepted(self, row: dict[str, Any], key: str) -> Accepted:
        return self._parse(row, lambda value: parse_accepted(value, key, f'{self._root}/notifications/{UUID(value["id"])}'), key)

    def _notification(self, row: dict[str, Any]) -> Notification:
        return self._parse(row, lambda value: parse_notification(value, f'{self._root}/notifications/{UUID(value["id"])}'))

    def _liveness(self, row: dict[str, Any]) -> Liveness:
        if row.get("status") != "live":
            raise ProtocolError("Unexpected liveness response.")
        return Liveness("live")

    def _readiness(self, row: dict[str, Any]) -> Readiness:
        if row.get("status") not in {"ready", "unavailable"} or not isinstance(row.get("checks"), dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in row["checks"].items()):
            raise ProtocolError("Unexpected readiness response.")
        return Readiness("ready" if row["status"] == "ready" else "unavailable", dict(row["checks"]))


class Client(_Base):
    def __init__(self, base_url: str, api_key: str, *, timeout: float | httpx.Timeout = 10,
                 retry_policy: RetryPolicy = RetryPolicy(), http_client: httpx.Client | None = None) -> None:
        super().__init__(base_url, api_key, timeout=timeout, retry_policy=retry_policy)
        self._owned = http_client is None
        self._http = http_client if http_client is not None else httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False)

    def close(self) -> None:
        if self._owned:
            self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _request(self, method: str, path: str, *, body: bytes | None = None, key: str | None = None,
                 public: bool = False, allow_unavailable: bool = False) -> dict[str, Any]:
        headers = self._headers(key, public)
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(1, self._retry.max_attempts+1):
            try:
                response = self._http.request(method, self._root+path, headers=headers, content=body, timeout=self._timeout, follow_redirects=False)
            except httpx.TransportError:
                delay = self._delay(attempt)
                if delay is None:
                    raise TransportError(attempts=attempt, idempotency_key=key) from None
                time.sleep(delay)
                continue
            if response.is_success or allow_unavailable and response.status_code == 503:
                return self._json(response, key)
            delay = self._delay(attempt, response) if response.status_code in RETRY_STATUSES else None
            if delay is None:
                raise api_error(response, attempt, key)
            time.sleep(delay)
        raise AssertionError("Retry loop exhausted")

    def send(self, template_key: str, *, recipient: str | None = None, device_token: str | None = None,
             context: Mapping[str, JsonValue] | None = None, locale: str = "en", idempotency_key: str | None = None) -> Accepted:
        body, key = self._body(template_key, recipient, device_token, context, locale), self._key(idempotency_key)
        return self._accepted(self._request("POST", "/api/v1/notifications", body=body, key=key), key)

    def validate(self, template_key: str, *, recipient: str | None = None, device_token: str | None = None,
                 context: Mapping[str, JsonValue] | None = None, locale: str = "en") -> ValidationResult:
        body = self._body(template_key, recipient, device_token, context, locale)
        return self._parse(self._request("POST", "/api/v1/notifications/validate", body=body), parse_validation)

    def get_notification(self, notification_id: str | UUID) -> Notification:
        identifier = self.notification_url(notification_id).rsplit("/", 1)[1]
        return self._notification(self._request("GET", f"/api/v1/notifications/{identifier}"))

    def liveness(self) -> Liveness:
        return self._liveness(self._request("GET", "/health/live", public=True))

    def readiness(self) -> Readiness:
        return self._readiness(self._request("GET", "/health/ready", public=True, allow_unavailable=True))


class AsyncClient(_Base):
    def __init__(self, base_url: str, api_key: str, *, timeout: float | httpx.Timeout = 10,
                 retry_policy: RetryPolicy = RetryPolicy(), http_client: httpx.AsyncClient | None = None) -> None:
        super().__init__(base_url, api_key, timeout=timeout, retry_policy=retry_policy)
        self._owned = http_client is None
        self._http = http_client if http_client is not None else httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)

    async def aclose(self) -> None:
        if self._owned:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, *, body: bytes | None = None, key: str | None = None,
                       public: bool = False, allow_unavailable: bool = False) -> dict[str, Any]:
        headers = self._headers(key, public)
        if body is not None:
            headers["Content-Type"] = "application/json"
        for attempt in range(1, self._retry.max_attempts+1):
            try:
                response = await self._http.request(method, self._root+path, headers=headers, content=body, timeout=self._timeout, follow_redirects=False)
            except httpx.TransportError:
                delay = self._delay(attempt)
                if delay is None:
                    raise TransportError(attempts=attempt, idempotency_key=key) from None
                await asyncio.sleep(delay)
                continue
            if response.is_success or allow_unavailable and response.status_code == 503:
                return self._json(response, key)
            delay = self._delay(attempt, response) if response.status_code in RETRY_STATUSES else None
            if delay is None:
                raise api_error(response, attempt, key)
            await asyncio.sleep(delay)
        raise AssertionError("Retry loop exhausted")

    async def send(self, template_key: str, *, recipient: str | None = None, device_token: str | None = None,
                   context: Mapping[str, JsonValue] | None = None, locale: str = "en", idempotency_key: str | None = None) -> Accepted:
        body, key = self._body(template_key, recipient, device_token, context, locale), self._key(idempotency_key)
        return self._accepted(await self._request("POST", "/api/v1/notifications", body=body, key=key), key)

    async def validate(self, template_key: str, *, recipient: str | None = None, device_token: str | None = None,
                       context: Mapping[str, JsonValue] | None = None, locale: str = "en") -> ValidationResult:
        body = self._body(template_key, recipient, device_token, context, locale)
        return self._parse(await self._request("POST", "/api/v1/notifications/validate", body=body), parse_validation)

    async def get_notification(self, notification_id: str | UUID) -> Notification:
        identifier = self.notification_url(notification_id).rsplit("/", 1)[1]
        return self._notification(await self._request("GET", f"/api/v1/notifications/{identifier}"))

    async def liveness(self) -> Liveness:
        return self._liveness(await self._request("GET", "/health/live", public=True))

    async def readiness(self) -> Readiness:
        return self._readiness(await self._request("GET", "/health/ready", public=True, allow_unavailable=True))

import asyncio
import inspect
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from uuid import uuid4

import httpx
import pytest

from voxriva_sdk import (
    ApiError,
    AsyncClient,
    AuthenticationError,
    Client,
    ConflictError,
    InputError,
    NotificationStatus,
    ProtocolError,
    RateLimitError,
    RetryPolicy,
    TransportError,
    ValidationError,
)

TOKEN = "synthetic-private-api-key"
IDENTIFIER = str(uuid4())


def accepted(**changes):
    return {"id": IDENTIFIER, "status": "queued", "environment_id": str(uuid4()), "template_version_id": str(uuid4()), "provider_revision_id": str(uuid4()), "replayed": False, "status_url": f"/api/v1/notifications/{IDENTIFIER}", **changes}


def detail():
    now = "2026-11-25T00:00:00Z"
    return {**accepted(status="sent"), "project_id": str(uuid4()), "channel": "email", "locale": "en", "recipient_mask": "p***@***", "error_code": None, "error_message": None,
            "attempt_count": 1, "next_attempt_at": None, "expires_at": now, "replay_of_id": None, "payload_available": False, "created_at": now, "updated_at": now,
            "resolution": {"project_name": "Project", "environment_name": "dev", "template_name": "Welcome", "template_key": "welcome", "branch_name": "main", "template_version": 1, "resolved_locale": "en", "fallback_used": False, "provider_name": "Local SMTP", "provider_type": "smtp", "provider_revision": 1, "provider_scope": "project"},
            "attempts": [{"number": 1, "status": "sent", "error_code": None, "error_message": None, "retryable": False, "provider_message_id": "message-1", "started_at": now, "finished_at": now}], "provider_events": [], "new_optional_field": "ignored"}


@asynccontextmanager
async def client_for(handler, asynchronous, **kwargs):
    transport = httpx.MockTransport(handler)
    if asynchronous:
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as http:
            async with AsyncClient("https://voxriva.example.test/prefix", TOKEN, http_client=http, retry_policy=kwargs.pop("retry_policy", RetryPolicy(initial_delay=0)), **kwargs) as client:
                yield client
            assert not http.is_closed
    else:
        with httpx.Client(transport=transport, follow_redirects=True) as http:
            with Client("https://voxriva.example.test/prefix", TOKEN, http_client=http, retry_policy=kwargs.pop("retry_policy", RetryPolicy(initial_delay=0)), **kwargs) as client:
                yield client
            assert not http.is_closed


async def invoke(client, method, *args, **kwargs):
    value = getattr(client, method)(*args, **kwargs)
    return await value if inspect.isawaitable(value) else value


@pytest.mark.parametrize("asynchronous", [False, True])
def test_unknown_http_outcome_and_500_reuse_one_key_and_immutable_body(asynchronous):
    calls, context = [], {"name": "Ada"}
    def handle(request):
        calls.append(request)
        assert request.url.path == "/prefix/api/v1/notifications"
        if len(calls) == 1:
            context["name"] = "MUTATED"
            raise httpx.ReadTimeout("RAW-PRIVATE-ERROR", request=request)
        return httpx.Response(500 if len(calls) == 2 else 202, json=accepted())
    async def check():
        async with client_for(handle, asynchronous) as client:
            result = await invoke(client, "send", "welcome", recipient="private@example.test", context=context)
            assert result.idempotency_key == calls[0].headers["Idempotency-Key"]
            assert result.dashboard_url == f"https://voxriva.example.test/prefix/notifications/{IDENTIFIER}"
    asyncio.run(check())
    assert len(calls) == 3
    assert len({request.headers["Idempotency-Key"] for request in calls}) == 1
    assert len({request.content for request in calls}) == 1
    assert json.loads(calls[-1].content)["context"]["name"] == "Ada"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("status,error_class", [(401, AuthenticationError), (409, ConflictError), (422, ValidationError)])
def test_permanent_typed_errors_are_not_retried_or_exposed_in_exception_message(asynchronous, status, error_class):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={"detail": {"message": "RAW-PRIVATE-ERROR", "issues": [{"path": ["context", "name"], "code": "required", "message": "Invalid or missing runtime value"}]}})
    async def check():
        async with client_for(handle, asynchronous) as client:
            with pytest.raises(error_class) as raised:
                await invoke(client, "send", "welcome", recipient="private@example.test", idempotency_key="business:1")
            assert raised.value.status_code == status and raised.value.attempts == 1 and raised.value.idempotency_key == "business:1"
            assert "RAW-PRIVATE" not in str(raised.value) and TOKEN not in str(raised.value)
            if status == 422:
                assert raised.value.issues[0].path == ("context", "name")
    asyncio.run(check())
    assert len(calls) == 1


@pytest.mark.parametrize("asynchronous", [False, True])
def test_retry_after_over_budget_is_not_shortened(asynchronous):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"}, json={"detail": "Busy"})
    async def check():
        async with client_for(handle, asynchronous, retry_policy=RetryPolicy(max_delay=30)) as client:
            with pytest.raises(RateLimitError) as raised:
                await invoke(client, "send", "welcome", recipient="private@example.test")
            assert raised.value.retry_after == 120 and raised.value.retryable
    asyncio.run(check())
    assert len(calls) == 1


@pytest.mark.parametrize("asynchronous", [False, True])
def test_retry_after_http_date_and_redirect_refusal(asynchronous, monkeypatch):
    calls, waits = [], []
    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, headers={"Retry-After": format_datetime(datetime.now(timezone.utc)+timedelta(seconds=5), usegmt=True)})
        return httpx.Response(307, headers={"Location": "https://untrusted.example.test"})
    async def pause(delay):
        waits.append(delay)
    monkeypatch.setattr("voxriva_sdk.client.time.sleep", waits.append)
    monkeypatch.setattr("voxriva_sdk.client.asyncio.sleep", pause)
    async def check():
        async with client_for(handle, asynchronous) as client:
            with pytest.raises(ApiError) as raised:
                await invoke(client, "send", "welcome", recipient="private@example.test")
            assert raised.value.status_code == 307
    asyncio.run(check())
    assert len(calls) == 2 and len(waits) == 1 and 3 <= waits[0] <= 5
    assert all(request.url.host == "voxriva.example.test" for request in calls)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_health_has_no_api_key_unavailable_is_a_report_and_history_is_typed(asynchronous):
    def handle(request):
        if request.url.path.endswith("/health/live"):
            assert "Authorization" not in request.headers
            return httpx.Response(200, json={"status": "live"})
        if request.url.path.endswith("/health/ready"):
            assert "Authorization" not in request.headers
            return httpx.Response(503, json={"status": "unavailable", "checks": {"redis": "unavailable"}})
        assert request.headers["Authorization"] == "Bearer "+TOKEN
        return httpx.Response(200, json=detail())
    async def check():
        async with client_for(handle, asynchronous) as client:
            assert (await invoke(client, "liveness")).status == "live"
            assert (await invoke(client, "readiness")).status == "unavailable"
            item = await invoke(client, "get_notification", IDENTIFIER)
            assert item.status is NotificationStatus.SENT and item.resolution.provider_name == "Local SMTP"
            assert item.attempts[0].finished_at.tzinfo is not None
    asyncio.run(check())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_exhausted_transport_and_malformed_acceptance_preserve_send_key(asynchronous):
    calls = []
    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("RAW-PRIVATE-ERROR", request=request)
    async def check():
        async with client_for(handle, asynchronous) as client:
            with pytest.raises(TransportError) as raised:
                await invoke(client, "send", "welcome", recipient="private@example.test")
            assert raised.value.attempts == 3 and raised.value.idempotency_key == calls[0].headers["Idempotency-Key"]
            assert "RAW-PRIVATE" not in str(raised.value)
        async with client_for(lambda request: httpx.Response(202, json={}), asynchronous) as client:
            with pytest.raises(ProtocolError) as raised:
                await invoke(client, "send", "welcome", recipient="private@example.test", idempotency_key="keep-after-bad-response")
            assert raised.value.idempotency_key == "keep-after-bad-response"
    asyncio.run(check())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_validation_is_read_only_and_push_target_does_not_become_recipient(asynchronous):
    def handle(request):
        assert request.url.path.endswith("/notifications/validate") and "Idempotency-Key" not in request.headers
        body = json.loads(request.content)
        assert body["device_token"] == "synthetic-device-token" and "recipient" not in body
        return httpx.Response(200, json={"valid": True, "project_id": str(uuid4()), "environment_id": str(uuid4()), "channel": "push", "locale": "uk", "resolved_locale": "en", "fallback_used": True, "template_version_id": str(uuid4()), "provider_revision_id": str(uuid4())})
    async def check():
        async with client_for(handle, asynchronous) as client:
            result = await invoke(client, "validate", "welcome", device_token="synthetic-device-token", locale="uk")
            assert result.valid and result.fallback_used and result.channel == "push"
            with pytest.raises(InputError):
                await invoke(client, "send", "welcome")
            with pytest.raises(InputError):
                await invoke(client, "send", "welcome", recipient="a@example.test", device_token="also-set")
            with pytest.raises(InputError):
                await invoke(client, "send", "welcome", recipient="a@example.test", context={"number": float("nan")})
    asyncio.run(check())


@pytest.mark.parametrize("asynchronous", [False, True])
def test_image_helper_preserves_bytes_in_runtime_context(asynchronous):
    import base64

    from voxriva_sdk import image_from_bytes
    raw = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
    value = image_from_bytes(raw, "image/png")
    def handle(request):
        image = json.loads(request.content)["context"]["banner"]
        assert image["media_type"] == "image/png"
        assert base64.b64decode(image["content_base64"]) == raw
        return httpx.Response(202, json=accepted())
    async def check():
        async with client_for(handle, asynchronous) as client:
            await invoke(client, "send", "welcome", recipient="fictional@example.test", context={"banner": value})
    asyncio.run(check())
    for data, mime in ((b"", "image/png"), (b"x" * 262145, "image/png"), (b"<svg/>", "image/svg+xml")):
        with pytest.raises(InputError):
            image_from_bytes(data, mime)

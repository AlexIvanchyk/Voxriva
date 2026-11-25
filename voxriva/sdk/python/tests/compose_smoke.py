"""Run only against the isolated test stack. Receives its short-lived key via stdin."""
import asyncio
import json
import sys
import time

from voxriva_sdk import AsyncClient, Client, NotificationStatus, ValidationError

settings = json.load(sys.stdin)
base, key, template = settings["base_url"], settings["key"], settings["template_key"]
request = {"recipient": "sdk.synthetic@example.test", "context": {"name": "SDK Runtime"}}
with Client(base, key, timeout=5) as client:
    assert client.liveness().status == "live"
    assert client.readiness().status == "ready"
    validation = client.validate(template, **request)
    assert str(validation.environment_id) == settings["environment_id"]
    try:
        client.validate(template, recipient=request["recipient"], context={})
        raise AssertionError("Invalid runtime input was accepted")
    except ValidationError as error:
        assert error.status_code == 422 and error.issues
    sync = client.send(template, **request, idempotency_key="sdk-sync-once")
    deadline = time.monotonic()+25
    while True:
        delivery = client.get_notification(sync.id)
        if delivery.status is NotificationStatus.SENT:
            break
        assert delivery.status in {NotificationStatus.QUEUED, NotificationStatus.PROCESSING, NotificationStatus.RETRYING}
        assert time.monotonic() < deadline
        time.sleep(0.25)
    assert str(delivery.template_version_id) == settings["template_version_id"] and len(delivery.attempts) == 1
    assert delivery.resolution.provider_type == "smtp"


async def check():
    async with AsyncClient(base, key, timeout=5) as client:
        validation = await client.validate(template, **request)
        assert validation.valid
        original = await client.send(template, **request, idempotency_key="sdk-sync-once")
        assert original.id == sync.id and original.replayed
        accepted = await client.send(template, **request, idempotency_key="sdk-async-once")
        assert accepted.id != sync.id
        deadline = time.monotonic()+25
        while True:
            detail = await client.get_notification(accepted.id)
            if detail.status is NotificationStatus.SENT:
                break
            assert detail.status in {NotificationStatus.QUEUED, NotificationStatus.PROCESSING, NotificationStatus.RETRYING}
            assert time.monotonic() < deadline
            await asyncio.sleep(0.25)
        assert len(detail.attempts) == 1 and detail.dashboard_url == accepted.dashboard_url
        return accepted


async_result = asyncio.run(check())
# IDs and statuses only. Never print request targets, runtime values or credentials.
print(json.dumps({"sync_id": str(sync.id), "async_id": str(async_result.id), "dashboard_url": async_result.dashboard_url, "status": "sent"}))

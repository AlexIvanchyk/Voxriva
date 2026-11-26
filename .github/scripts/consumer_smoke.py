#!/usr/bin/env python3
"""Exercise the installed PyPI SDK against the downloaded operator distribution."""
import asyncio
import importlib.metadata
import json
import sys
import time
from pathlib import Path

from voxriva_sdk import AsyncClient, Client, NotificationStatus

operator, version, evidence_path = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
assert importlib.metadata.version("voxriva-sdk") == version
assert "site-packages" in str(Path(__import__("voxriva_sdk").__file__).resolve())
sys.path.insert(0, str(operator / "scripts/example"))
from seed import API, FIXTURE, verify_receipt  # noqa: E402

state = json.loads((operator / "output/example/published/state.json").read_text())
arguments = {key: FIXTURE[key] for key in ("recipient", "locale", "context")}
base, key, template = state["base_url"], state["delivery_key"], FIXTURE["template_key"]
headers = {"Authorization": "Bearer " + key}


def receipt(identifier):
    raw = API(base).call("GET", "/notifications/" + str(identifier), headers=headers)
    fresh = {k: v for k, v in state.items() if k != "mailpit_id"}
    result = verify_receipt(fresh, raw)
    assert result["status"] == "sent" and result["image_bytes_match"]
    return result


with Client(base, key, timeout=10) as client:
    assert client.liveness().status == "live" and client.readiness().status == "ready"
    checked = client.validate(template, **arguments)
    assert str(checked.provider_revision_id) == state["provider_revision_id"]
    accepted = client.send(template, **arguments, idempotency_key="published-sdk-sync")
    deadline = time.monotonic() + 90
    while client.get_notification(accepted.id).status is not NotificationStatus.SENT:
        assert time.monotonic() < deadline, "Sync SDK notification did not reach Sent"
        time.sleep(0.5)
sync_receipt = receipt(accepted.id)


async def check_async():
    async with AsyncClient(base, key, timeout=10) as client:
        replay = await client.send(template, **arguments, idempotency_key="published-sdk-sync")
        assert replay.replayed and replay.id == accepted.id
        result = await client.send(template, **arguments, idempotency_key="published-sdk-async")
        deadline = time.monotonic() + 90
        while (await client.get_notification(result.id)).status is not NotificationStatus.SENT:
            assert time.monotonic() < deadline, "Async SDK notification did not reach Sent"
            await asyncio.sleep(0.5)
        return result


async_result = asyncio.run(check_async())
async_receipt = receipt(async_result.id)
assert async_receipt["mailpit_receipts"] == 3  # launcher + sync + async; replay adds nothing
evidence = {
    "version": version, "distribution": "PyPI", "sync": sync_receipt,
    "async": async_receipt, "idempotent_replay": True, "source_checkout": False,
}
evidence_path.write_text(json.dumps(evidence, indent=2) + "\n")
print("Installed PyPI SDK: sync/async SMTP receipts, inline images and idempotent replay verified.")

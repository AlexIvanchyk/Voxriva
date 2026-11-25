"""Invoked by the isolated Playwright image delivery E2E; credentials arrive on stdin."""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from voxriva_sdk import Client, image_from_bytes

settings = json.load(sys.stdin)
with Client(settings["base_url"], settings["key"]) as client:
    client.validate(settings["template_key"], recipient="image.default@example.test", context={})
    default = client.send(settings["template_key"], recipient="image.default@example.test", context={}, idempotency_key="image-default-v1")
    context = {"banner": image_from_bytes(base64.b64decode(settings["override"]), "image/png")}
    override = client.send(settings["template_key"], recipient="image.override@example.test", context=context, idempotency_key="image-override-v1")
    print(json.dumps({"default": str(default.id), "override": str(override.id)}))

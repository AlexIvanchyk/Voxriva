"""Generate the delivery-only MVP contract. Review changes to the checked-in snapshot."""

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.main import create_app

OPERATIONS = {
    "/health/live": ["get"],
    "/health/ready": ["get"],
    "/api/v1/notifications": ["post"],
    "/api/v1/notifications/validate": ["post"],
    "/api/v1/notifications/{notification_id}": ["get"],
}


def contract() -> dict[str, Any]:
    schema = create_app().openapi()
    schema["paths"] = {
        path: {verb: schema["paths"][path][verb] for verb in verbs}
        for path, verbs in OPERATIONS.items()
    }
    schema["info"] = {"title": "Voxriva delivery API", "version": "1.0.0"}
    components = schema["components"]["schemas"]
    required: set[str] = set()

    def refs(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/schemas/"):
                name = reference.rsplit("/", 1)[1]
                if name not in required:
                    required.add(name)
                    refs(components[name])
            for child in value.values():
                refs(child)
        elif isinstance(value, list):
            for child in value:
                refs(child)

    refs(schema["paths"])
    schema["components"]["schemas"] = {
        name: components[name] for name in sorted(required)
    }
    return schema


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the frozen contract differs; never write it",
    )
    arguments = parser.parse_args()
    destination = (
        Path(__file__).resolve().parents[1] / "contracts/delivery-v1.openapi.json"
    )
    content = json.dumps(contract(), indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if destination.read_text() != content:
            raise SystemExit(
                "Delivery contract changed. Review compatibility before explicitly freezing a new snapshot."
            )
        print("Frozen delivery contract matches the application.")
    else:
        destination.write_text(content)

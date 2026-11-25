import inspect
import re
from importlib.metadata import entry_points
from typing import Any

from backend.app.features.providers.adapters.fcm import FCMProvider
from backend.app.features.providers.adapters.ses import SESProvider
from backend.app.features.providers.adapters.smtp import SMTPProvider
from backend.app.shared.provider_contract import BaseProvider

ENTRY_POINT_GROUP = "notification_platform.providers"


def discover() -> dict[str, type[BaseProvider]]:
    candidates = [
        SMTPProvider,
        SESProvider,
        FCMProvider,
        *(entry.load() for entry in entry_points(group=ENTRY_POINT_GROUP)),
    ]
    result: dict[str, type[BaseProvider]] = {}
    for adapter in candidates:
        if (
            not isinstance(adapter, type)
            or not issubclass(adapter, BaseProvider)
            or inspect.isabstract(adapter)
        ):
            raise RuntimeError(
                "Installed provider does not implement the provider interface"
            )
        if (
            adapter.interface_version != 1
            or not re.fullmatch("[a-z][a-z0-9_-]{0,63}", adapter.key)
            or adapter.channel not in {"email", "push"}
        ):
            raise RuntimeError(
                "Installed provider has unsupported metadata or interface version"
            )
        if adapter.key in result:
            raise RuntimeError("Duplicate installed provider key")
        schema = config_schema(adapter)
        for name, field in schema.get("properties", {}).items():
            if name.startswith("_"):
                raise RuntimeError(
                    "Provider field names cannot use the reserved metadata prefix"
                )
            types = field.get("anyOf", [field])
            if any(
                part.get("type")
                not in {"string", "integer", "number", "boolean", "null"}
                for part in types
            ):
                raise RuntimeError("Provider configuration must use flat scalar fields")
        result[adapter.key] = adapter
    return result


def metadata(adapter: type[BaseProvider]) -> dict[str, Any]:
    return {
        "key": adapter.key,
        "name": adapter.name,
        "channel": adapter.channel,
        "interface_version": adapter.interface_version,
        "capabilities": adapter.capabilities.model_dump(),
        "schema": config_schema(adapter),
    }


def secret_fields(adapter: type[BaseProvider]) -> set[str]:
    return {
        name
        for name, field in config_schema(adapter).get("properties", {}).items()
        if field.get("writeOnly")
    }


def config_schema(adapter: type[BaseProvider]) -> dict[str, Any]:
    schema = adapter.config_model.model_json_schema()
    for field in schema.get("properties", {}).values():
        if any(part.get("writeOnly") for part in field.get("anyOf", [])):
            field["writeOnly"] = True
    return schema

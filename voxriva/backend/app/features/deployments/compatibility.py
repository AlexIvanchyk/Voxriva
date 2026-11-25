"""Conservative variable-contract comparison. Unknown changed constraints require acknowledgement."""

import json
from typing import Any

from pydantic import BaseModel

from backend.app.features.templates.rendering import DraftContent


class CompatibilityIssue(BaseModel):
    path: str
    code: str
    message: str


def schema_changes(
    before: DraftContent, after: DraftContent
) -> list[CompatibilityIssue]:
    issues: list[CompatibilityIssue] = []

    def add(path: str, code: str, message: str) -> None:
        issues.append(CompatibilityIssue(path=path or "$", code=code, message=message))

    def equal(a: Any, b: Any) -> bool:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def compare(old: Any, new: Any, path: str = "") -> None:
        if equal(old, new):
            return
        if not isinstance(old, dict) or not isinstance(new, dict):
            add(path, "schema_changed", "The variable constraint changed")
            return
        old_required, new_required = (
            set(old.get("required", [])),
            set(new.get("required", [])),
        )
        for name in sorted(new_required - old_required):
            if path or name not in after.runtime_defaults:
                add(
                    f"{path}.{name}".strip("."),
                    "required_added",
                    "A new required variable must be supplied",
                )
        old_props, new_props = (old.get("properties", {}), new.get("properties", {}))
        for name in sorted(set(old_props) - set(new_props)):
            add(
                f"{path}.{name}".strip("."),
                "property_removed",
                "A previously accepted variable was removed",
            )
        for name in sorted(set(old_props) & set(new_props)):
            compare(old_props[name], new_props[name], f"{path}.{name}".strip("."))
        types_old = set(
            old["type"] if isinstance(old.get("type"), list) else [old.get("type")]
        )
        types_new = set(
            new["type"] if isinstance(new.get("type"), list) else [new.get("type")]
        )
        if "number" in types_new:
            types_new.add("integer")
        if new.get("type") is not None and (
            old.get("type") is None or not types_old <= types_new
        ):
            add(
                path,
                "type_narrowed",
                "The accepted variable type was narrowed or changed",
            )
        for key in [
            "minimum",
            "exclusiveMinimum",
            "minLength",
            "minItems",
            "minProperties",
        ]:
            if key in new and (key not in old or new[key] > old[key]):
                add(path, "constraint_tightened", f"{key} became stricter")
        for key in [
            "maximum",
            "exclusiveMaximum",
            "maxLength",
            "maxItems",
            "maxProperties",
        ]:
            if key in new and (key not in old or new[key] < old[key]):
                add(path, "constraint_tightened", f"{key} became stricter")
        if (
            new.get("additionalProperties") is False
            and old.get("additionalProperties") is not False
        ):
            add(
                path,
                "additional_properties_rejected",
                "Extra variables are no longer accepted",
            )
        if isinstance(new.get("additionalProperties"), dict) and (
            not equal(old.get("additionalProperties"), new["additionalProperties"])
        ):
            add(path, "constraint_changed", "Extra variable constraints changed")
        if "enum" in new and (
            "enum" not in old
            or any(
                not any(equal(value, candidate) for candidate in new["enum"])
                for value in old["enum"]
            )
        ):
            add(path, "enum_narrowed", "The allowed values were narrowed")
        ignored = {
            "$schema",
            "$id",
            "$comment",
            "title",
            "description",
            "examples",
            "default",
            "properties",
            "required",
            "type",
            "additionalProperties",
            "enum",
            "minimum",
            "exclusiveMinimum",
            "minLength",
            "minItems",
            "minProperties",
            "maximum",
            "exclusiveMaximum",
            "maxLength",
            "maxItems",
            "maxProperties",
        }
        for key in sorted((set(old) | set(new)) - ignored):
            if not equal(old.get(key), new.get(key)):
                add(
                    path,
                    "constraint_changed",
                    f"{key} changed; compatibility needs review",
                )

    compare(before.variable_schema, after.variable_schema)
    required = before.variable_schema.get("required", [])
    if isinstance(required, list):
        for name in before.runtime_defaults.keys() - after.runtime_defaults.keys():
            if name in required:
                add(
                    name,
                    "runtime_default_removed",
                    "A required variable no longer has a runtime default",
                )
    return issues

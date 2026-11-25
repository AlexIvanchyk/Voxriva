"""Bounded best-effort examples. Never return an example that fails the contract."""

import math
from typing import Any

from backend.app.features.templates.formats import FORMAT_METADATA, variable_validator


def example_value(
    schema: Any, path: list[str | int] | None = None, depth: int = 0
) -> Any:
    path = path or []
    if depth > 20:
        raise ValueError("Example nesting exceeds 20 levels")
    if schema is False:
        raise ValueError(f"{path}: schema allows no values")
    if schema is True:
        return None
    validator = variable_validator(schema)
    candidates = [schema["const"]] if "const" in schema else []
    candidates += schema.get("enum", []) + schema.get("examples", [])
    for candidate in candidates:
        if validator.is_valid(candidate):
            return candidate
    for branch in schema.get("oneOf", []) + schema.get("anyOf", []):
        try:
            candidate = example_value(branch, path, depth + 1)
            if validator.is_valid(candidate):
                return candidate
        except ValueError:
            pass
    if schema.get("x-voxriva-image") == 1:
        from backend.app.features.templates.images import synthetic_image

        candidate = synthetic_image().model_dump()
        if validator.is_valid(candidate):
            return candidate
        raise ValueError("Image constraints require a supplied test image")
    kind = schema.get("type", "string")
    if kind == "object":
        fields = schema.get("properties", {})
        required = schema.get("required", [])
        # Include optional fields where possible, but don't make impossible optional fields fatal.
        values = {}
        for key, field in fields.items():
            try:
                values[key] = example_value(field, [*path, key], depth + 1)
            except ValueError:
                if key in required:
                    raise
        candidates += [
            values,
            {key: value for key, value in values.items() if key in required},
        ]
    elif kind == "array":
        size = schema.get("minItems", min(1, schema.get("maxItems", 1)))
        if size > 100:
            raise ValueError(
                f"{path}: supply test data manually for lists over 100 items"
            )
        items = schema.get("items", {})
        prefix = schema.get("prefixItems", [])
        candidates += [
            [
                example_value(
                    prefix[index] if index < len(prefix) else items,
                    [*path, index],
                    depth + 1,
                )
                for index in range(size)
            ]
        ]
    elif kind in ("number", "integer"):
        step = schema.get("multipleOf", 1)
        lower = schema.get("minimum", schema.get("exclusiveMinimum", 0))
        if "exclusiveMinimum" in schema:
            lower = max(lower, schema["exclusiveMinimum"] + step)
        start = math.ceil(lower / step) * step
        candidates += [
            start,
            math.floor(schema.get("maximum", 1) / step) * step,
            schema.get("maximum", 1),
            0,
            1,
            -1,
        ]
    elif kind == "boolean":
        candidates += [True, False]
    elif kind == "null":
        candidates += [None]
    else:
        metadata = FORMAT_METADATA.get(schema.get("format", ""))
        if metadata:
            candidates.append(metadata["example"])
        size = schema.get("minLength", min(7, schema.get("maxLength", 7)))
        if size > 10000:
            raise ValueError(
                f"{path}: supply test data manually for strings over 10000 characters"
            )
        candidates += [
            "Example"[:size].ljust(size, "x"),
            "x" * size,
            "A" * size,
            "0" * size,
            "",
            "test",
            "ABC",
            "123",
        ]
    for candidate in candidates:
        if validator.is_valid(candidate):
            return candidate
    raise ValueError(
        f"{'.'.join(map(str, path)) or 'context'}: cannot generate an example satisfying these rules. Add a valid schema examples value or supply test data manually."
    )

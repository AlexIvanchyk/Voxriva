"""Bounded editor diagnostics and conservative draft-only Jinja renaming."""

import asyncio
import copy
import json
import re
import sys
from typing import Any


def sources(channel: str, draft: dict[str, Any]) -> dict[str, str]:
    result = {
        key: str(draft.get(key, ""))
        for key in (
            ["subject", "html", "text"] if channel == "email" else ["title", "body"]
        )
    }
    if channel == "push":
        result.update(
            {"data." + key: value for key, value in draft.get("data", {}).items()}
        )
    return result


def diagnostics(channel: str, draft: dict[str, Any]) -> list[dict[str, Any]]:
    from jinja2 import Environment, TemplateSyntaxError, meta, nodes
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    from backend.app.features.templates.formats import CHECKER, PHONE_VERSION

    environment = Environment(keep_trailing_newline=True)
    environment.globals.clear()
    schema = draft.get("variable_schema", {})
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        return [
            {
                "severity": "error",
                "code": "schema",
                "field": "variable_schema",
                "line": 1,
                "message": error.message[:250],
            }
        ]
    declared = set(schema.get("properties", {})) | set(
        draft.get("runtime_defaults", {})
    )
    used: set[str] = set()
    result: list[dict[str, Any]] = []

    def walk(value: Any, path: list[str | int], depth: int = 0) -> None:
        if depth > 20:
            return
        if isinstance(value, dict):
            if "format" in value and value["format"] not in {
                *CHECKER.checkers,
                "phone",
            }:
                result.append(
                    {
                        "severity": "error",
                        "code": "unknown_format",
                        "field": "variable_schema",
                        "line": 1,
                        "path": path + ["format"],
                        "message": "Unsupported format. Choose a supported validation format or remove it.",
                    }
                )
            if value.get("format") == "phone" and (
                type(value.get(PHONE_VERSION)) is not int
                or value.get(PHONE_VERSION) != 1
            ):
                result.append(
                    {
                        "severity": "error",
                        "code": "phone_version",
                        "field": "variable_schema",
                        "line": 1,
                        "path": path + [PHONE_VERSION],
                        "message": f"Phone validation requires {PHONE_VERSION}: 1. Select Phone in Variables or explicitly opt in using Advanced JSON.",
                    }
                )
            for key in ("properties", "patternProperties", "$defs", "dependentSchemas"):
                children = value.get(key)
                if isinstance(children, dict):
                    for name, child in children.items():
                        walk(child, path + [key, name], depth + 1)
            for key in (
                "items",
                "additionalProperties",
                "unevaluatedProperties",
                "unevaluatedItems",
                "contains",
                "propertyNames",
                "not",
                "if",
                "then",
                "else",
            ):
                if key in value:
                    walk(value[key], path + [key], depth + 1)
            for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
                children = value.get(key)
                if isinstance(children, list):
                    for index, child in enumerate(children):
                        walk(child, path + [key, index], depth + 1)

    walk(schema, ["variable_schema"])
    for field, source in sources(channel, draft).items():
        try:
            tree = environment.parse(source)
            globals_used = meta.find_undeclared_variables(tree)
            used.update(globals_used)
            for name in sorted(globals_used - declared):
                line = next(
                    (
                        node.lineno
                        for node in tree.find_all(nodes.Name)
                        if node.name == name
                    ),
                    1,
                )
                result.append(
                    {
                        "severity": "warning",
                        "code": "undeclared_variable",
                        "field": field,
                        "line": line,
                        "name": name,
                        "message": f"{name} is used here but is not declared in Variables or runtime defaults.",
                    }
                )
        except TemplateSyntaxError as error:
            result.append(
                {
                    "severity": "error",
                    "code": "syntax",
                    "field": field,
                    "line": error.lineno,
                    "message": str(error.message)[:250],
                }
            )
    for name in sorted(set(schema.get("properties", {})) - used):
        result.append(
            {
                "severity": "warning",
                "code": "unused_variable",
                "field": "variable_schema",
                "line": 1,
                "name": name,
                "message": f"{name} is declared but not used in this draft's content.",
            }
        )
    return result[:100]


def rename_source(source: str, old: str, new: str) -> tuple[str, int]:
    from jinja2 import Environment, meta, nodes

    environment = Environment(keep_trailing_newline=True)
    environment.globals.clear()
    tree = environment.parse(source)
    if any(
        node.name == old and node.ctx != "load" for node in tree.find_all(nodes.Name)
    ) or any(node.name == old for node in tree.find_all(nodes.Macro)):
        raise ValueError(
            "This variable is also used as a local template binding. Rename those references manually to avoid changing their meaning."
        )
    if old not in meta.find_undeclared_variables(tree):
        return (source, 0)
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    positions = []
    raw_index = 0
    for character in normalized:
        positions.append(raw_index)
        raw_index += (
            2
            if source[raw_index : raw_index + 2] == "\r\n" and character == "\n"
            else 1
        )
    positions.append(len(source))
    tokens = list(environment.lex(normalized))
    cursor, changes = (0, [])
    meaningful = [
        (index, token) for index, token in enumerate(tokens) if token[1] != "whitespace"
    ]
    neighbors = {index: offset for offset, (index, _) in enumerate(meaningful)}
    for index, (_, kind, value) in enumerate(tokens):
        start = normalized.find(value, cursor)
        if start < 0:
            raise ValueError(
                "The source cannot be renamed losslessly. Update its references manually."
            )
        cursor = start + len(value)
        if kind != "name" or value != old:
            continue
        offset = neighbors[index]
        previous = meaningful[offset - 1][1][2] if offset else ""
        following = meaningful[offset + 1][1][2] if offset + 1 < len(meaningful) else ""
        if (
            previous in {".", "|", "is", "filter"}
            or (
                previous == "not"
                and offset > 1
                and (meaningful[offset - 2][1][2] == "is")
            )
            or following == "="
        ):
            continue
        changes.append((positions[start], positions[cursor]))
    for start, end in reversed(changes):
        source = source[:start] + new + source[end:]
    return (source, len(changes))


def rename_draft(
    channel: str, draft: dict[str, Any], old: str, new: str
) -> dict[str, Any]:
    keywords = {
        "if",
        "else",
        "elif",
        "endif",
        "for",
        "in",
        "endfor",
        "set",
        "endset",
        "macro",
        "endmacro",
        "block",
        "endblock",
        "extends",
        "include",
        "import",
        "from",
        "as",
        "with",
        "endwith",
        "without",
        "context",
        "filter",
        "endfilter",
        "recursive",
        "and",
        "or",
        "not",
        "is",
        "call",
        "endcall",
        "autoescape",
        "endautoescape",
        "raw",
        "endraw",
    }
    if old in keywords or new in keywords:
        raise ValueError(
            "Template keywords must be renamed manually in advanced source."
        )
    if not all(
        re.fullmatch("[A-Za-z][A-Za-z0-9_]*", value) for value in [old, new]
    ) or new in {
        "true",
        "false",
        "none",
        "True",
        "False",
        "None",
        "loop",
        "self",
        "super",
    }:
        raise ValueError("Use a non-reserved variable name beginning with a letter.")
    result = copy.deepcopy(draft)
    schema = result.get("variable_schema", {})
    properties = schema.get("properties", {})
    if old not in properties or new in properties or old == new:
        raise ValueError("Select an existing variable and a new unique name.")
    if any(
        new in result.get(key, {}) for key in ["runtime_defaults", "preview_context"]
    ) or any(new in value for value in result.get("scenarios", {}).values()):
        raise ValueError("The new name already exists in saved defaults or test data.")
    changes = []
    for field, source in sources(channel, result).items():
        updated, count = rename_source(source, old, new)
        if count:
            if field.startswith("data."):
                result["data"][field[5:]] = updated
            else:
                result[field] = updated
            changes.append({"field": field, "replacements": count})
    schema["properties"] = {
        new if key == old else key: value for key, value in properties.items()
    }
    if "required" in schema:
        schema["required"] = [
            new if value == old else value for value in schema["required"]
        ]
    if any(
        key in schema
        for key in [
            "dependentRequired",
            "dependencies",
            "dependentSchemas",
            "allOf",
            "anyOf",
            "oneOf",
            "if",
            "then",
            "else",
            "not",
            "patternProperties",
            "propertyNames",
            "const",
            "enum",
        ]
    ):
        raise ValueError(
            "This schema has variable dependencies. Rename it in advanced JSON to preserve its contract."
        )
    annotations = [
        entry for entry in schema.get("examples", []) if isinstance(entry, dict)
    ]
    if isinstance(schema.get("default"), dict):
        annotations.append(schema["default"])
    if any(new in entry for entry in annotations):
        raise ValueError("The new name already exists in schema examples or defaults.")
    for values in [
        *annotations,
        result.get("runtime_defaults", {}),
        result.get("preview_context", {}),
        *result.get("scenarios", {}).values(),
    ]:
        if old in values:
            values[new] = values.pop(old)
    return {"draft": result, "changes": changes}


async def rename_bounded(
    channel: str, draft: dict[str, Any], old: str, new: str
) -> dict[str, Any]:
    payload = json.dumps(
        {"channel": channel, "draft": draft, "old": old, "new": new}, ensure_ascii=False
    ).encode()
    if len(payload) > 6000000:
        raise ValueError("Draft exceeds the rename input limit")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "backend.app.features.templates.authoring",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(payload), timeout=3)
        if process.returncode != 0 or len(output) > 6000000:
            raise ValueError("Rename exceeded its resource limits")
        result: dict[str, Any] = json.loads(output)
        if result.get("error"):
            raise ValueError(result["error"])
        return result
    except TimeoutError:
        raise ValueError("Rename exceeded its time limit") from None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


if __name__ == "__main__":
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    try:
        payload = json.loads(sys.stdin.buffer.read(6000001))
        print(
            json.dumps(
                rename_draft(
                    payload["channel"], payload["draft"], payload["old"], payload["new"]
                ),
                ensure_ascii=False,
            )
        )
    except Exception as error:
        print(json.dumps({"error": str(error)[:300]}))

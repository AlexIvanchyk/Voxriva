"""Pure preview/delivery renderer. Untrusted work runs in a bounded child process."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    model_validator,
)

from backend.app.features.templates.images import ImageContent

DIALECT = "https://json-schema.org/draft/2020-12/schema"
MAX_INPUT = 3000000
MAX_OUTPUT = 200000


def empty_schema() -> dict[str, JsonValue]:
    return {
        "$schema": DIALECT,
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


class LayoutReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: UUID
    version_id: UUID | None = None

    @field_serializer("template_id", "version_id")
    def serialize_id(self, value: UUID | None) -> str | None:
        return str(value) if value else None


class DraftContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: int = Field(default=1, ge=1, le=1)
    layout: LayoutReference | None = None
    subject: str = Field(default="", max_length=20000)
    text: str = Field(default="", max_length=30000)
    html: str = Field(default="", max_length=30000)
    title: str = Field(default="", max_length=10000)
    body: str = Field(default="", max_length=20000)
    data: dict[str, str] = Field(default_factory=dict)
    images: dict[str, ImageContent] = Field(default_factory=dict, max_length=20)
    variable_schema: dict[str, JsonValue] = Field(default_factory=empty_schema)
    runtime_defaults: dict[str, JsonValue] = Field(default_factory=dict)
    preview_context: dict[str, JsonValue] = Field(default_factory=dict)
    scenarios: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def bounded(self) -> DraftContent:
        import re

        from backend.app.features.templates.images import (
            ImageContent,
            bounded_images,
            without_image_bytes,
        )

        for name, value in self.images.items():
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", name):
                raise ValueError("Invalid image name")
            ImageContent.model_validate(value)
        stored = self.model_dump(exclude_none=True)
        bounded_images(stored)
        if (
            len(
                json.dumps(
                    without_image_bytes(stored),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            > 100000
        ):
            raise ValueError("Draft excluding image bytes exceeds 100 KB")
        if len(self.scenarios) > 20 or any(
            not name.strip() or len(name) > 80 for name in self.scenarios
        ):
            raise ValueError(
                "Use at most 20 named scenarios, with names of 1–80 characters"
            )
        return self


class RenderIssue(BaseModel):
    path: list[str | int]
    code: str
    message: str


class RenderResult(BaseModel):
    rendered: dict[str, Any] | None = None
    errors: list[RenderIssue] = Field(default_factory=list)
    layout: dict[str, Any] | None = None
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


def failure(
    code: str, message: str, path: list[str | int] | None = None
) -> RenderResult:
    return RenderResult(
        errors=[RenderIssue(path=path or [], code=code, message=message)]
    )


def _render(
    channel: str,
    draft: DraftContent,
    context: dict[str, JsonValue],
    wrappers: dict[str, list[str]] | None = None,
) -> RenderResult:
    from jinja2 import StrictUndefined, TemplateError
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    from backend.app.features.templates.formats import (
        format_message,
        variable_validator,
    )

    schema = draft.variable_schema
    if schema.get("$schema", DIALECT) != DIALECT or schema.get("type") != "object":
        return failure(
            "schema", "Use a Draft 2020-12 object schema", ["variable_schema"]
        )

    def inspect(value: Any, depth: int = 0) -> None:
        if depth > 20:
            raise ValueError("JSON nesting exceeds 20 levels")
        if isinstance(value, dict):
            if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                raise ValueError("Schema references are unsupported; inline the schema")
            if "x-voxriva-image" in value and (
                value["x-voxriva-image"] != 1 or value.get("type") != "object"
            ):
                raise ValueError("Use x-voxriva-image: 1 on an object schema")
            for child in value.values():
                inspect(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                inspect(child, depth + 1)

    try:
        inspect(schema)
        Draft202012Validator.check_schema(schema)
    except (ValueError, SchemaError) as error:
        return failure("schema", str(error).split("\n")[0][:250], ["variable_schema"])
    effective = {**draft.runtime_defaults, **context}
    validator = variable_validator(schema)
    issues = []
    for issue in validator.iter_errors(effective):
        issue_path = ["context", *issue.absolute_path]
        if issue.validator == "required" and isinstance(issue.instance, dict):
            missing = next(
                (
                    name
                    for name in issue.validator_value
                    if name not in issue.instance
                    and issue.message == f"{name!r} is a required property"
                ),
                None,
            )
            if missing is not None:
                issue_path.append(missing)
        issues.append(
            RenderIssue(
                path=issue_path,
                code=str(issue.validator),
                message=(
                    format_message(str(issue.validator_value))
                    if issue.validator == "format"
                    else None
                )
                or f"Context violates {issue.validator}: {issue.message[:160]}",
            )
        )
        if len(issues) == 30:
            break
    if issues:
        return RenderResult(errors=issues)

    import re

    from backend.app.features.templates.images import (
        ImageContent,
        bounded_images,
        resolve_images,
    )

    images: dict[str, ImageContent] = {}
    try:
        bounded_images(
            {
                "context": effective,
                "images": {
                    name: value.model_dump() for name, value in draft.images.items()
                },
            }
        )
        effective = resolve_images(effective, schema, images)
        static_images = {
            name: ImageContent.model_validate(value)
            for name, value in draft.images.items()
        }
        if channel != "email" and (images or static_images):
            raise ValueError("Images are supported only for email")
    except ValueError:
        return failure(
            "image", "Invalid image content, schema or image limit", ["context"]
        )

    class Environment(ImmutableSandboxedEnvironment):
        intercepted_binops = frozenset({"*", "**"})

        def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
            return False

        def is_safe_callable(self, obj: Any) -> bool:
            return False

        def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
            from jinja2.exceptions import SecurityError

            raise SecurityError("Multiplication and exponentiation are disabled")

    env = Environment(undefined=StrictUndefined, autoescape=False)
    env.globals.clear()
    env.filters = {
        key: value
        for key, value in env.filters.items()
        if key
        in {
            "upper",
            "lower",
            "title",
            "capitalize",
            "trim",
            "default",
            "escape",
            "e",
            "length",
            "join",
            "replace",
            "tojson",
        }
    }
    total = 0

    def render(source: str, html: bool = False, keep_newline: bool = False) -> str:
        nonlocal total
        env.autoescape = html
        env.keep_trailing_newline = keep_newline
        chunks = []
        for chunk in env.from_string(source).generate(effective):
            total += len(chunk.encode())
            if total > MAX_OUTPUT:
                raise ValueError("Rendered output exceeds 200 KB")
            chunks.append(chunk)
        return "".join(chunks)

    def render_body(field: str) -> str:
        source = getattr(draft, field)
        fragments = (wrappers or {}).get(field)
        if fragments is None:
            return render(source, field == "html")
        return "".join(
            render(part, field == "html", keep_newline=True)
            for part in (fragments[0], source, fragments[1])
        )

    try:
        if channel == "email":
            result: dict[str, Any] = {
                "subject": render(draft.subject),
                "text": render_body("text"),
                "html": render_body("html"),
            }
        else:
            result = {
                "title": render(draft.title),
                "body": render(draft.body),
                "data": {key: render(value) for key, value in draft.data.items()},
            }
        if channel == "email":

            def static(match: Any) -> str:
                name = match.group(1)
                if name not in static_images:
                    raise ValueError("Unknown static image: " + name)
                image = static_images[name]
                images[image.cid] = image
                return "cid:" + image.cid

            result["html"] = re.sub(
                r"voxriva-image:([A-Za-z][A-Za-z0-9_-]{0,79})", static, result["html"]
            )
            if images:
                result["images"] = [
                    {"cid": cid, **image.model_dump()}
                    for cid, image in images.items()
                    if "cid:" + cid in result["html"]
                ]
        return RenderResult(rendered=result)
    except (
        TemplateError,
        ValueError,
        OverflowError,
        RecursionError,
        TypeError,
    ) as error:
        return failure("render", str(error)[:250])


async def render_message(
    channel: str,
    draft: DraftContent,
    context: dict[str, JsonValue],
    *,
    wrappers: dict[str, list[str]] | None = None,
    authoring: bool = False,
    generate_example: bool = False,
) -> RenderResult:
    """One pipeline for preview and future delivery; never substitutes preview fixtures."""
    payload = json.dumps(
        {
            "channel": channel,
            "draft": draft.model_dump(),
            "context": context,
            "wrappers": wrappers,
            "authoring": authoring,
            "generate_example": generate_example,
        },
        ensure_ascii=False,
    ).encode()
    if len(payload) > 2 * MAX_INPUT:
        return failure("limit", "Render input including image data exceeds 6 MB")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "backend.app.features.templates.rendering",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(payload), timeout=3)
        if process.returncode != 0:
            return failure("limit", "Rendering exceeded its resource limits")
        return RenderResult.model_validate_json(output)
    except TimeoutError:
        return failure("limit", "Rendering exceeded its 3 second time limit")
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def worker() -> None:
    if sys.platform == "linux":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    payload = json.loads(sys.stdin.buffer.read(2 * MAX_INPUT + 1))
    if payload.get("generate_example"):
        from backend.app.features.templates.examples import example_value

        draft = DraftContent.model_validate(payload["draft"])
        from backend.app.features.templates.authoring import diagnostics

        notes = diagnostics(
            payload["channel"], {"variable_schema": draft.variable_schema}
        )
        schema_errors = [
            RenderIssue(
                path=note.get("path", ["variable_schema"]),
                code=note["code"],
                message=note["message"],
            )
            for note in notes
            if note["severity"] == "error"
        ]
        if schema_errors:
            print(RenderResult(errors=schema_errors).model_dump_json())
            return
        # Validate schema and reference restrictions before attempting generation.
        checked = _render(payload["channel"], draft, {})
        if any(issue.code == "schema" for issue in checked.errors):
            print(checked.model_dump_json())
            return
        try:
            context = example_value(draft.variable_schema)
            from backend.app.features.templates.images import resolve_images

            # Reuse the semantic image pipeline too; never return placeholder bytes.
            resolve_images(context, draft.variable_schema, {})
            result = RenderResult(rendered={"context": context})
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            result = failure("example", str(error)[:500], ["variable_schema"])
        print(result.model_dump_json())
        return
    notes = []
    if payload.get("authoring"):
        from backend.app.features.templates.authoring import diagnostics

        sources = dict(payload["draft"])
        for field, parts in (payload.get("wrappers") or {}).items():
            sources[field] = "\n".join([parts[0], sources[field], parts[1]])
        notes = diagnostics(payload["channel"], sources)
    errors = [
        RenderIssue(
            path=note.get("path", [note["field"], note["line"]]),
            code=note["code"],
            message=note["message"],
        )
        for note in notes
        if note["severity"] == "error"
    ]
    result = (
        RenderResult(errors=errors)
        if errors
        else _render(
            payload["channel"],
            DraftContent.model_validate(payload["draft"]),
            payload["context"],
            payload.get("wrappers"),
        )
    )
    result.diagnostics = notes
    if (
        payload.get("authoring")
        and payload["channel"] == "push"
        and result.rendered
        and (len(json.dumps(result.rendered, ensure_ascii=False).encode()) > 4096)
    ):
        result.errors.append(
            RenderIssue(
                path=["body"],
                code="push_size",
                message="Rendered push content exceeds 4096 bytes before the device token and request envelope.",
            )
        )
    print(result.model_dump_json())


if __name__ == "__main__":
    worker()

"""Compose independent template sources without interpolating rendered data into Jinja."""

from html.parser import HTMLParser
from typing import Any, cast

from pydantic import ValidationError

from backend.app.features.templates.rendering import DIALECT, DraftContent
from backend.app.infrastructure.errors import ApplicationError

BODY_SLOT = "<!-- voxriva:body -->"


def validate_kind(channel: str, is_layout: bool, draft: DraftContent) -> None:
    if is_layout and channel != "email":
        raise ApplicationError(422, "Only email supports layouts")
    if draft.layout and (is_layout or channel != "email"):
        raise ApplicationError(422, "Only an email template can reference a layout")


class _SlotParser(HTMLParser):
    found = False

    def handle_comment(self, data: str) -> None:
        if data == " voxriva:body ":
            self.found = True


def layout_parts(layout: DraftContent) -> dict[str, list[str]]:
    parts = {}
    for field in ("html", "text"):
        source = getattr(layout, field)
        if source:
            if source.count(BODY_SLOT) != 1:
                raise ApplicationError(
                    422, f"Layout {field} requires exactly one {BODY_SLOT} body slot"
                )
            if field == "html":
                parser = _SlotParser()
                try:
                    parser.feed(source)
                    parser.close()
                except (ValueError, AssertionError) as error:
                    raise ApplicationError(
                        422, "Invalid layout HTML around the body slot"
                    ) from error
                if not parser.found:
                    raise ApplicationError(
                        422, "Place the HTML body slot in the document as a comment"
                    )
            parts[field] = source.split(BODY_SLOT)
    if not parts:
        raise ApplicationError(422, "Add HTML or plain text with a body slot")
    return parts


def contract(draft: DraftContent) -> tuple[dict[str, Any], list[str]]:
    schema = draft.variable_schema
    # Root constraints such as oneOf or patternProperties cannot be flattened
    # without changing which payloads they accept. Nested schemas stay intact.
    supported = {
        "$schema",
        "type",
        "properties",
        "required",
        "additionalProperties",
        "title",
        "description",
        "$comment",
        "examples",
        "default",
    }
    props, required = schema.get("properties", {}), schema.get("required", [])
    if (
        schema.keys() - supported
        or schema.get("type") != "object"
        or schema.get("$schema", DIALECT) != DIALECT
        or not isinstance(schema.get("additionalProperties", True), bool)
        or not isinstance(props, dict)
        or not isinstance(required, list)
        or not all(isinstance(key, str) and key in props for key in required)
        or len(required) != len(set(required))
    ):
        raise ApplicationError(
            422,
            "Layout composition requires named object properties and compatible root constraints",
        )
    return props, cast(list[str], required)


def compose(letter: DraftContent, layout: DraftContent) -> DraftContent:
    if layout.layout:
        raise ApplicationError(422, "Layouts cannot reference another layout")
    layout_props, layout_required = contract(layout)
    props, required = contract(letter)
    local = props.keys() | letter.runtime_defaults.keys() | letter.images.keys()
    inherited = (
        layout_props.keys() | layout.runtime_defaults.keys() | layout.images.keys()
    )
    overlap = local & inherited
    if overlap:
        raise ApplicationError(
            422, "Conflicting layout and template names: " + ", ".join(sorted(overlap))
        )
    schema = {
        **letter.variable_schema,
        "properties": {**layout_props, **props},
        "required": [*layout_required, *required],
        "additionalProperties": bool(
            layout.variable_schema.get("additionalProperties", True)
            and letter.variable_schema.get("additionalProperties", True)
        ),
    }
    for field in ("html", "text"):
        if (
            len(getattr(letter, field))
            + len(getattr(layout, field).replace(BODY_SLOT, ""))
            > 30000
        ):
            raise ApplicationError(422, f"Combined {field} exceeds 30000 characters")
    try:
        return DraftContent.model_validate(
            {
                **letter.model_dump(),
                "layout": None,
                "images": {**layout.images, **letter.images},
                "variable_schema": schema,
                "runtime_defaults": {
                    **layout.runtime_defaults,
                    **letter.runtime_defaults,
                },
                "scenarios": {},
                "preview_context": {},
            }
        )
    except ValidationError as error:
        raise ApplicationError(
            422, "Combined layout and template exceed the draft limits"
        ) from error

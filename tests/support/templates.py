"""Synthetic content factories and rendering assertion support."""

import asyncio

from backend.app.features.templates.rendering import (
    DIALECT,
    DraftContent,
    render_message,
)


def content(**changes):
    return DraftContent(
        subject="Hello {{ name }}",
        html="<h1>{{ name }}</h1>",
        text="Hi {{ name }}",
        variable_schema={
            "$schema": DIALECT,
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name"],
            "additionalProperties": False,
        },
        preview_context={"name": "Synthetic Example"},
        **changes,
    )


def render(draft, context=None, channel="email"):
    return asyncio.run(render_message(channel, draft, context or {}))

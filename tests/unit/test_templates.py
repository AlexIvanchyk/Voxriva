import asyncio

import pytest

from backend.app.features.templates.rendering import render_message
from tests.support.templates import content


def render(draft, context=None, channel="email"):
    return asyncio.run(render_message(channel, draft, context or {}))


def test_renderer_defaults_are_explicit_and_fixtures_never_fill_delivery_context():
    draft = content()
    assert render(draft).errors[0].code == "required"
    assert render(draft, {"name": "Example", "age": "wrong"}).errors[0].code == "type"
    assert render(draft, {"name": "<script>"}).rendered == {
        "subject": "Hello <script>",
        "text": "Hi <script>",
        "html": "<h1>&lt;script&gt;</h1>",
    }
    draft.runtime_defaults = {"name": "Default Example"}
    assert render(draft).rendered["subject"] == "Hello Default Example"
    assert render(draft, {"name": "Override"}).rendered["subject"] == "Hello Override"
    draft.variable_schema["properties"]["name"]["default"] = "Annotation only"
    draft.runtime_defaults = {}
    assert render(draft).errors[0].code == "required"


@pytest.mark.parametrize(
    "source",
    [
        "{{ missing }}",
        "{% if %}",
        "{{ name.__class__ }}",
        "{{ name.upper() }}",
        "{{ 'x' * 100000000 }}",
        "{% include 'secret' %}",
    ],
)
def test_renderer_rejects_undefined_syntax_attribute_calls_and_expansion(source):
    draft = content()
    draft.html = source
    assert render(draft, draft.preview_context).errors[0].code == "render"


def test_schema_format_refs_and_resource_limits():
    draft = content()
    draft.variable_schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "format": "email"}},
    }
    assert render(draft, {"name": "invalid"}).errors[0].code == "format"
    draft.variable_schema = {
        "type": "object",
        "properties": {"name": {"$ref": "https://example.test/schema"}},
    }
    assert render(draft).errors[0].code == "schema"
    draft.variable_schema = {
        "type": "object",
        "properties": {"name": {"type": "not-a-type"}},
    }
    assert render(draft).errors[0].code == "schema"
    draft.variable_schema = {"type": "object"}
    draft.html = (
        "{% for a in name %}{% for b in name %}{{ name }}{% endfor %}{% endfor %}"
    )
    result = render(draft, {"name": "x" * 1000})
    assert result.errors[0].code in {"render", "limit"}
    # A computation producing no output must also be interruptible.
    draft.html = "{% for a in name %}{% for b in name %}{% for c in name %}{% if false %}x{% endif %}{% endfor %}{% endfor %}{% endfor %}"
    assert render(draft, {"name": "x" * 2000}).errors[0].code == "limit"


def test_push_uses_the_same_context_contract():
    draft = content(title="Hi {{ name }}", body="Ready", data={"account": "{{ name }}"})
    assert render(draft, draft.preview_context, "push").rendered == {
        "title": "Hi Synthetic Example",
        "body": "Ready",
        "data": {"account": "Synthetic Example"},
    }

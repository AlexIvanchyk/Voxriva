import asyncio
import json
import subprocess
import sys

import pytest

from backend.app.features.templates.authoring import diagnostics
from backend.app.features.templates.examples import example_value
from backend.app.features.templates.formats import (
    FORMATS,
    PHONE_VERSION,
    variable_validator,
)
from backend.app.features.templates.rendering import DraftContent, render_message

PHONE = {"type": "string", "format": "phone", PHONE_VERSION: 1}


@pytest.mark.parametrize(
    "value",
    [
        "+12025550123",
        "+442083661177",
        "+380501234567",
        "+359888123456",
        "+4930123456",
        "+81312345678",
    ],
)
def test_international_phone_regions(value):
    assert variable_validator(PHONE).is_valid(value)


@pytest.mark.parametrize(
    "value",
    [
        "2025550123",
        "02083661177",
        "0888123456",
        "00359888123456",
        "+1 202 555 0123",
        "+1-202-555-0123",
        "+12025550123x2",
        " +12025550123",
        "+999123456789",
        "+12001230101",
        "+123",
        "+0123456789",
        "+1202555012345678",
        "",
        123,
        None,
    ],
)
def test_phone_invalid_and_no_silent_normalization(value):
    assert not variable_validator(PHONE).is_valid(value)


@pytest.mark.parametrize(
    "name,bad",
    [
        ("ipv4", "256.1.2.3"),
        ("ipv6", "2001:::1"),
        ("hostname", "https://example.test/path"),
        ("duration", "30 minutes"),
        ("email", "invalid"),
        ("uri", "/relative"),
        ("date", "2026-02-30"),
        ("date-time", "2026-01-01T12:00:00"),
        ("uuid", "broken"),
    ],
)
def test_format_catalog_examples_and_invalid_values(name, bad):
    entry = next(item for item in FORMATS if item["value"] == name)
    validator = variable_validator({"type": "string", "format": name})
    assert validator.is_valid(entry["example"])
    assert not validator.is_valid(bad)


def test_catalog_has_no_frontend_drift():
    subprocess.run(
        [sys.executable, "scripts/generate-variable-formats.py", "--check"],
        check=True,
        env={"PYTHONPATH": "."},
    )


@pytest.mark.parametrize(
    "name,valid,invalid",
    [
        ("uri", "https://example.test/a?b=c#d", "/relative"),
        ("uri", "mailto:alex@example.test", "https://example.test/has space"),
        ("uri", "urn:example:synthetic", "https://[broken]/"),
        ("uri-reference", "../relative?query#fragment", "has space"),
        ("iri", "https://例え.テスト/пошта", "/relative"),
        ("iri-reference", "../пошта#лист", "has space"),
    ],
)
def test_uri_and_iri_formats_remain_enforced_in_preview_and_runtime(name, valid, invalid):
    # jsonschema silently accepts unknown formats when optional checkers are
    # missing. Exercise both acceptance and rejection after dependency changes.
    from backend.app.features.templates.formats import CHECKER

    assert name in CHECKER.checkers
    schema = {
        "type": "object",
        "properties": {"link": {"type": "string", "format": name}},
        "required": ["link"],
    }
    for authoring in [False, True]:
        draft = DraftContent(subject="{{ link }}", variable_schema=schema)
        accepted = asyncio.run(
            render_message("email", draft, {"link": valid}, authoring=authoring)
        )
        assert accepted.errors == []
        assert accepted.rendered["subject"] == valid
        rejected = asyncio.run(
            render_message("email", draft, {"link": invalid}, authoring=authoring)
        )
        assert rejected.rendered is None
        assert rejected.errors[0].path == ["context", "link"]
        assert rejected.errors[0].code == "format"


def test_phone_opt_in_preserves_legacy_runtime_and_requires_explicit_authoring():
    schema = {
        "type": "object",
        "properties": {"number": {"type": "string", "format": "phone"}},
    }
    assert variable_validator(schema).is_valid({"number": "legacy local value"})
    notes = diagnostics("email", {"variable_schema": schema})
    assert notes[0]["code"] == "phone_version"
    assert notes[0]["path"] == [
        "variable_schema",
        "properties",
        "number",
        PHONE_VERSION,
    ]
    # Annotation values do not themselves define schemas.
    schema["examples"] = [{"format": "phone"}]
    schema["properties"]["number"][PHONE_VERSION] = 1
    assert not any(
        note["severity"] == "error"
        for note in diagnostics("email", {"variable_schema": schema})
    )
    assert not variable_validator(schema).is_valid({"number": "legacy local value"})


def test_nested_phone_path_and_preview_runtime_parity_and_roundtrip():
    schema = {
        "type": "object",
        "properties": {
            "contacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"phone": PHONE},
                    "required": ["phone"],
                },
            }
        },
        "required": ["contacts"],
    }
    draft = DraftContent(subject="{{ contacts[0].phone }}", variable_schema=schema)
    for context, valid in [
        ({"contacts": [{"phone": "+442083661177"}]}, True),
        ({"contacts": [{"phone": "02083661177"}]}, False),
    ]:
        results = [
            asyncio.run(render_message("email", draft, context, authoring=mode))
            for mode in [False, True]
        ]
        assert results[0].errors == results[1].errors
        assert bool(results[0].rendered) is valid
        if valid:
            assert results[0].rendered["subject"] == context["contacts"][0]["phone"]
        else:
            assert results[0].errors[0].path == ["context", "contacts", 0, "phone"]
            assert "E.164" in results[0].errors[0].message
    assert (
        DraftContent.model_validate_json(draft.model_dump_json()).variable_schema
        == schema
    )
    assert json.loads(json.dumps(schema)) == schema


def test_examples_are_valid_for_nested_formats_and_constraints():
    fields = {
        entry["value"]: {
            "type": "string",
            "format": entry["value"],
            **({PHONE_VERSION: 1} if entry["value"] == "phone" else {}),
        }
        for entry in FORMATS
        if entry["value"]
    }
    fields.update(
        {
            "count": {
                "type": "integer",
                "exclusiveMinimum": 4,
                "maximum": 10,
                "multipleOf": 3,
            },
            "short": {"type": "string", "maxLength": 2},
            "pattern": {
                "type": "string",
                "pattern": "^[A-Z]{3}$",
                "examples": ["invalid", "ABC"],
            },
            "items": {"type": "array", "minItems": 2, "items": PHONE},
        }
    )
    schema = {"type": "object", "properties": fields, "required": list(fields)}
    example = example_value(schema)
    assert variable_validator(schema).is_valid(example)
    draft = DraftContent(variable_schema=schema)
    result = asyncio.run(render_message("email", draft, {}, generate_example=True))
    assert result.errors == []
    assert result.rendered["context"] == example
    assert draft.preview_context == {} and draft.runtime_defaults == {}


def test_unconstructable_examples_report_failure_instead_of_invalid_data():
    schema = {
        "type": "object",
        "properties": {"code": {"type": "string", "pattern": "^UNUSUAL42$"}},
        "required": ["code"],
    }
    result = asyncio.run(
        render_message(
            "email", DraftContent(variable_schema=schema), {}, generate_example=True
        )
    )
    assert result.rendered is None
    assert result.errors[0].code == "example"
    assert "code" in result.errors[0].message
    schema["properties"]["code"]["examples"] = ["UNUSUAL42"]
    assert example_value(schema) == {"code": "UNUSUAL42"}


def test_root_examples_are_filtered_before_incomplete_generation_and_legacy_is_opt_in():
    schema = {
        "type": "object",
        "properties": {"code": {"type": "string", "pattern": "^UNUSUAL42$"}},
        "required": ["code"],
        "examples": [{"code": "invalid"}, {"code": "UNUSUAL42"}],
    }
    assert example_value(schema) == {"code": "UNUSUAL42"}
    draft = DraftContent(
        variable_schema={
            "type": "object",
            "properties": {"phone": {"type": "string", "format": "phone"}},
        }
    )
    result = asyncio.run(render_message("email", draft, {}, generate_example=True))
    assert result.errors[0].code == "phone_version" and result.rendered is None


def test_runtime_hints_never_echo_values():
    from backend.app.features.templates.formats import (
        format_message,
        runtime_issue_message,
    )

    assert "E.164" in runtime_issue_message("format", format_message("phone"))
    assert (
        runtime_issue_message("format", "private supplied number +12025550123")
        == "Invalid or missing runtime value"
    )
    assert (
        runtime_issue_message("enum", "private allowed value")
        == "Invalid or missing runtime value"
    )

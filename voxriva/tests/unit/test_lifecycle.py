import pytest

from backend.app.features.templates.rendering import DraftContent
from tests.support.lifecycle import draft


@pytest.mark.parametrize(
    "old_schema,new_schema,breaking",
    [
        (
            {"type": "object", "properties": {}},
            {"type": "object", "properties": {"optional": {"type": "string"}}},
            False,
        ),
        (
            {"type": "object", "properties": {"n": {"type": "integer"}}},
            {"type": "object", "properties": {"n": {"type": "number"}}},
            False,
        ),
        (
            {"type": "object", "properties": {"n": {"type": "number"}}},
            {"type": "object", "properties": {"n": {"type": "integer"}}},
            True,
        ),
        (
            {"type": "object", "properties": {"x": {"enum": [True]}}},
            {"type": "object", "properties": {"x": {"enum": [1]}}},
            True,
        ),
        (
            {"type": "object", "properties": {"x": {"const": True}}},
            {"type": "object", "properties": {"x": {"const": 1}}},
            True,
        ),
        (
            {"type": "object", "description": "Old"},
            {"type": "object", "description": "New"},
            False,
        ),
        (
            {"type": "object", "properties": {"x": {"type": "string", "minLength": 1}}},
            {"type": "object", "properties": {"x": {"type": "string", "minLength": 4}}},
            True,
        ),
    ],
)
def test_contract_compatibility_rules(old_schema, new_schema, breaking):
    from backend.app.features.deployments.compatibility import schema_changes

    before = DraftContent(variable_schema=old_schema)
    after = DraftContent(variable_schema=new_schema)
    assert bool(schema_changes(before, after)) is breaking


def test_required_fields_with_explicit_defaults_preserve_the_client_contract():
    from backend.app.features.deployments.compatibility import schema_changes

    before = draft()
    after = draft()
    after.variable_schema["properties"]["code"] = {"type": "string"}
    after.variable_schema["required"].append("code")
    after.runtime_defaults = {"code": "SYNTHETIC"}
    assert schema_changes(before, after) == []
    after_without_default = after.model_copy(update={"runtime_defaults": {}})
    assert any(
        issue.code == "runtime_default_removed"
        for issue in schema_changes(after, after_without_default)
    )

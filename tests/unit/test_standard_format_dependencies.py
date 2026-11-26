"""The supported non-GPL jsonschema extra must retain standard format checks."""

from importlib import metadata

import pytest

from backend.app.features.templates.formats import CHECKER, variable_validator


def test_standard_formats_are_registered_without_the_gpl_iri_package():
    with pytest.raises(metadata.PackageNotFoundError):
        metadata.distribution("rfc3987")
    for name in [
        "uri", "uri-reference", "iri", "iri-reference", "email", "idn-email",
        "hostname", "idn-hostname", "date", "date-time", "time", "duration",
        "uuid", "ipv4", "ipv6", "json-pointer", "relative-json-pointer",
        "uri-template", "regex",
    ]:
        assert name in CHECKER.checkers, f"Missing standard format validator: {name}"


@pytest.mark.parametrize(
    "name,value,valid",
    [
        ("uri", "https://example.test/a?x=1#fragment", True),
        ("uri", "mailto:synthetic@example.test", True),
        ("uri", "/relative/path", False),
        ("uri", "https://example.test/простір", False),
        ("uri", "https://example.test/bad space", False),
        ("uri", "https://example.test/%ZZ", False),
        ("uri-reference", "../relative/path?x=1", True),
        ("uri-reference", "", True),
        ("uri-reference", "bad space", False),
        ("iri", "https://приклад.test/простір", True),
        ("iri", "https://例え.test/文書?名前=値", True),
        ("iri", "/простір", False),
        ("iri", "https://example.test/bad space", False),
        ("iri", "https://example.test/%ZZ", False),
        ("iri-reference", "../простір?ім’я=значення", True),
        ("iri-reference", "", True),
        ("iri-reference", "bad space", False),
        ("iri-reference", "https://example.test/%ZZ", False),
    ],
)
def test_uri_and_iri_vectors_keep_validation_enabled(name, value, valid):
    validator = variable_validator({"type": "string", "format": name})
    assert validator.is_valid(value) is valid


@pytest.mark.parametrize("name", ["uri", "uri-reference", "iri", "iri-reference"])
def test_format_checker_retains_jsonschema_non_string_semantics(name):
    assert CHECKER.conforms(42, name)
    assert CHECKER.conforms(None, name)

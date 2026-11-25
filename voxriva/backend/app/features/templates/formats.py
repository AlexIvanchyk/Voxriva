"""Format catalog and validators. UI metadata is generated from this module."""

import re
from typing import Any

import phonenumbers
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators

# Existing standard validators keep jsonschema's established semantics.
FORMATS = [
    {
        "value": "",
        "label": "Plain text",
        "description": "Text without a semantic format.",
        "example": "Example",
    },
    {
        "value": "email",
        "label": "Email address",
        "description": "Email address syntax; does not verify delivery or ownership.",
        "example": "alex@example.test",
    },
    {
        "value": "phone",
        "label": "Phone number (E.164)",
        "description": "International number: + and country code, digits only (up to 15). No spaces, extensions or national numbers. Region is never inferred; ownership is not verified.",
        "example": "+12025550123",
    },
    {
        "value": "uri",
        "label": "URL",
        "description": "Absolute URI, including its scheme.",
        "example": "https://example.test/welcome",
    },
    {
        "value": "date",
        "label": "Date",
        "description": "RFC 3339 full date: YYYY-MM-DD.",
        "example": "2026-01-01",
    },
    {
        "value": "date-time",
        "label": "Date and time",
        "description": "RFC 3339 date and time with a timezone.",
        "example": "2026-01-01T12:00:00Z",
    },
    {
        "value": "duration",
        "label": "Duration",
        "description": "ISO 8601 duration, for example PT30M (30 minutes).",
        "example": "PT30M",
    },
    {
        "value": "uuid",
        "label": "UUID",
        "description": "UUID in hyphenated form.",
        "example": "00000000-0000-4000-8000-000000000001",
    },
    {
        "value": "ipv4",
        "label": "IPv4 address",
        "description": "IPv4 address, without a port or network prefix.",
        "example": "192.0.2.1",
    },
    {
        "value": "ipv6",
        "label": "IPv6 address",
        "description": "IPv6 address, without brackets or network prefix.",
        "example": "2001:db8::1",
    },
    {
        "value": "hostname",
        "label": "Hostname",
        "description": "ASCII DNS hostname, without a scheme, port or path. Use punycode for international names.",
        "example": "mail.example.test",
    },
]
FORMAT_METADATA = {item["value"]: item for item in FORMATS}
PHONE_VERSION = "x-voxriva-phone-version"
CHECKER = FormatChecker()


def valid_phone(value: Any) -> bool:
    if not isinstance(value, str):
        return True  # JSON Schema type handles non-strings.
    if not re.fullmatch(r"\+[1-9][0-9]{1,14}", value):
        return False
    try:
        return phonenumbers.is_valid_number(phonenumbers.parse(value, None))
    except phonenumbers.NumberParseException:
        return False


def _format(validator: Any, name: str, instance: Any, schema: Any) -> Any:
    if name == "phone":
        # An explicit opt-in preserves previously published unknown-format behavior.
        if (
            type(schema.get(PHONE_VERSION)) is int
            and schema.get(PHONE_VERSION) == 1
            and not valid_phone(instance)
        ):
            yield ValidationError(
                "Enter a valid international phone number in E.164 form, e.g. +12025550123; use + and country code, digits only, without extensions."
            )
    else:
        yield from Draft202012Validator.VALIDATORS["format"](
            validator, name, instance, schema
        )


VariableValidator = validators.extend(Draft202012Validator, {"format": _format})  # type: ignore[no-untyped-call]


def variable_validator(schema: Any) -> Any:
    return VariableValidator(schema, format_checker=CHECKER)


def format_message(name: str) -> str | None:
    metadata = FORMAT_METADATA.get(name)
    if not metadata or not name:
        return None
    return f"Expected {metadata['label']}. {metadata['description']} Example: {metadata['example']}"


def runtime_issue_message(code: str, message: str) -> str:
    # Only return catalog-owned explanations; never echo runtime values or schemas.
    safe = {format_message(item["value"]) for item in FORMATS if item["value"]}
    return (
        message
        if code == "format" and message in safe
        else "Invalid or missing runtime value"
    )

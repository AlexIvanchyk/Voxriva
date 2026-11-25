# Variable formats and validation

Variables remain JSON Schema Draft 2020-12 types. Formats constrain strings; they do
not convert, trim, normalize, fetch URLs, send messages or verify ownership.

The visual editor offers plain text, email, absolute URI (URL), date, date-time,
UUID, **phone**, **IPv4**, **IPv6**, **hostname** and **duration**. Existing advanced
formats accepted by the installed jsonschema format checker remain supported.
Descriptions and fictional examples come from `backend/app/features/templates/formats.py`;
`scripts/generate-variable-formats.py` generates the frontend catalog. The architecture
check detects drift. New validators belong in this module, not in individual endpoints.
Existing standard format semantics continue to use the installed jsonschema checker.
In particular this release does not change the legacy advanced `time` behavior.

## Phone numbers

Select **Text → Phone number (E.164)**, including for text list items. Advanced JSON:

```json
{
  "type": "string",
  "format": "phone",
  "x-voxriva-phone-version": 1
}
```

Supply a `+`, country calling code and digits, with at most 15 digits total:
`+12025550123`. The pinned Python port of Google's libphonenumber (`phonenumbers`)
checks validity against country numbering-plan metadata, after checking E.164 syntax.
For example, international UK, Ukrainian and Bulgarian numbers are supported.
Spaces, punctuation, extensions, `00` prefixes and national numbers such as
`02083661177` are rejected. No default country is inferred from template language,
recipient, browser or account. National-format input is intentionally unsupported;
applications must explicitly collect a country and convert their input before
calling Voxriva. The value supplied to Voxriva is preserved exactly for rendering
and idempotency. This is numbering-plan validation, not proof that a number is
assigned, reachable, mobile, or owned by a recipient. It performs no OTP/SMS call.
Metadata updates can change which numbering ranges are valid; dependency upgrades
must rerun the format tests and review this behavior.

The version annotation is an explicit compatibility opt-in. Historical published
schemas containing unknown `format: "phone"` without the annotation retain their
previous runtime behavior (no phone check). Authoring/publication asks the author
to select Phone again or add the annotation explicitly. Opening or saving the
visual editor never silently adds it. Existing schemas, immutable published
versions and deployment pointers are not migrated or rewritten. Standard formats
newly exposed in the visual menu were already checked at runtime; their rules do
not change. Unknown formats remain publication errors.

## Additional standard formats

| Format | Example | Input rule |
| --- | --- | --- |
| `ipv4` | `192.0.2.1` | IPv4 address, no port or prefix |
| `ipv6` | `2001:db8::1` | IPv6 address, no brackets or network prefix |
| `hostname` | `mail.example.test` | ASCII hostname, no scheme, path or port; punycode for international names |
| `duration` | `PT30M` | ISO 8601 duration, validated by jsonschema's installed format dependency |

Patterns, allowed values, required flags, length and numeric constraints still
combine with formats. Advanced JSON supports nested schemas and additional
constraints; it never executes user Python or JavaScript. Errors retain the
context path, including list indices (for example `context.contacts.0.phone`).

## Examples, previews and delivery

Generate example sends the current unsaved schema to the bounded preview worker.
It validates candidates with the same validator used for preview, publication and
runtime acceptance, including `/notifications/validate`. It supports nested objects,
lists, formats, enums, constants, length and numeric bounds. It tries explicit
schema `examples` first, filtering out invalid examples. It is not a general schema
solver: arbitrary patterns, intersections, uniqueness and complex conditional
schemas may require a valid `examples` annotation or manually entered test data.
If it cannot construct a valid value, it reports the problem and preserves current
fixtures. It never silently substitutes a value that fails the schema. Generation
is bounded to 100 list items and 10,000 string characters, within the renderer's
existing time, nesting and resource limits.

Generated data replaces only in-memory preview data after success. Runtime
defaults, saved scenarios, persisted drafts and caller context remain separate.
A draft changed while generation runs keeps its newer edits. Invalid drafts and
fixtures can still be saved for further editing; publication requires valid
fixtures. Preview and validation do not enqueue notifications or call providers.

SDK clients send ordinary JSON context and use the server validation endpoint;
no client-side phonenumbers installation is required. An independent JSON Schema
consumer must implement Voxriva's phone extension: generic JSON Schema tools may
ignore unknown `format: "phone"` and the annotation.

## Implementation and verification

The shared registry is `backend/app/features/templates/formats.py`; generated
frontend metadata is checked for drift. Runtime parity is covered in
`tests/integration/test_variable_formats.py`, including nested error paths,
publication/preview/generation and validation/acceptance. The isolated browser
scenario is `frontend/e2e/31-variable-formats.spec.ts`. [Development checks](development.md)
describe the available verification commands.

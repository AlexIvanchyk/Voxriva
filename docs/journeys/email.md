# Template and payload contract

A template is content plus a versioned JSON input contract. `DraftContent`
contains channel fields, `variable_schema`, `runtime_defaults`,
`preview_context`, named `scenarios` and email-only `images`. The current
`contract_version` is 1. Published versions freeze these values; runtime callers
reference the template key and resolve a deployment rather than naming a draft.

## Schema and rendering

Use a JSON Schema Draft 2020-12 object root. Nested objects, arrays, enums,
constants, required fields, numeric/length constraints and known string formats
are supported. References must be inlined. Set `additionalProperties: false`
when your application contract should reject unknown context members.

For example, a template contract can be:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "properties": {
    "first_name": {"type": "string", "minLength": 1},
    "account_url": {"type": "string", "format": "uri"}
  },
  "required": ["first_name", "account_url"],
  "additionalProperties": false
}
```

That minimal contract is illustrative; the local Northstar fixture extends it
with image/phone fields and published defaults. Its runtime request remains
[welcome.json](../examples/welcome.json).

Content uses restricted Jinja, for example subject `Welcome, {{ first_name }}`
and HTML `<a href="{{ account_url }}">Open your account</a>`. Strict undefined
access applies even to optional schema properties; guard optional values with
`is defined` or provide an explicit runtime default. HTML autoescaping remains
on. There are no global objects, attribute/call access or `safe` filter.
See [execution and payload limits](../limits.md).

Email needs a valid nonempty subject without CR/LF and at least one nonempty
body representation. Maintain HTML and plain text when clients require both.
Push has title/body and string-valued data, with its own full transport budget.
The server does not fetch URLs contained in context or templates.

## Email layout composition

A published layout wraps the corresponding HTML or plain-text body using the
structural body slot. A format the layout omits uses the template's own content
directly. Layouts can publish without a subject and cannot reference another
layout. The letter supplies the delivery subject.

For a composed letter, declare named properties on a Draft 2020-12 object
root. The layout and letter contribute their properties, required fields,
runtime defaults and saved images to one contract. Names shared across the two
sources are rejected. Unknown context fields are rejected when either source
sets `additionalProperties: false`. Composition supports boolean
`additionalProperties` and rejects advanced root constraints such as
`oneOf` and `patternProperties`. Constraints on named properties still apply.
The body slot is structural and takes no context value.

Delivery uses the combined defaults and a single request context. During
preview, the template's fixture, selected scenario or supplied preview context
can override the layout fixture. For editor steps, see
[Author email layouts](../workspace-guide.md#author-email-layouts).

## Defaults and fixtures have different semantics

The effective runtime context is a shallow merge:

```python
effective = {**published_runtime_defaults, **request_context}
```

The actual schema validation and image processing happen **after** that merge.
A supplied top-level value wins, including null, false, zero, empty string or an
entire nested object. An invalid override fails; it does not silently fall back.
An omitted nested key is not recursively filled from another object.

`preview_context` and named scenarios are fictional rendering inputs only.
They never fill a runtime request. JSON Schema `default` is an annotation and
also does not fill context. Published runtime defaults are the only server-side
values intended to supplement missing request properties.

## Formats and extension markers

Standard known formats are checked through the installed jsonschema checker.
Email/URI/date/date-time/UUID, IPv4/IPv6, hostname and duration remain strings;
validation does not verify ownership, fetch a URI or send an OTP.

Phone is a Voxriva extension requiring an explicit version annotation:

```json
{"type":"string","format":"phone","x-voxriva-phone-version":1}
```

The value must already be a valid international E.164 string. No region is
guessed and no normalization is performed. Historical published `format: phone`
without the marker retains its previous runtime behavior; authoring/publication
requires explicit opt-in. Unknown formats are publication errors. See
[format compatibility and generation](../variable-formats.md).

Image is an object with `x-voxriva-image: 1`, not a nonstandard JSON Schema
`type: image`. It contains claimed MIME and canonical base64 bytes. The server
decodes/validates the raster, enforces semantic budgets and converts referenced
values to CID identities. See [Image v1](../email-images.md).

## Preview, save and publication boundaries

`POST /api/v1/templates/{id}/preview` can render a saved draft, an unsaved draft
proposal and explicit context or a named saved scenario. Scenario selection takes
precedence over supplied context. It returns rendered fields or structured
errors and creates no notification, outbox, provider send or persisted ad-hoc
input. Version preview renders an immutable snapshot.

Generate-example is an explicit bounded operation; candidate values are checked
with the shared validator. Unsupported constraints can require manual input or
a valid schema `examples` annotation. It does not populate runtime defaults.

Draft saves use an expected revision and can retain invalid schema/content as
work in progress. Publication validates the saved revision, synthetic fixture
and explicit defaults before freezing the version. Publish and deployment are
separate mutations. See [version resolution/concurrency](lifecycle.md).

Management routes and dashboard writes use account/project permissions;
Delivery keys cannot author a template. [MCP](../../MCP.md) supports scoped
create/read/preview/reviewed draft saves with the same domain renderer. It has
no publication, deployment or send tool. The [editor reference](../workspace-guide.md)
covers authoring controls as a secondary UI workflow.

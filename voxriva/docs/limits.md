# Limits and validation boundaries

These are current implementation limits, not benchmarked throughput or an SLA.
Plan payloads and ingress settings around semantic budgets rather than a single
maximum HTTP-body number.

| Boundary | Limit / behavior |
| --- | --- |
| Runtime context | 100,000 UTF-8 bytes after canonical compact JSON serialization with image byte strings excluded; object required |
| Draft | 100,000 nonimage UTF-8 JSON bytes including schema, defaults, fixtures and scenarios |
| Draft content fields | subject 20,000; HTML/text 30,000 each; push title 10,000/body 20,000 characters |
| JSON Schema | Draft 2020-12 object root; 20 nesting levels; $ref/$dynamicRef/$recursiveRef unsupported |
| Rendered output | 200,000 UTF-8 bytes combined across rendered text fields; CID binary bytes have a separate budget |
| Renderer execution | Child process, 3-second wall limit; Linux address-space limit 256 MiB and CPU limit 2 seconds |
| Render concurrency | Two slots per API process, shared by preview/runtime render work; saturation can return 429 |
| Preview rate | 60 attempts per account per minute, process-local; quota response supplies Retry-After: 60 |
| Synthetic generation | At most 100 list items and 10,000 string characters; validated candidate or an error, not a general schema solver |
| Scenarios | At most 20 names, each 1–80 characters |
| Static images | At most 20 per draft; names match [A-Za-z][A-Za-z0-9_-]{0,79} |
| Raster value | 1–262144 decoded bytes, at most 4096 px on either side and 4,000,000 pixels; PNG/JPEG/single-frame WebP |
| Image aggregate | 1048576 decoded bytes in a draft, runtime context and effective rendered message; repeated input values count |
| MCP body/change set | 6,000,000 JSON bytes; 1–20 unique template/branch entries per batch |
| Push transport | Complete serialized FCM request ≤4096 bytes, including target/envelope, not just displayed body text |
| Idempotency-Key | 1–128 ASCII letters/digits or . _ : -; environment scope; retained with notification history |
| Locale | 2–35 characters, validated language/subtags and lowercased; no implicit region truncation |

The renderer's serialized input pipe also has a 3,000,000-byte cap. Reverse
proxies need to permit image-bearing authoring JSON (up to the bounded MCP/body
budget where applicable); doing so does not waive smaller image/context limits.

## Template execution is constrained

Strict undefined variables, HTML autoescaping, no globals, attribute access or
calls, and an allowlisted filter set apply. The `safe` filter is unavailable;
multiplication/exponentiation are disabled. Filters currently include upper,
lower, title, capitalize, trim, default, escape/e, length, join, replace and tojson.
Templates cannot fetch remote URLs, schemas or files. A supplied URL string is
data, not permission for a fetch.

Preview HTML is sanitized and displayed in a scriptless sandbox with restrictive
CSP. This is a browser boundary in addition to the server renderer. Other MCP
clients that display returned HTML must provide their own isolation.

## Configuration and transport are separate

Transport timeouts, leases, retry budgets and expiry are configured independently
of render limits. Defaults and allowed setting ranges are in
[configuration](configuration.md#delivery-controls). HTTP client timeout is also
separate: the SDK defaults to ten seconds per HTTPX operation, not a guaranteed
end-to-end delivery deadline.

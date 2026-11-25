# Template authoring through MCP

Ask your AI client to find templates, propose changes across languages and show
diffs with rendered previews. Review the proposal, then explicitly save the
approved drafts. Publication and deployment remain separate dashboard actions.

For example: “Update the welcome email's wording in English and Ukrainian.
Preserve its variable contract and show both diffs and previews before saving.”
Your AI client supplies the model and proposed content; Voxriva supplies scoped
access, validation, previews and revision-checked draft operations.

Start with the [MCP walkthrough](docs/journeys/mcp.md) for setup and a first
read using the tested Python MCP client. This page is the detailed reference.
The self-hosted MCP process uses the existing database and domain services;
it has no send, publish or deploy tools.

## Start and connect

From this directory, build the current application image (including all current migrations) and add the separate MCP service to the local stack:

```sh
docker compose -f compose.yaml -f compose.mcp.yaml up -d --build api mcp
```

The endpoint is `http://127.0.0.1:8001/mcp` (set `VOXRIVA_MCP_PORT` to change the
loopback port). Configure a client that supports **Streamable HTTP and a custom
Authorization header**:

```json
{
  "url": "http://127.0.0.1:8001/mcp",
  "headers": {"Authorization": "Bearer <your-management-token>"}
}
```

This is the transport configuration, not a universal client-specific config file.
The official Python SDK 2.3.0 is the tested client. Other clients require their own
connection check. This release supports pre-issued static bearer credentials;
it does **not** implement an OAuth authorization server, OAuth discovery or an
interactive OAuth consent flow. OAuth-only connectors cannot connect yet.

Install the MCP runtime locally with `pip install -c requirements-runtime.lock
-c requirements-mcp.lock '.[mcp]'`. Then `python -m backend.mcp_server` uses
`VOXRIVA_DATABASE_URL` (or the existing `VOXRIVA_DATABASE_URL_FILE` mechanism).
The API and MCP must use the same database and migration revision.

## Issue, inspect and revoke access

Delivery keys (`vxk_…`) only authorize delivery and are rejected by MCP. Management
credentials (`vxm_…`) belong to an existing dashboard account and contain an
explicit nonempty set of project IDs, `templates:read` and optionally
`templates:write`. They expire in 1–90 days (30 by default). Only SHA-256 hashes
are stored. The plaintext token is returned once at issue time.

Issue credentials through the account-authenticated CLI, the session/CSRF-protected
management API or **API keys → Purpose → Template / MCP**. The API is
`GET/POST /api/v1/management-credentials` and
`DELETE /api/v1/management-credentials/{id}`. Issuance returns plaintext once;
listing returns metadata, never hashes or saved plaintext. Users list/revoke
their own credentials; installation administrators may revoke a known ID.

Select explicit projects, read/read-write scopes and an expiry. Current account
roles constrain issuance and every later operation. Read-only viewers can issue
read credentials; write needs template editor/admin permission. Selecting all
projects is a snapshot rather than wildcard future access. Shared-template writes
still require credential coverage and editor access in every connection.

The endpoint is deployment-specific: local Compose uses a separate loopback
port; production may route `/mcp` on the dashboard host. There is no automatic
OAuth login. The UI one-time secret dialog and secondary instructions are in
the [credentials reference](docs/credentials.md).

The password-prompted CLI remains an alternative for local administration:

```sh
.venv/bin/python -m backend.mcp_credentials --url http://127.0.0.1:8080 \
  --email editor@example.test issue --name 'My AI editor' \
  --project '<project-uuid>' --write --days 30 --output /private/tmp/voxriva-mcp-token

.venv/bin/python -m backend.mcp_credentials --url http://127.0.0.1:8080 \
  --email editor@example.test list

.venv/bin/python -m backend.mcp_credentials --url http://127.0.0.1:8080 \
  --email editor@example.test revoke '<credential-uuid>'
```

Repeat `--project` for each allowed project; omit `--write` for read-only access.
Use your actual account, project IDs and a private token path. The command uses
dashboard login, the existing CSRF token, and logout. It writes a new token file
with mode 0600, refuses to overwrite an existing file and never prints the token.
Configure the client's secret store/header from this file; do not commit it.
Use HTTPS except for loopback development.

For an MFA-enabled account the CLI also prompts for an authenticator/recovery
code. Complete any required initial enrollment in the dashboard first. When the
installation requires MFA, MCP also rejects credentials for unenrolled accounts.

The corresponding session/CSRF-protected management API is
`GET/POST /api/v1/management-credentials` and
`DELETE /api/v1/management-credentials/{id}`. Users list and revoke their own
credentials; installation admins can also revoke a known credential ID.
Listing never returns hashes or plaintext. Issuance/revocation and domain writes
produce audit events without bearer values. A new credential cannot give a user
roles they do not hold.

Each request and each batch item reloads the credential and account. Current
membership/role rules are checked by the existing domain services. Revocation,
expiry, account deletion or membership removal therefore affects subsequent calls,
including calls on an already-connected client. Revocation cannot undo an already
committed save or cancel a transaction already in progress.

A shared template is readable through at least one connected project both in the
credential and in the user's live access. Writing requires editor/admin access
and credential coverage in **every** connected project. Credential responses hide
project identities outside the credential scope. Unconnected, installation-only
templates are deliberately unavailable in this first project-scoped MCP release;
connect them through the dashboard before authoring them through MCP.

## Tools and editing workflow

| Tool | Purpose |
| --- | --- |
| `list_templates` | Paginated metadata, project filter, name/key search |
| `get_template` | Full saved draft, exact branch ID, locale and revision |
| `list_branches` | All languages/branches, revisions, published heads and lineage |
| `list_versions`, `get_version`, `diff_versions` | Immutable history and contract comparison |
| `create_template` | Explicitly create a scoped template and initial main draft |
| `add_language` | Blank language or copy of a saved branch at an expected revision |
| `create_branch` | Fork a published version with recorded source lineage |
| `preview` | Validate/render saved draft, unsaved proposal or immutable version |
| `plan_changes` | Side-effect-free unified diffs and previews for draft replacements |
| `apply_changes` | Explicitly save the reviewed replacements with revision checks |

For example, changing a logo across languages:

1. Find the templates; list branches and read each exact draft. Keep
   `template_id`, `branch_id` and `draft_revision`.
2. The AI client prepares complete `DraftContent` replacements. Preserve content,
   variable schema, synthetic `preview_context`, named `scenarios` and
   `runtime_defaults` independently. A logo can live in HTML, a runtime default
   or test data: changing one does not silently change the others.
3. Call `plan_changes` with `changes.items`, each containing `template_id`,
   `branch_id`, `expected_revision` and `draft`. Review every diff and preview
   with the user. Planning saves neither drafts nor a plan record.
4. After explicit user approval, call `apply_changes` with the identical
   `changes`, the returned `confirmed_plan_hash` and `confirm: true`.
5. Inspect **all** item results. Read conflicting branches again and produce a
   new reviewed plan for those branches. Publication and deployment remain
   separate dashboard workflows.

The hash binds confirmation to the exact canonical proposal, including revisions.
It is not a stored approval, secret, signature or proof of a human's consent. The
client must enforce the user's approval policy; a credential holder can explicitly
invoke a mutating tool. Creating templates/languages/branches is also an explicit
write operation, not a preparation step automatically triggered by a preview.

Batch writes are **not atomic**. Each item uses a fresh session and the domain
save transaction. Results retain input order and identify both template and
branch. `saved` includes the new revision; `conflict` means stale revision;
`invalid` means preview validation failed; `error` covers access/input failures.
`unknown` means a database/service failure left the save outcome uncertain:
re-read that branch before deciding what to retry. Prior committed items remain
saved. `ok: false` at the top does not mean nothing was saved. Reapplying a saved
revision returns a conflict rather than silently overwriting it. The server checks
the revision again in the actual domain update after rendering.
If the connection ends before any results arrive, re-read every affected branch
before retrying; a missing response does not mean no items were committed.

All proposals have 1–20 unique branch entries and at most 6 MB total JSON. Apply
requires a matching hash and explicit confirmation and rejects rendered validation
errors for that item. Structural input failures save nothing. Incomplete drafts
can still be created and worked on through previews; fix preview errors before
applying them through this MCP workflow. Published versions remain immutable.

## Rendering and security boundaries

Preview uses the same constrained Jinja renderer, authoring diagnostics and
runtime-default pipeline as the dashboard, in a child process with a 3 second
timeout, bounded input/output and Linux CPU/memory limits. The service retains
the existing per-account 60 previews/minute limiter and two concurrent render
slots. These are process-local, as in the API; run one MCP worker unless you add
a shared limiter. A batch's individual previews consume that quota.

Synthetic fixtures and scenarios are preview-only. Runtime defaults are explicit
and separate. No preview creates a notification, outbox, deployment, audit write,
provider call or persisted ad hoc context. JSON Schema references and Jinja
attribute/call access are blocked. The backend does not retrieve logo URLs,
remote schemas, files or any other resources. There are no resource-fetch,
provider-secret, sending or replay tools. No provider encryption key is mounted
in the MCP container.

Rendered HTML is **untrusted output**, not a browser security boundary. A client
that displays it must use a scriptless sandboxed iframe with a restrictive CSP
(`default-src 'none'`, remote resources disabled) and no navigation/forms. The
existing dashboard implements its own preview isolation; arbitrary MCP clients
must provide theirs. Treat template text as data, not executable instructions.
Only store fictional/synthetic test data; the server cannot determine whether a
user-supplied string contains personal information or a secret.

HTTP is stateless; bearer authorization is checked for discovery as well as tool
calls. Missing, delivery, expired and revoked credentials receive 401. Allowed
Host and Origin are derived from the exact configured public URL; mismatches are
rejected. HTTP bodies are bounded, request access logging is disabled and
validation failures omit submitted values. Do not enable HTTP/debug tracing that
logs Authorization headers or template bodies.

## Production and stdio

Build a separate versioned image locally with `Dockerfile.mcp`. The additive
`compose.mcp.production.yaml` works with the production Compose stack and its
existing `database-url` filesystem secret. It does not alter that stack's images,
TLS, backups, release scripts or provider keyring.

Set `VOXRIVA_MCP_IMAGE` and `VOXRIVA_MCP_PUBLIC_URL=https://<VOXRIVA_HOST>/mcp`,
then add the override to production Compose. The overlay mounts the separate
`deploy/Caddyfile.mcp`: it routes `/mcp` to `mcp:8001`, retaining the public Host
header, and all other paths to the API. It reuses the production TLS secrets and
HSTS policy without modifying the base production files. A different hostname or
external proxy needs its own corresponding route. Do not expose plaintext port
8001 publicly. Use matching API/MCP source revisions and run migrations before
starting either service. Backups must include the new credential table; restored
credentials retain their hashes and expiry, so revoke/rotate them after a restore
when appropriate. No release image is published by these commands.

For a local client that launches subprocesses, stdio is also available:

```json
{
  "command": "/absolute/path/Voxriva/.venv/bin/python",
  "args": ["-m", "backend.mcp_server", "--transport", "stdio"],
  "env": {
    "VOXRIVA_DATABASE_URL_FILE": "/private/path/database-url",
    "VOXRIVA_MCP_TOKEN_FILE": "/private/path/management-token"
  }
}
```

Set the process working directory to `voxriva`, or install the package into that
Python environment. The token file is read at startup; its credential is validated
again on every tool call. Stdio does not use HTTP headers. This optional transport
does not remove project scoping, revocation or role checks.

## Verification

```sh
.venv/bin/python -m pytest tests/integration/test_mcp_authoring.py -q
bash scripts/test-mcp-compose.sh
# Dashboard issuance, permissions, one-time copy and mobile browser workflow:
bash scripts/test-mcp-keys-browser.sh
```

The first suite includes a real loopback HTTP server and official MCP client (it
requires permission to bind a local socket). The Compose smoke owns a randomly
named stack with disposable PostgreSQL, API and MCP containers, uses fictional
data and removes that stack on exit. It demonstrates discovery, read/create/edit,
language copying, branch lineage, preview, two-item batch with a stale conflict,
immutable published history, redacted invalid inputs, revocation and zero
notifications/outbox. No workers or provider configurations are needed.

The dashboard browser script builds only its dedicated test image and frontend,
starts a separate disposable PostgreSQL/API stack, and removes it on exit. It
requires an installed Playwright Chromium (`cd frontend && npx playwright install
chromium`); a custom browser cache can be supplied through
`PLAYWRIGHT_BROWSERS_PATH`. It never rebuilds a production release archive or
restarts the main application stack.

Implementation references: [official SDK 2.x documentation](https://py.sdk.modelcontextprotocol.io/),
[SDK repository](https://github.com/modelcontextprotocol/python-sdk),
[Streamable HTTP specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports),
[authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization).
The SDK is pinned at 2.3.0; custom-header bearer interoperability is tested here,
not claimed for every AI client. OAuth onboarding,
installation-wide scopes, distributed rate limiting and cursor pagination for
large version histories are possible follow-up work.

## Email images

Draft tools support `draft.images` and Image v1 object variables, including base64 bytes. Preview/save/publication share raster validation and existing project scopes. See [the image contract](docs/email-images.md) for schema, byte limits, fixtures/defaults and immutable storage. The bounded MCP body/change-set budget is 6 MB.

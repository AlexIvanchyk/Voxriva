# Credentials and scope

Voxriva has three distinct authentication surfaces. Choose a credential for the
operation, not merely an account with broad installation access.

| Surface | Credential | Effective scope |
| --- | --- | --- |
| Runtime delivery API / Python SDK | `vxk_…` Delivery Bearer key | One environment and its project; validate/send and scoped status |
| MCP template authoring | `vxm_…` management Bearer credential | Explicit project IDs, templates:read and optional templates:write, intersected with the account's current roles |
| Dashboard / administration API | Account session cookie + CSRF for writes | Current installation/project permissions, subject to MFA policy |

Secrets are issued once and stored as hashes. A Delivery key cannot administer
projects/providers/templates or list dashboard history. A management credential
cannot send notifications or call arbitrary administration endpoints. A dashboard
cookie cannot substitute for the Delivery key on runtime POSTs.

## Delivery keys

Keys are issued for an environment by an installation/project administrator.
The issuance schema defaults to 90 days and accepts 1–365 days or an explicit
null expiry. Expiry and revocation are checked on subsequent requests; they do
not cancel already accepted notifications or rewrite pinned credentials.

Use `GET /api/v1/delivery/scope` to verify the key's project/environment.
Authorization is independent of payload fields: no project ID in a request can
expand the key's scope. Environment-wide idempotency survives rotation to another
active key in the same environment.

For the local example, the launcher creates the key and writes it to the protected
`output/example/<name>/state.json`. See [local credential loading](quickstart.md#load-local-credentials).
For your application, inject a key and the installation URL through your secret
configuration. Do not reuse the example's administrator password or tokens.

## Template / MCP credentials

Credentials belong to an existing account, name 1–100 explicit projects, and
expire in 1–90 days (30 by default). `templates:read` is mandatory; write is an
additional scope, not a replacement. Issuance cannot grant roles the account
does not hold. Selecting all available projects snapshots current IDs rather
than granting future-project access.

Each request and batch item reloads the credential, account and live permissions.
Revocation, expiry or membership removal affects later calls on an existing
connection. A committed save is not undone, and a transaction already in progress
cannot be treated as cancelled by revocation.

A shared template is readable through at least one project present in both the
credential and current account access. Writing requires editor/admin permission
and credential coverage in **every connected project**. Unconnected
installation-only templates are outside project-scoped MCP access.

Issue/list/revoke through the session-protected `/api/v1/management-credentials`
API, the credential CLI, or the secondary [API keys UI reference](workspace-guide.md#environments-and-delivery-keys).
See [MCP](../MCP.md) for HTTP headers, stdio files, supported tools and explicit
batch-save confirmation. There is no OAuth discovery server or interactive
OAuth consent flow; OAuth-only clients cannot onboard through it.

## Sessions, roles and MFA

The first administrator is bootstrapped locally; there is no default account.
Dashboard sessions use HTTP-only cookies and CSRF checks for writes. Installation
administrators have inherited access; project administrators manage their
projects, template editors edit content, operators inspect/replay delivery and
viewers read permitted resources. Shared-template writes enforce all connections,
not just the project currently visible in a page filter.

`VOXRIVA_MFA_POLICY=optional` permits opt-in TOTP; `required` blocks dashboard
access until enrollment. MFA-enabled credential CLI sign-in also requires a
factor/recovery code, and required-policy MCP access rejects an unenrolled
account. Delivery-key requests remain machine authentication rather than
interactive MFA challenges. See [MFA enrollment, recovery and keyring rules](mfa.md).

The full encryption keyring protects provider credentials, temporary runtime
payloads, encrypted email history and MFA seeds; it is separate from token hashes.
Back up it and PostgreSQL together. Retaining old keys also preserves historical
idempotency fingerprint comparisons. See [configuration](configuration.md) and
[production recovery](../PRODUCTION.md#backup-database-and-full-encryption-keyring-together).

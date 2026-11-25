# Provider configuration and transport reference

Providers are installed trusted Python adapters. A named configuration has
immutable revisions containing public settings and encrypted write-only secrets.
A channel binding selects an exact revision at environment/project/global scope.
Accepted notifications pin that revision; changing a configuration or a binding
does not rewrite queued work.

## Scope and management API

Project administrators manage configurations owned by their project and can bind
permitted shared revisions there. Installation administrators manage shared
configurations/global defaults. Configuring, assigning or probing a provider does
not enqueue a notification. Delivery keys cannot call these management routes.

| Route under /api/v1 | Purpose |
| --- | --- |
| GET /providers/types | Installed adapter schemas, channel and capabilities |
| GET/POST /providers | Inventory / create named configuration |
| GET/POST /providers/{id}/revisions | Inspect public settings and secret presence / create a new revision with expected_revision |
| GET/PUT /providers/bindings | Inspect/elect an exact revision with expected_generation |
| GET /providers/resolve | Side-effect-free scoped channel binding resolution |
| POST /providers/{id}/test-connection | Probe a specified revision without sending |
| POST /providers/{id}/send-test | Explicit email/push provider test, outside notification/outbox history |

Bindings resolve **environment → project default → global default** for a
channel. Project-owned configurations cannot be used by another project; shared
binding access does not grant permission to edit/test shared credentials.
Optimistic revision/generation conflicts return 409. Keep API/worker plugin sets
identical so a pinned adapter remains available.

## SMTP

The adapter key is `smtp`, channel email. Its config object for **local Compose**
Mailpit is:

```json
{
  "host": "mailpit",
  "port": 1025,
  "tls": "none",
  "sender": "sender@example.test",
  "username": "",
  "timeout": 5
}
```

This is provider config, not the entire POST /providers body. Creation wraps it
with name, provider_type and optional project_id returned by your management
setup. The [example launcher](evaluate.md) performs those steps automatically
inside its owned stack; do not point this config at a public mail service.

Supported tls values are `starttls` (default), `ssl` and `none`. Port defaults to
587; timeout is 1–15 seconds (default 5). TLS certificates are verified.
Authentication requires a username/password pair and TLS. Password is write-only:
omitting/retaining it preserves the previous secret; explicit clear_secrets
controls removal. Secret rotation creates another immutable revision and requires
an explicit binding change. The remote service can invalidate credentials still
pinned by old notifications.

Test-connection opens SMTP, negotiates TLS/auth when configured and uses NOOP.
It does not send. Explicit send-test bypasses template/queue/history and requires
a supplied recipient/content. SMTP Sent means acceptance, not inbox receipt.
An ambiguous error after sending begins is Unknown. Local Mailpit has no outbound
relay, and its SMTP port is private to the Compose network.

Transport tests require management rights and allow ten tests/account/minute
with at most two concurrent tests per API process. Configure
VOXRIVA_SMTP_ALLOWED_HOSTS as a JSON array when private destinations must be
restricted. Empty permits administrator-configured endpoints.

The keyring is external to the database/image; local Compose persists it in
provider-secrets. Back it up with PostgreSQL. Key rotation prepends a new primary
while retaining old keys; it does not re-encrypt every historical credential or
MFA seed automatically. See [configuration](configuration.md).

## Amazon SES

Choose the AWS region, a verified sender and authentication:

- **Workload credentials** uses the standard AWS credential chain on API/workers (IAM
  workload roles, environment or mounted SDK credentials).
- **AWS access keys** requires both an access key ID and secret; an optional session
  token supports temporary credentials. All three fields are encrypted and write-only.

**Test connection** calls SES v2 GetAccount without sending a message. It requires
`ses:GetAccount`; delivery requires `ses:SendEmail`. Sandbox accounts also need verified
recipients. A successful account probe does not establish sender verification or remove
sandbox restrictions. **Send test email** is explicit, independent of notification jobs.
The SDK has one total attempt; durable worker retry/Unknown policy remains authoritative.

For verified delivery status, set an SES **Configuration set** with Delivery and Bounce
publishing to an SNS topic in the same region, and save its **SNS topic ARN** in the
provider revision. In Configure, copy the event URL:
`https://your-public-host/api/v1/providers/<configuration-id>/events/ses`.
Subscribe that HTTPS endpoint in SNS (JSON envelope, raw delivery disabled); use SNS
signature version 2. Saving a topic ARN does not create an AWS subscription. The API
confirms a correctly signed subscription with SNS ConfirmSubscription, never by following
an incoming SubscribeURL. Its AWS credentials must allow `sns:ConfirmSubscription` for
the expected topic. Localhost needs a publicly reachable HTTPS deployment to receive SNS.

Only signed notifications for a saved expected topic are accepted. Signing certificates
come from the exact regional SNS HTTPS host, with no redirects, alternate ports or arbitrary
certificate URLs. Signature versions 1 and 2 are verified; version 2 is recommended.
Event IDs are deduplicated per configuration. Only normalized message ID, event type and
timestamps persist; recipient lists, raw payloads and provider error text are discarded.
Events arriving before the worker saves acceptance wait in an inbox and are correlated by
the provider's message ID and the pinned provider revision/topic. Unmatched events expire
after seven days. Newer event timestamps win; at equal times a bounce wins. Late older
events remain in history but cannot revert a newer status. **Delivered** and **Bounced**
are shown only after verified SES events, with their occurrence and receipt timestamps.

## Firebase Cloud Messaging

Choose the Firebase project ID and either an encrypted **Service account JSON** or
**Workload credentials** (Google Application Default Credentials). Credentials must have
`cloudmessaging.messages.create` in the target project. For ADC, make credentials available
to API and push worker through your deployment configuration. The standard image does not
include cloud keys. Google service-account configuration accepts only the standard Google
OAuth token endpoint; caller-supplied authentication URLs are rejected.

**Test connection** obtains an OAuth token without sending or proving FCM permission.
**Test push** defaults to validation only (`validate_only: true`); check **Send to device**
to deliver an explicit test push. Validation requires a real registration token and FCM
permission and does not create delivery history. **Sent** means FCM accepted the message;
it does not confirm device display or receipt. FCM has no trusted per-message delivery
webhook in this implementation, so it never invents Delivered or Bounced states.

Push notifications use the same environment API key, idempotency and runtime context
contract as email, with `device_token` instead of `recipient`:

```bash
curl http://localhost:8080/api/v1/notifications \
  -H 'Authorization: Bearer <environment-key>' \
  -H 'Idempotency-Key: <stable-unique-request-id>' \
  -H 'Content-Type: application/json' \
  -d '{"template_key":"<published-push-template>","device_token":"<device-registration-token>","locale":"en","context":{"name":"Example"}}'
```

Supply exactly one target matching the template channel. Rendered pushes need a title,
body and an FCM request size of at most 4096 bytes. Published push data values render as
strings. The device token is encrypted in runtime storage and always hidden in delivery
history, audit and metrics. Expired failed push replay requires a new token and explicit
runtime context. A permanently unregistered token fails without retry; replace it in the
calling application. Quota/temporary service responses honor Retry-After (quota waits at
least 60 seconds), while an ambiguous network timeout after sending becomes Unknown.


## Custom adapters and evidence boundary

Install a reviewed package at image-build time with an entry point in
`notification_platform.providers`. The public contract is
`backend.app.providers.base.BaseProvider`, interface version 1, with a unique key,
channel, config model, capabilities and bounded test/send methods. Use SecretStr
or writeOnly metadata for secrets and normalize errors through ProviderError.
An uncertain error must not be labelled safe solely to obtain retries.

The registry rejects duplicate keys, unsupported interfaces, abstract adapters
and unsupported generated-form schemas. Current schema-generated forms support
flat scalar fields/enums/optional values. Plugins are trusted code, not dashboard
uploads or runtime pip installs. Use the same reviewed custom image for all
application roles, then repeat relevant dependency/runtime checks. See the
[external provider example](../examples/provider-plugin/README.md).

Local tests use deterministic SES/FCM transports and signed event fixtures.
These cover request shapes and runtime classification, not live AWS/Firebase
credentials or recipient/device receipt. The ordinary local evaluation verifies
real SMTP/Mailpit. See [delivery semantics](journeys/operate.md),
[development checks](development.md).

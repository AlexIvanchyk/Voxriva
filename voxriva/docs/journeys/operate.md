# Acceptance, delivery and recovery semantics

There are three different retries: an application's HTTP retry with the same
idempotency key, a worker's safe transport retry within one notification, and an
operator replay that creates a new linked notification. They solve different
failure boundaries and should not be substituted for one another.

## Commit and publication boundaries

Acceptance validates the request and pins content/provider revisions before
committing the PostgreSQL notification and outbox in one transaction. HTTP 202
follows that commit. Redis availability and provider acceptance are not commit
conditions; a broker outage can leave durable work queued.

The relay locks an eligible outbox row, publishes an ID-only task, then marks it
published and commits. A crash after publication but before that commit can
republish. Redis/task acknowledgement is not an exactly-once boundary. Workers
claim notifications with database locks, lease tokens and fencing checks so
repeated task consumption does not grant another ordinary send.

## States

| API value | Meaning / next action |
| --- | --- |
| `queued` | Accepted, waiting for eligible dispatch/claim |
| `retrying` | A safe retry has been scheduled; inspect next_attempt_at and attempts |
| `processing` | A worker holds a fenced renewable claim |
| `sent` | The configured provider accepted the message |
| `delivered` / `bounced` | Verified, correlated SES event; not inferred from transport acceptance |
| `failed` | Permanent error, exhausted safe attempt budget or expired queued input |
| `unknown` | External acceptance cannot be ruled out; investigate rather than retry blindly |

SMTP Sent means SMTP acceptance. FCM Sent does not prove device receipt/display.
SES receipt events are accepted only from the expected signed SNS topic and are
correlated to the pinned provider revision/message ID. The event inbox handles
early arrivals, deduplication and out-of-order timestamps; newer events win and
bounce wins at equal timestamps. See [provider event configuration](../delivery-guide.md#amazon-ses).

## Worker retry and crash policy

Defaults are three attempts, a 5-second exponential retry base capped at 60
seconds, a 180-second renewable lease and two concurrent processing claims per
provider configuration across its revisions. Jitter uses half to all of the
bounded exponential delay. Finite provider Retry-After guidance can extend the
wait, capped at one hour. Provider-specific rules still apply, for example FCM
quota handling. See [configuration](../configuration.md#delivery-controls).

A retry requires a failure classified safe/retryable, remaining attempt budget
and unexpired input. Ambiguous provider errors become Unknown. After a worker
crash, reconciliation can safely reschedule a claim that never entered sending;
a claim that entered the send phase becomes Unknown. The Celery hard task limit
is 120 seconds (soft 110); keep the lease/grace periods longer and consistent
across processes. Fencing protects state transitions but cannot revoke a message
already accepted by an external provider.

The SDK independently retries transient HTTP outcomes with the original encoded
body/key. It does not automatically resubmit a Failed/Unknown notification as a
new operation. See [HTTP retry behavior](integrate.md#handle-failures-at-the-right-boundary).

## Idempotency and response uncertainty

A missing response is not evidence that acceptance failed. Persist your operation
key and original payload before sending. Retry those exact values after a network
timeout, process restart or retryable HTTP error. A matching request returns the
same ID before resolving new deployments; a different request with that key is
409. There is no exactly-once recipient-delivery promise, and changing the key
requests a different notification. See [canonical fingerprint behavior](../api.md#idempotency).

## Runtime retention and privacy

Runtime payloads are encrypted and expire after 24 hours by default (configurable
1–604800 seconds). Queued/retrying work whose input expires becomes Failed.
Successful and Unknown outcomes clear temporary payloads immediately; Failed
input may remain until its original expiry. Cleanup runs through the relay, so
relay downtime can delay physical deletion after the deadline.

Encrypted email-recipient history is independent of the runtime payload. Authorized
dashboard users can view/search it; Delivery-key responses mask it. Technical
history and immutable published/static images are retained. Device tokens are
not exposed in history. The payload TTL is not a notification-history deletion
policy. Sanitized Celery telemetry and unmatched provider inbox events are cleaned
after seven days.

## Operator replay

`POST /api/v1/notifications/{id}/replay` is a session/CSRF-protected management
operation for an installation admin, project admin or operator. Only `failed`
is eligible; Unknown returns 409. The request includes a stable `replay_key` and
`expected_updated_at` from the inspected record. Stale state returns 409.

Replay creates a new linked notification and audit event while preserving the
original. It defaults to the original template/provider revisions. Setting
`use_current_deployments: true` deliberately resolves current pointers instead.
The same replay key is idempotent for that original record and proposal.

Supply the channel-appropriate target **and** context together to replace input.
If omitted, the server can reuse only retained, unexpired decryptable payload.
After expiry it requires resupplied values; fixtures never substitute. Fixing a
provider's saved revision without selecting current deployments still reuses the
original pinned credentials. Inspect both revision choices before replaying.

## Operational signals

Inspect outbox backlog/age, queue depth, worker freshness, attempt error codes and
next retry times. Queue counts are approximate; PostgreSQL records are durable.
`GET /api/v1/operations/metrics` requires an installation-admin session or the
configured metrics Bearer token. Explicit invalid bearer authentication does not
fall back to a session. Public `/metrics` contains dependency readiness only.

An application content rollback changes a deployment pointer for future
acceptance. Disaster recovery instead restores a matching database and complete
keyring with a fresh Redis volume; it cannot undo a provider send or preserve
recovery codes consumed after the backup. See [production recovery](../../PRODUCTION.md).

# Configuration and deployment modes

The application reads `VOXRIVA_` settings. Source entrypoints share the same
PostgreSQL models, renderer and permission services; each runtime role needs
matching code, migrations and configuration where relevant.

## Deployment modes

| Mode | Intended use | Operational boundary |
| --- | --- | --- |
| `python3 scripts/example.py` | Isolated evaluation and first API send | Named owned disposable stack, fictional fixture and private generated state |
| `docker compose up --build -d` | Persistent local development/demo | Canonical local stack on loopback; does not seed a template/key automatically |
| `compose.production.yaml` | Single-host production installation | HTTPS, secure cookies, file-backed secrets, private dependencies and coordinated data operations |
| Native API/Vite | Feature development | Requires separately configured PostgreSQL/Redis/keyring; does not automatically start delivery processes |

Run commands from `voxriva/`. Do not layer the local Compose file over production.
The [example](evaluate.md) can coexist with the main local stack; do not seed or
reset an existing installation to evaluate the docs.

For a new persistent local installation, start Compose and bootstrap once:

```sh
docker compose up --build -d --wait --wait-timeout 180
docker compose exec api python -m backend.app.features.identity.bootstrap --email admin@example.test
```

The password is entered interactively. This creates the administrator, not a
provider/template/deployment. Configure those through management APIs/dashboard
or use the separate isolated example for a prepared integration fixture.

## Required resources and secrets

| Setting | Purpose |
| --- | --- |
| `VOXRIVA_DATABASE_URL` / `VOXRIVA_DATABASE_URL_FILE` | PostgreSQL SQLAlchemy async URL; file content overrides the inline setting |
| `VOXRIVA_REDIS_URL` | Broker connection for API readiness, relay and workers |
| `VOXRIVA_PROVIDER_ENCRYPTION_KEYS` / `VOXRIVA_PROVIDER_ENCRYPTION_KEY_FILE` | Complete Fernet keyring; new primary first, retained old keys following |
| `VOXRIVA_METRICS_TOKEN` / `VOXRIVA_METRICS_TOKEN_FILE` | Protected operations-metrics bearer credential; file content overrides inline |
| `VOXRIVA_SECURE_SESSION_COOKIE` | Defaults true; local Compose explicitly permits HTTP cookies on loopback |
| `VOXRIVA_MFA_POLICY` | optional (default) or required; unknown values fail validation |
| `VOXRIVA_SMTP_ALLOWED_HOSTS` | JSON array limiting administrator-configured SMTP destinations; empty by default |
| `VOXRIVA_CONTAINER_MONITORING_ENABLED` | Local collector snapshots; production explicitly disables container inspection |

The local stack creates a random persistent key in its `provider-secrets` volume.
The production secrets initializer creates a protected host keyring file. There
is no fallback development encryption key. Losing/replacing the keyring against
an existing database can make provider secrets, runtime data, email history and
MFA seeds unreadable. Keep old keys needed for retained data and idempotency
fingerprints; rotation is not permission to discard them.

Production uses `database-url`, `provider-keyring`, `metrics-token` and TLS
filesystem secrets. Use the commands and file permissions in
[the production runbook](../PRODUCTION.md#prepare-and-install), including SMTP
allowlisting and custom plugin installation. Do not put real env files/secrets
inside a Docker build context.

## External PostgreSQL and Redis

The application accepts connection URLs; it does not require its database/broker
to run in the same Compose project. Supply a SQLAlchemy `postgresql+asyncpg://…`
URL through `VOXRIVA_DATABASE_URL` or a protected URL file. Supply the Redis broker
URL through `VOXRIVA_REDIS_URL` consistently to the relevant roles. Configure the
TLS/CA/auth options required by those services and the installed drivers, and
verify connectivity from every role. No cloud-specific database provisioning or
credential discovery is implemented.

The existing Compose files are a bundled topology, not a managed-service switch.
Production sets Redis directly to `redis://redis:6379/0`; adding a variable of the
same name to .env.production alone does not override that YAML value. Its
application/migrate depends_on conditions also reference local services. A custom
deployment must replace those environment/startup relationships, retain a single
migration execution against the external database, and provide the same complete
keyring to all data readers/writers. Do not change a running installation's
connection target without a verified data migration and cutover plan.

`scripts/production-data.py` uses Compose exec into postgres for dump/import, and
its restore safety checks assume that service's database. Managed services need
a separately tested provider/dump backup/restore process, retaining the full
application keyring alongside the matching database snapshot. Redis remains
reconstructible transport, but disaster restore still requires a fresh/cleared
isolated broker namespace so old tasks cannot refer to another snapshot.

API sessions and permission data are PostgreSQL-backed; an API replica does not
need a private session store. Share static build, keyring and compatible settings,
configure ingress correctly, and account for process-local render/rate budgets.
Workers can replicate per channel with global database claims/provider limits.
A relay can publish duplicates after its publish/commit boundary; claims and
idempotency, rather than a claim of exactly-once broker transport, handle that.
Queue names are fixed to email/push. Independent installations require an isolated
broker endpoint or provider-supported separate Redis database; project/environment
permissions inside one installation are not a broker namespace. No automatic
scaling or multi-host HA topology is shipped by the Compose runbook.

## Delivery controls

Keep shared settings consistent across API, relay and both workers.

| Setting suffix (prefix VOXRIVA_) | Default | Accepted range / role |
| --- | --- | --- |
| DELIVERY_MAX_ATTEMPTS | 3 | 1–10; safe attempt budget |
| DELIVERY_RETRY_BASE_SECONDS | 5 | Positive; exponential delay base |
| DELIVERY_RETRY_MAX_SECONDS | 60 | Positive; exponential delay cap before provider guidance |
| DELIVERY_PAYLOAD_TTL_SECONDS | 86400 | 1–604800; runtime input deadline |
| DELIVERY_LEASE_SECONDS | 180 | 10–600; keep longer than the 120-second hard task limit |
| DELIVERY_PROVIDER_CONCURRENCY | 2 | 1–20; database-enforced claims per provider configuration |
| DELIVERY_OUTBOX_RESEND_SECONDS | 30 | 5–600; eligible unclaimed publication reconciliation |
| WORKER_STALE_SECONDS | 30 | 5–300; worker freshness threshold |

[Delivery semantics](journeys/operate.md) describes uncertainty, payload cleanup,
Retry-After and replay. These controls do not establish a delivery SLA or make
an unsafe external send retryable.

## Health, migrations and data operations

`/health/live` reports process liveness. `/health/ready` checks configured database
and broker dependencies and returns 503 when unavailable. Neither is a provider
credential test. Apply migrations before starting matching API/MCP/workers; the
Compose migration job does this. Do not run mismatched source versions against
a newly migrated database without a tested rollback procedure.

Back up PostgreSQL and the **entire encryption keyring together**, with writers
quiesced. Backup tooling leaves writers stopped until explicit resume. Restore
to fresh volumes/project with a fresh Redis transport; outbox reconciliation
reconstructs pending work. Never use `down -v` on the user's installation as a
restore preparation step. Follow the [backup/restore/upgrade runbook](../PRODUCTION.md)
for the actual commands and failure behavior.

Cloud credentials and event ingress are provider-specific. SES live sends need
verified senders/sandbox permissions; verified events need an HTTPS SNS setup.
FCM needs service-account/workload authorization and a real test-device token.
Local cloud doubles do not establish those external prerequisites.

Release policy requires application dependency/security/runtime checks and
image-bound evidence. OS scanning is optional advisory. See [release status](release-status.md)
for platform scope, licensing and outstanding publication prerequisites.

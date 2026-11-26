# First self-hosted production release (Compose)

This distribution targets one Linux Docker host with Docker Engine 28+ and Compose
v2, PostgreSQL 17, Redis 7 and an operator-supplied TLS certificate. It does not
require a cloud account or send telemetry. It is a single-host deployment: plan a
maintenance window for migration, backup and restore. Helm and Kubernetes workload
monitoring are not included.

## Prepare and install

Work from the release artifact directory (or this application directory). Do not
combine `compose.yaml` with production; the former contains demo credentials and
Mailpit. Production publishes only HTTPS, keeps API/PostgreSQL/Redis private, uses
secure session cookies, and never mounts the Docker socket. System Health shows
live dependency checks and Operations shows worker/application health; container
monitoring is explicitly disabled. The existing isolated Docker collector remains
available in the local demo stack.

1. Download the reviewed operator bundle from the GitHub release and verify its
   `OPERATOR-SHA256SUMS` before extraction. The configured public image is
   `ghcr.io/alexivanchyk/voxriva:0.1.1` (linux/amd64). For an offline image archive,
   verify the artifact checksums:
   `shasum -a 256 -c SHA256SUMS`. A `RELEASE-BLOCKED` file means the
   candidate failed a required scan and must not be promoted. For a locally built archive run
   `docker load -i voxriva-image.tar`. Archives are for the builder's platform;
   build/test each target architecture separately. Checksums establish integrity;
   obtain the checksum list from a trusted channel.
2. `cp deploy/production.env.example .env.production`. Set the real HTTPS hostname,
   a fixed application image tag or registry digest, and a stable Compose project
   name. Never change the project name during an upgrade: it selects the volumes.
   Keep custom secret/backup paths outside the build context, or explicitly exclude
   them in `.dockerignore` before building. PostgreSQL/Redis/proxy defaults are pinned to the digests used in the local
   smoke. Review and pin any overrides to immutable digests before promotion. Do not use `latest` or overwrite a released image tag.
3. `python3 scripts/init-production-secrets.py secrets`. This refuses a nonempty
   directory and generates independent high-entropy database, metrics and provider
   encryption secrets. Keep this host directory at mode 0700. App secret files are
   0444 inside it so non-root UID 10001 can read Compose bind-backed secrets;
   Compose does not remap their UID/GID. Do not make the host directory accessible
   to other users. Protect the deployment host and Docker daemon as administrators.
4. Install your full-chain certificate as `secrets/tls.crt` and private key as
   `secrets/tls.key` (0600). The SAN must match `VOXRIVA_HOST`. Caddy uses these
   files directly, without an ACME account. Maintain renewal outside this stack;
   after renewal recreate proxy with `up -d --force-recreate proxy`. Open inbound
   TCP 443, configure DNS and restrict host firewall access as appropriate.
5. Start and check readiness:

   ```sh
   docker compose --env-file .env.production up -d --wait --wait-timeout 180
   curl --fail https://notifications.example.org/health/ready
   docker compose --env-file .env.production exec api python -m backend.app.features.identity.bootstrap --email admin@example.org
   ```

   Bootstrap prompts for a password interactively; there is no default administrator
   or password. Open `https://notifications.example.org/sign-in`. Create a project,
   environment, template, publish/deploy it, configure a provider and bind its exact
   revision, then issue an environment key. Use [configuration](docs/configuration.md), [template contracts](docs/journeys/email.md)
   and the [Delivery API](docs/api.md) for the integration setup. TLS must work before signing in; secure cookies are never downgraded.

For private SMTP, allow only explicit trusted destinations with the JSON array
`VOXRIVA_SMTP_ALLOWED_HOSTS`. Public SMTP/SES/FCM use normal provider configuration;
no demo provider is configured automatically. Provider plugins must be reviewed
and built into the same image used by every process. Do not expose Redis or PostgreSQL.
Metrics require the generated token and should be scraped privately.

API, relay and workers use one image with read-only roots, temporary `/tmp`, no
capabilities, init forwarding, restart policies and 150-second termination grace (above the worker's 120-second hard task limit).
Worker probes use a lightweight Celery control client instead of importing the
application in every probe. Cold starts have separate health-check grace periods; PostgreSQL readiness uses
TCP so migrations cannot race its temporary initialization server.
Celery receives SIGTERM for warm shutdown; relay already handles SIGTERM. Liveness
checks process health; `/health/ready` checks dependencies. Compose does not replace
an external uptime alert. Each worker can scale independently with
`up -d --scale email-worker=2`; there are no fixed container names or worker ports.

## Backup: database and full encryption keyring together

Run on the Docker host, from the deployment directory, with Python 3.11+:

```sh
python3 scripts/production-data.py backup backups/2026-11-25-before-upgrade
```

The command stops proxy, API, relay and both workers before `pg_dump --format=custom`.
If the optional MCP production overlay is configured, it stops that writer too.
Quiesce any other custom database writers separately.
Allow the configured grace period and inspect unknown/in-flight deliveries before
resuming. It creates `database.dump`, `provider-keyring` and a manifest with SHA256
checksums and the configured application image. **Applications remain stopped on
success or failure**, so an incomplete backup cannot silently resume writes.
Resume explicitly with the startup command above.

Backups contain secrets, personal data, encrypted payloads and the keys that decrypt
them. The tool creates a 0700 directory and 0600 files; encrypt and copy the complete
bundle to access-controlled off-host storage. Checksums detect corruption, not
malicious replacement. Maintain several generations and rehearse restoration.
Protect TLS/private database credentials separately; they are host configuration,
not part of this portable data bundle. Back up the entire comma-separated provider
keyring, including old keys after rotation. Never generate a replacement keyring for
an existing database. Losing a key can make credentials, retained payloads and
idempotency fingerprints unrecoverable.

Redis is a reconstructible delivery transport; PostgreSQL is the durable source.
For disaster restore use a **fresh Redis volume**, so stale queued tasks cannot
refer to a different database snapshot. Existing outbox reconciliation restores
pending tasks. Recovery does not remove external-send ambiguity: investigate
Unknown outcomes before replaying them.

## Restore drill and disaster recovery

Use a NEW deployment directory and Compose project name, with NEW PostgreSQL and
Redis volumes. Keep the same PostgreSQL major version. Initialize new host secrets
and TLS as above. Select the application image recorded in the backup manifest.
Do not start applications or run migrations before importing the backup:

```sh
docker compose --env-file .env.production up -d --wait postgres redis
python3 scripts/production-data.py restore /secure/backups/complete-bundle
docker compose --env-file .env.production run --rm --no-deps migrate
docker compose --env-file .env.production up -d --wait --wait-timeout 180
curl --fail https://notifications.example.org/health/ready
```

Restore validates both file checksums before stopping anything, refuses a populated
public schema, imports in one transaction and restores the full provider keyring.
If key writing fails after DB import, leave services stopped and restore that file
from the verified bundle before retrying startup. Never run `down -v` against your
production project to prepare a restore. Keep the old deployment stopped until the
new instance is verified; route traffic only to one instance. Verify sign-in,
projects, deployed versions, provider connection/decryption, notification history
and a synthetic delivery. Configure your DNS/TLS cutover separately.

## Upgrade and rollback

Retain the old image ID/digest (`docker compose --env-file .env.production images`)
and the old `.env.production` securely. Read migration notes in README and test the
candidate against a restored backup first. From the existing deployment directory:

```sh
VOXRIVA_IMAGE='ghcr.io/<github-owner-or-org>/<package>:0.2.0' bash scripts/upgrade-production.sh backups/before-0.2.0
```

When using the optional MCP overlay, select its matching reviewed image in
`VOXRIVA_MCP_IMAGE` and include the overlay in `COMPOSE_FILE`; its writer is stopped
for backup and restarted with the application. The primary image archive does not
contain the separate MCP image.

The script pulls the candidate before downtime, stops writers and takes a backup,
runs a fresh one-shot Alembic migration, then recreates private application
processes and checks actual API database/broker readiness before opening the HTTPS
proxy. A post-backup failure stops the application writers and proxy, keeping the
maintenance window open; inspect logs before
resuming. Set the same new image in `.env.production` after successful verification;
an exported environment variable overrides the env file. The backup manifest records
the configured candidate reference and retained application image IDs; use the OLD
image for rollback.
For offline archives, load the new image and set `VOXRIVA_UPGRADE_OFFLINE=1`
when calling the same upgrade script; it checks the image exists locally and skips
the registry pull.

Do not automatically run Alembic downgrade or old code on a new schema. Roll back
by restoring the pre-upgrade database AND keyring into a fresh project with fresh
Redis and the old image, verify, then switch traffic. PostgreSQL major upgrades
require a separately tested dump/import or pg_upgrade procedure. This script does
not perform them. Avoid overlapping operator migrations/backups/upgrades.

## Release artifacts and gates

Build a local candidate from reviewed source and run the isolated production
check before promotion:

```sh
bash scripts/test-production-compose.sh
bash scripts/build-release.sh 0.1.1 SOURCE_REVISION_OR_ARCHIVE_SHA256
```

The builder creates a version/revision-labelled non-root image archive, bundled
SDK wheel and frozen delivery contract, production Compose/scripts/runbooks,
license/notices, dependency metadata and checksums. The operator bundle is not a
complete development checkout. Neither command creates a repository, pushes an
image or deploys a production host. Do not overwrite a released tag/archive.

Required checks include application/library vulnerability scanning at
HIGH/CRITICAL, a completed package-metadata license inventory and application
checks bound to the exact image ID. Auth/permissions, tenant isolation, secret
handling, preview sandbox and runtime smoke categories must have actual passing
results. Supply them through VOXRIVA_APP_CHECKS_FILE; a missing/failed check does
not become passed through packaging. Frontend/SDK dependency and contract checks
remain necessary because bundled JavaScript is not a complete npm inventory.

OS vulnerability scanning is **optional advisory**, enabled with
VOXRIVA_OS_SCAN=1. Supported upstream does not mean CVE-free. Required application
findings, scanner failure or missing/mismatched evidence remain failures;
RELEASE-BLOCKED prevents promotion. APP-CHECKS-PASSED does not close ownership or
third-party redistribution review. SHA256SUMS establishes integrity when obtained
from a trusted channel, not absolute security or publication approval.

For exact-image export without rebuilding, CI can supply
VOXRIVA_EXISTING_IMAGE_ID, its original VOXRIVA_EXISTING_BUILD_INPUTS and a fresh
VOXRIVA_RELEASE_IMAGE tag. Version/revision labels must match the arguments.
The source build resolves base images to digests and records build inputs.
Python requirements and npm dependencies are version locked; Python package
artifacts are not hash locked. Preserve each candidate's own provenance and bytes.

Own code uses [MIT](LICENSE). The retained rfc3987 dependency and other upstream
components need [redistribution review](THIRD_PARTY_NOTICES.md) before a public
release. [Release status](docs/release-status.md) tracks actual artifact
availability, GHCR package namespaces, platform commitments and review inputs.
Use an approved actual image reference/digest when one exists.

## Base image updates

Dockerfile, Dockerfile.mcp and the release builder use the official Python 3.13
slim Trixie base pinned to a digest. The exact value lives in those source files.
A frozen digest does not receive automatic package updates. At least monthly
and after relevant upstream security notices, inspect the official image, review
its new digest and update all three defaults together. Build a fresh candidate,
run application dependency/security/runtime checks and use the tested upgrade
procedure. Do not mutate running containers with ad-hoc apt upgrades.

The production check exercises isolated HTTPS, local SMTP, coordinated restore,
nonempty-restore refusal and application image replacement. Local image replacement
does not establish compatibility with every prior release; rehearse an actual
old-to-new migration against a restored backup before upgrading production.
It makes no live SES/FCM delivery claim and does not use production volumes.

## Authenticator MFA and keyring backups

`VOXRIVA_MFA_POLICY` defaults to `optional`; set `required` in `.env.production`
and recreate API to require enrollment before dashboard access. Configure and back
up the full keyring first. TOTP seeds share the provider keyring: the coordinated
backup/restore above covers MFA as well. Keep old rotation keys for existing MFA
seeds. Operator recovery is local and audited; see [the MFA runbook](docs/mfa.md).

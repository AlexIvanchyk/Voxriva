# Self-host Voxriva

Run the dashboard, API and delivery workers in your infrastructure. You control
the database, provider credentials, runtime data and backups. A local SMTP setup
needs no cloud account; SES and FCM use your own provider accounts.

## Pick an installation

| Goal | Route | What you get |
| --- | --- | --- |
| Try the product and send a local email | [Quickstart](quickstart.md) | Prebuilt Compose stack, fictional workspace and Mailpit inbox |
| Develop or configure a persistent local workspace | [Configuration](configuration.md) | Local Compose or native development with explicit bootstrap and setup |
| Operate a real installation | [Production runbook](../PRODUCTION.md) | Single Linux Docker host, HTTPS, private database/broker, migrations and backup/restore tooling |

The production baseline is Docker Engine 28+ and Compose v2. Supply a hostname,
DNS and a matching TLS certificate; certificate renewal is managed outside the
stack. Production data tools need host Python 3.11+. Follow the runbook for
image preparation and secrets before starting services.

## What runs and what persists

| Component | Purpose | Operator responsibility |
| --- | --- | --- |
| Dashboard/API | Team administration, authoring and delivery requests | HTTPS ingress, access policy and protected metrics |
| PostgreSQL 17 | Content, sessions, notification/outbox records and history | Persistent storage, capacity, migrations and backup/restore |
| Redis broker | ID-only task transport | Private access and isolated transport state during restore |
| Relay, email and push workers | Dispatch and channel-specific delivery | Health checks, provider quotas and backlog monitoring |
| Encryption keyring | Decryption of credentials, retained runtime data and MFA material | Back up the complete keyring with the matching database |
| Optional MCP process | Scoped template authoring for an AI client | Matching code/database revision, credentials and transport |

Production publishes HTTPS only. Database and Redis ports stay private. Mailpit
belongs to local evaluation, and no hosted control plane or telemetry account is
required. The default Redis 7.4 image has source-available license terms; see
[license scope](release-status.md#license-scope) before choosing your stack.

## Plan capacity and maintenance

CPU, RAM, disk and throughput minima have not been benchmarked for a published
support matrix. Measure with your payload sizes, retained history and provider
limits before committing capacity. The current CI target and release boundaries
are listed in [release status](release-status.md).

This is a single-host Compose topology. Plan migration/backup/restore maintenance
windows. Workers can scale by channel; an HA database, ingress, autoscaling and
Kubernetes/Helm deployment are outside the shipped setup. External PostgreSQL or
Redis needs an explicit configuration and separately tested backup workflow;
see [external dependencies](configuration.md#external-postgresql-and-redis).

## Before using real data

Follow the production runbook to create private secrets and an administrator,
configure your provider and exact binding, publish/deploy a template and issue
an environment Delivery key. Verify readiness, a test delivery, protected metrics
and a database/keyring restore in your own deployment. Keep the runbook available
for [backup, restore and upgrades](../PRODUCTION.md).

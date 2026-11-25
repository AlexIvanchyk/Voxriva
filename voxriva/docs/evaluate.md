# Local example reference

For your first visit, follow [Run locally and send your first email](quickstart.md).
This reference covers named examples, ports, generated state and lifecycle.

The example launcher creates an isolated, source-built Compose installation with
fictional data. Use it to evaluate template contracts, deployment resolution,
provider binding and delivery history before connecting your own application.
It does not reset or seed an existing `voxriva` installation.

## Requirements and command

Docker Engine with Compose v2 must be running. The host launcher needs Python
3.10+ on macOS/Linux and no installed Python packages or Node.js. A cold build
needs network access for image/package downloads and can take several minutes.
For production requirements and supported scope, see [self-hosting](self-hosting.md)
and [release status](release-status.md).

From `voxriva/`:

```sh
python3 scripts/example.py
```

This selects a free app port starting at 18080 and a Mailpit web port starting at
18025, then persists both. Use the URLs printed by the command rather than
assuming a particular port. An independent named installation can use explicit
free ports:

```sh
python3 scripts/example.py --name integration --port 28080 --mailpit-port 28025
```

An explicit busy port fails before startup. Both web interfaces bind to loopback;
PostgreSQL, Redis and SMTP expose no host ports. The example uses its own Compose
project, image tag, network, volumes and generated credentials. It needs no Docker
socket mount and configures no external SMTP/SES/FCM credentials.

## What is configured

The fixture creates **Northstar Market / local**, the English email template
`northstar-welcome`, a published/deployed version, local Mailpit SMTP binding and
an environment Delivery key. The message contract requires `first_name` and
`account_url`; published runtime defaults provide the banner image and phone.
The fixture also includes a static logo and synthetic preview scenarios.

The launcher submits one sample through the ordinary Delivery API, transactional
outbox, relay and worker. It waits for Sent, matches the worker's SMTP message ID
to a Mailpit receipt, and verifies inline image bytes and MIME Content-ID values.
It is a real local SMTP result, not a cloud-delivery claim.

Login is in `output/example/local/access.txt`; machine-readable credentials and
IDs are in adjacent `state.json`. Named examples replace `local` in that path.
Directories are mode 0700 and private files mode 0600. Do not publish or reuse
those credentials outside the disposable example.

The dashboard is available for inspecting saved content, immutable version IDs,
active pointers, provider revisions and attempts. Changing preview data does not
send; publishing does not change a deployment. The [first API email](quickstart.md)
uses this exact fixture without a UI setup prerequisite.

## Repeat and lifecycle

Rerunning the launcher starts stopped services and verifies its original sample.
It preserves user edits and does not submit a second sample or reseed over saved
work. Interrupted setup reconciles supported API operations where possible;
it refuses conflicting binding changes rather than replacing them. An expired
or revoked key, or a deleted receipt, is reported rather than silently replayed.

```sh
python3 scripts/example.py stop
python3 scripts/example.py remove
```

`stop` preserves the example's database, broker, Mailpit, keyring and credentials.
`remove` permanently deletes only the owned example resources and generated
credentials; built images/cache remain. Use `--name integration` for a named
example. Ownership-label checks refuse absent/mismatched state and prevent
adopting an unrelated project. Keep private state until removal.

For a persistent manual installation use [configuration](configuration.md) and
[local infrastructure](local-infrastructure.md). For real HTTPS, backup/restore
and upgrades use [production](../PRODUCTION.md). The launcher implementation and
safety checks are documented in the source tooling guide at
`scripts/example/README.md`.

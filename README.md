# Voxriva

**Open-source, self-hosted email and push notifications.**

Manage templates, languages and deployments in a web dashboard. Integrate through
the HTTP API or typed Python SDK, and use MCP for AI-assisted draft editing.
Release notification content independently of your application, with delivery
data and provider credentials in your infrastructure.

**MIT license · Self-hosted · Web dashboard · HTTP API · Python SDK · MCP**

[Run locally](docs/quickstart.md) · [Dashboard](docs/dashboard.md) ·
[API & SDK](docs/journeys/integrate.md) · [MCP](docs/journeys/mcp.md) ·
[Documentation](https://alexivanchyk.github.io/Voxriva/)

- **Content releases without application releases:** preview, languages,
  immutable versions, explicit environment deployments and rollback.
- **Delivery under your control:** SMTP, Amazon SES and Firebase Cloud Messaging,
  with local data, provider credentials and no mandatory hosted control plane.
- **An integration you can inspect:** typed payloads, preflight validation,
  idempotent HTTP retries and a history of pinned revisions and delivery attempts.

[![Edit notification content alongside its rendered preview](docs/assets/screenshots/email-preview.jpg)](docs/dashboard.md)

*Edit → preview → publish → deploy in the web dashboard. Email editing uses
HTML/Jinja with a live preview.*

## Run locally

Requirements: running Docker Engine with Compose v2 and host Python 3.10+ on
macOS/Linux. Published images target **linux/amd64**; no source checkout, build,
cloud account, host Node.js or installed Python packages are needed.

Download the small operator bundle and verify its checksum:

```sh
curl -fLO https://github.com/AlexIvanchyk/Voxriva/releases/download/v0.1.1/Voxriva-0.1.1-operator.tar.gz
curl -fLO https://github.com/AlexIvanchyk/Voxriva/releases/download/v0.1.1/OPERATOR-SHA256SUMS
shasum -a 256 -c OPERATOR-SHA256SUMS
tar -xzf Voxriva-0.1.1-operator.tar.gz
cd Voxriva-0.1.1
python3 scripts/example.py
```

The launcher creates an isolated fictional workspace, verifies a welcome email in
local Mailpit, and prints dashboard/inbox URLs and a private login-file location.
Continue with [the first API request](docs/quickstart.md#load-local-credentials),
[Python sync/async or curl](docs/journeys/integrate.md), or
[AI-assisted template editing](docs/journeys/mcp.md).

For an existing application, send a template key, recipient/device token and JSON
context. The environment Delivery key selects the project and environment. See
[the HTTP contract](docs/api.md) and [self-hosting guide](docs/self-hosting.md).

## License and release status

Own code and documentation use [MIT](LICENSE). Dependencies retain their own
terms; the default stack includes source-available Redis 7.4. Version 0.1.1
is a prerelease. Published artifacts, support scope and redistribution
review are tracked in [release status](docs/release-status.md) and
[third-party notices](THIRD_PARTY_NOTICES.md).

Contributions, support, security reporting and community guidelines are available
from [the project guide](docs/community.md).

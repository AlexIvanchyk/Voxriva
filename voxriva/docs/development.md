# Development and verification

Run commands from `voxriva/`, the application root. Use Python 3.12+ and Node.js
22+. The image uses pinned Python 3.13; the separately packaged SDK declares
Python 3.10+. See [release status](release-status.md) for CI targets and
production platform commitments.

## Native development

```sh
make setup
```

This creates `.venv`, installs the server with development tools and installs the
frontend dependencies. For a reproducible frontend install from the checked-in
lockfile use `npm --prefix frontend ci --no-audit --no-fund`. Configure a dedicated
PostgreSQL database and Redis instance through `VOXRIVA_DATABASE_URL` and
`VOXRIVA_REDIS_URL`. For loopback HTTP set `VOXRIVA_SECURE_SESSION_COOKIE=false`
and `VOXRIVA_CONTAINER_MONITORING_ENABLED=false`. Configure a persistent private
Fernet keyring file with `VOXRIVA_PROVIDER_ENCRYPTION_KEY_FILE`; the generation
command and rotation rules are in the [provider guide](delivery-guide.md).
Do not use a fresh keyring with an existing database.

```sh
.venv/bin/alembic upgrade head
.venv/bin/python -m backend.app.features.identity.bootstrap --email admin@example.test
.venv/bin/uvicorn backend.app.main:app --reload
```

In another terminal run `npm --prefix frontend run dev`, then open Vite's reported
loopback URL. Vite proxies `/api`, `/health` and `/metrics` to
`http://127.0.0.1:8000`; set `VOXRIVA_DEV_API` for another API origin. Native API
startup does not launch delivery workers. Prefer the [local Compose quickstart](quickstart.md)
for the complete API, relay, email/push worker and local SMTP path.

## Reusable local example

Run `python3 scripts/example.py` for a source-built, isolated Northstar first-email
installation. It needs Docker/Compose v2 and host Python 3.10+, without the native
development setup above. The [first-email guide](quickstart.md) covers scoped
cleanup and integration. Its fixture is curated source, shared with the richer
media demo; generated credentials stay under ignored `output/example/`.

Run `python3 -m unittest discover -s scripts/example -p 'test_*.py'` for launcher
ownership, collision and interruption checks. Use a new `--name` for an actual
clean-install verification; never point mutation checks at a user's stack.

## Checks

| Command | Coverage |
| --- | --- |
| `make test` | Architecture/catalog drift, backend lint/types/tests, frontend lint/component tests/build, Compose config, SDK and frozen contract |
| `make test-backend` | Python lint, strict mypy and pytest with application coverage |
| `make test-frontend` | Frontend lint, component tests, TypeScript and production build |
| `make test-sdk` | Independent SDK lint/types/tests |
| `make test-architecture test-contract` | Feature boundaries, generated format catalog and frozen delivery contract comparison |
| `TEST_DATABASE_URL='<isolated-postgresql-asyncpg-url>' make test-postgres` | PostgreSQL row locks, concurrent acceptance/claims and recovery |
| `make test-e2e` | Sequential standard, deterministic cloud, crash recovery and clean-install SDK Compose suites |
| `make test-production-compose` | Isolated HTTPS install, local SMTP, backup/restore and image replacement drill |
| `make test-browser-matrix` | Opt-in Firefox/WebKit/mobile Chromium smoke |

Install browser binaries once with `cd frontend && npx playwright install chromium`;
install `firefox webkit` separately for the optional matrix. Set
`PLAYWRIGHT_BROWSERS_PATH` only if using a custom browser cache.

Compose wrappers own separate randomly named projects and remove their own volumes.
Default standard test ports are 18080 (API) and 18025 (Mailpit); choose unused
`VOXRIVA_TEST_PORT` and `VOXRIVA_TEST_MAILPIT_PORT` for concurrent runs and pass a
separate Playwright `--output=/absolute/path` directory. Example:

```sh
VOXRIVA_TEST_PORT=28284 VOXRIVA_TEST_MAILPIT_PORT=28225 \
  bash scripts/test-compose.sh 31-variable-formats.spec.ts --output=/tmp/voxriva-formats-e2e
```

Do not run these wrappers against a user's stack or point mutation tests at real
data. PostgreSQL fixtures use a disposable schema on a dedicated test database;
SQLite cannot prove PostgreSQL locking. Local cloud tests use transport doubles,
not live AWS/Firebase acceptance. Optional live smoke tests require separate
sandbox credentials and a test device; they are not part of ordinary local tests.

MFA, MCP credentials, images and format-specific scenarios have dedicated commands
and prerequisites in their linked guides. `make test-e2e` is not a claim that every
opt-in scenario ran. Keep claims tied to the checks actually run for the target
source/image. Update a frozen delivery contract deliberately with
`make freeze-delivery-contract`, then review API and SDK compatibility.

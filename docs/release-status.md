# Release status and compatibility

The current application, frontend and Python SDK metadata are **0.1.0**. Treat
this source as a prerelease while published artifacts, platform commitments and
dependency redistribution are being prepared. No production support SLA or
benchmark-based capacity guarantee is published.

## Where to get it

| Component | Current route |
| --- | --- |
| Source | [AlexIvanchyk/Voxriva on GitHub](https://github.com/AlexIvanchyk/Voxriva); [quickstart](quickstart.md) builds from the checkout |
| Application and optional MCP images | Build locally using the supplied tooling; GHCR is the selected future registry, with package namespaces pending |
| Python delivery SDK | Install the wheel bundled with the running application or `python -m pip install ./sdk/python` from the application directory; no PyPI publication is claimed |
| Documentation | [Public documentation](https://alexivanchyk.github.io/Voxriva/) and [local MkDocs preview](contributing/documentation.md) |

Runtime installation needs no maintainer-hosted control plane, telemetry account
or license-key activation. Cloud transports require your own provider accounts;
the local SMTP example works without them.

## License scope

Voxriva's own backend, dashboard, SDK and documentation use [MIT](../LICENSE).
You may use, modify and redistribute that code, including commercially, subject
to the license's notice requirements. Dependencies keep their upstream terms.

The shipped production Compose default is **Redis 7.4.7**. Redis 7.4 is offered
under **RSALv2 or SSPLv1**, which Redis identifies as source-available, non-open-source
licenses in its [official license table](https://redis.io/legal/licenses/).
The MIT application license does not make that default stack wholly OSI-licensed.
A different broker needs compatibility tests before being offered as an alternative.

The current runtime also includes `rfc3987` 1.3.8 under GPL-3.0-or-later. GPL is
an open-source license; its inclusion raises redistribution obligations separate
from the application's MIT declaration. Review the exact artifact, upstream
licenses, notices and any corresponding-source requirements before distributing
images. [Third-party notices](../THIRD_PARTY_NOTICES.md) tracks the open review.

## Platform and operating scope

| Area | Current scope |
| --- | --- |
| CI target | Ubuntu 24.04 x86-64, Python 3.13, Node.js 22 and pinned Chromium |
| Local example launcher | Host Python 3.10+ on macOS/Linux, Docker Engine and Compose v2; source builds may take minutes |
| Native development | Python 3.12+ and Node.js 22+; separately configured PostgreSQL/Redis |
| Delivery SDK | Python 3.10+ and HTTPX; sync and async clients |
| Production tooling | One Linux Docker host, Engine 28+, Compose v2, PostgreSQL 17, Redis and operator-supplied TLS; data tools need Python 3.11+ |
| Capacity and additional platforms | Minimum CPU/RAM, throughput, ARM64/other OS guarantees and a production support matrix have not been published |

The CI target describes configured checks, not evidence that a particular commit
passed them. Use checks and runtime evidence for the exact revision/image you
intend to deploy. [Self-hosting](self-hosting.md) describes storage and maintenance.

## API, SDK and upgrade compatibility

The checked-in [Delivery v1 OpenAPI contract](../contracts/delivery-v1.openapi.json)
covers runtime send, validation, scoped status and health operations. The Python
SDK accepts additive response fields and validates required field types and the
current status set. Dashboard management and MCP authoring are separate surfaces.

The prerelease has no blanket cross-version compatibility commitment. Contract
changes require an explicit contract update and SDK review. Record user-visible
changes, migration requirements and deprecations in the [changelog](https://github.com/AlexIvanchyk/Voxriva/blob/HEAD/CHANGELOG.md).
Keep API, MCP, relay and worker code/migrations aligned; the bundled SDK version
must match release metadata. Back up the database and complete keyring before
upgrading and follow the [upgrade/restore runbook](../PRODUCTION.md).

## Before the first public artifact release

- Set the application/MCP image namespaces and SDK distribution location.
- Complete the artifact-specific dependency and redistribution review, including
  Redis and `rfc3987`; publish required notices and source materials.
- Define and verify supported production platforms and capacity guidance.
- Build and test the exact candidate images and retain their checksums/evidence.
- Confirm GitHub issue reporting and private vulnerability reporting are available.
- Assign the documentation URL and configure the existing Pages workflow before
  publishing its static output.

Kubernetes/Helm, a provisioned HA topology, campaigns, subscriber management,
business scheduling and MCP OAuth onboarding are outside the current scope.

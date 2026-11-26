# Release status and compatibility

Application, frontend and Python SDK metadata are **0.1.1**. This is a
prerelease. Container/SDK publication is being verified; the existing
[source prerelease 0.1.0](https://github.com/AlexIvanchyk/Voxriva/releases/tag/v0.1.0)
remains available. No production support SLA or measured capacity guarantee is published.

## Where to get it

| Component | Distribution |
| --- | --- |
| Source | [AlexIvanchyk/Voxriva on GitHub](https://github.com/AlexIvanchyk/Voxriva) |
| Application | `ghcr.io/alexivanchyk/voxriva:0.1.1` — candidate, publication pending |
| MCP | `ghcr.io/alexivanchyk/voxriva-mcp:0.1.1` — candidate, publication pending |
| Operator download | `Voxriva-0.1.1-operator.tar.gz` — publication pending; [quickstart](quickstart.md) |
| Python delivery SDK | `voxriva-sdk==0.1.1` — TestPyPI/PyPI publication pending; a matching wheel is bundled with the application |
| Documentation | [Public documentation](https://alexivanchyk.github.io/Voxriva/) |

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

The runtime uses jsonschema's supported `format-nongpl` extra with
`rfc3986-validator`, `rfc3987-syntax` and Lark for URI/IRI validation; `rfc3987`
is not part of the 0.1.1 runtime lock. Exact installed dependency notices, source
archives, upstream URLs/checksums and available native SBOMs are retained under
`/app/release-metadata/third-party` in each image and in candidate artifacts.
See [third-party notices](../THIRD_PARTY_NOTICES.md) for scope and upstream terms.
These materials document the distributed components; they are not a blanket legal opinion.

## Platform and operating scope

| Area | Current scope |
| --- | --- |
| CI target | Ubuntu 24.04 x86-64, Python 3.13, Node.js 22 and pinned Chromium |
| Local example launcher | Host Python 3.10+ on macOS/Linux, Docker Engine and Compose v2; downloaded images target linux/amd64 |
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

## Verification

Release candidates require full source checks, exact-image runtime tests,
HIGH/CRITICAL application dependency scans, dependency inventories and checksums.
A separate public-consumer run checks anonymous pulls, startup from the operator
download and an SDK installed from PyPI sending sync/async SMTP mail. Publication
and that final consumer check remain pending until their actual results are linked here.

Kubernetes/Helm, a provisioned HA topology, campaigns, subscriber management,
business scheduling and MCP OAuth onboarding are outside the current scope.

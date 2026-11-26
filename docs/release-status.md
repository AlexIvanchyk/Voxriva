# Release status and compatibility

The application, frontend and Python SDK source are version **0.2.0**. See the
[0.2.0 source prerelease notes](releases/0.2.0.md) for changes and upgrade steps.

The published images, operator bundle and PyPI SDK listed below are **0.1.1**.
The images target **linux/amd64**. No production support SLA or measured capacity
guarantee is published. The earlier source-only 0.1.0 release remains available.

## Where to get it

| Component | Distribution |
| --- | --- |
| Source | [0.1.1 release](https://github.com/AlexIvanchyk/Voxriva/releases/tag/v0.1.1) and [tagged source](https://github.com/AlexIvanchyk/Voxriva/tree/v0.1.1) |
| Application | [`ghcr.io/alexivanchyk/voxriva:0.1.1`](https://github.com/AlexIvanchyk/Voxriva/pkgs/container/voxriva), public |
| MCP | [`ghcr.io/alexivanchyk/voxriva-mcp:0.1.1`](https://github.com/AlexIvanchyk/Voxriva/pkgs/container/voxriva-mcp), public |
| Operator download | [Voxriva-0.1.1-operator.tar.gz](https://github.com/AlexIvanchyk/Voxriva/releases/download/v0.1.1/Voxriva-0.1.1-operator.tar.gz) and [checksum](https://github.com/AlexIvanchyk/Voxriva/releases/download/v0.1.1/OPERATOR-SHA256SUMS); [quickstart](quickstart.md) |
| Python delivery SDK | [`voxriva-sdk==0.1.1` on PyPI](https://pypi.org/project/voxriva-sdk/0.1.1/); the matching version is also bundled with the application |
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

The [full candidate checks](https://github.com/AlexIvanchyk/Voxriva/actions/runs/45886294396)
passed, including all six E2E suites, exact-image runtime tests, HIGH/CRITICAL
application dependency scans, dependency inventories and checksums. The
[publishing run](https://github.com/AlexIvanchyk/Voxriva/actions/runs/45889311038)
promoted those same image IDs without rebuilding. The release's
`published-digests.json` records immutable registry digests and image IDs.

The [SDK publication](https://github.com/AlexIvanchyk/Voxriva/actions/runs/45889314935)
used the same wheel/sdist through TestPyPI and PyPI, verified their index hashes,
and passed clean installation checks on Python 3.10 and 3.13. The SDK source tree
was unchanged from its original successful candidate.

The [public consumer check](https://github.com/AlexIvanchyk/Voxriva/actions/runs/45889970570)
passed: anonymous pulls, startup from the operator download without a source
checkout, and a PyPI-installed SDK sending sync/async mail to local SMTP. The
three received messages (launcher, sync and async) and the SDK idempotent replay
were verified; repeating the SDK operation created no duplicate mail.

Kubernetes/Helm, a provisioned HA topology, campaigns, subscriber management,
business scheduling and MCP OAuth onboarding are outside the current scope.

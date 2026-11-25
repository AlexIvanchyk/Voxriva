# GitHub automation prepared for review

These workflows belong at the repository root. Application commands run inside
`voxriva/`; the source tree is not moved or flattened. Preparing these files does
not approve a release or configure any external repository, registry or Pages site.

## Pull requests and branch pushes

`workflows/ci.yml` runs on pull requests, branch pushes, manual dispatch and as a
reusable workflow for release preparation. Its token has only `contents: read`.
Checkout credentials are not persisted. It never pushes images, uses account
secrets or requires live SES/FCM credentials or devices.

Jobs:

- `changes`: compares the PR base or push predecessor with the checked-out SHA.
  Only documentation paths skip runtime jobs. Renames are treated as a deletion
  plus an addition; missing history, new branches and manual/release runs require
  full checks.
- `workflow-policy`: actionlint, ShellCheck and the stdlib release-helper tests.
- `docs`: strict Material for MkDocs build with the documentation toolchain in
  `voxriva/requirements-docs.lock`; retains the generated site for seven days.
- `backend`: runtime/MCP locks, dependency consistency, Ruff, strict mypy,
  architecture rules, generated format registry, frozen delivery contract, SDK
  checks and backend tests with a dedicated PostgreSQL 17 service. Successful
  security cases produce a small source evidence artifact.
- `frontend-security`: ESLint, Vitest, TypeScript/Vite build, mandatory npm audit
  (HIGH/CRITICAL), pip-audit of both application locks, and Compose schema checks.
- `trivy`: mandatory HIGH/CRITICAL library vulnerability scan of the npm and
  Python lockfiles, including the custom `requirements-*.lock` names. The pinned
  scanner sees a read-only source mount and no Docker socket; secret scanning is
  separate from this dependency check.
- `e2e`: six isolated suites, at most two simultaneous jobs: full Chromium UI
  (including saved image and variable-format delivery tests), cloud doubles,
  worker crash, clean SDK installation/delivery, MCP PostgreSQL/HTTP/stdio, and
  dashboard management credentials. Each job has its own runner/Docker daemon;
  wrappers use disposable Compose project names, loopback ports and volumes.
- `ci-ready`: stable required-check target; accepts runtime skips only when
  `changes` proved that the diff contains documentation alone. All other failed,
  cancelled or unexpectedly skipped checks block it.

The initial CI configuration is Ubuntu 24.04 x86-64, Python 3.13, Node 22 and
Playwright's pinned Chromium. This does not establish support for other CPU
architectures, operating systems or browsers. No additional browser matrix is
silently enabled.

Raw browser traces, screenshots and test stdout are not uploaded: disposable
issued credentials can appear in them. E2E artifacts contain suite/revision/exit
status only. Source evidence includes fixed passing test names, not runtime data.
The portable MCP-key CI wrapper runs the existing Compose and Playwright scenario;
the original local wrapper currently uses a macOS-specific temporary directory.

## Release candidates and GHCR

`workflows/release.yml` has only a manual trigger. Required inputs are `version`
(without `v`), `application_package` and `mcp_package` (distinct lowercase
`<owner>/<package>` paths). The namespace must belong to the workflow repository
owner. There are no invented account/package defaults. The version must match
the application, frontend and SDK metadata, including the bundled wheel contract.

With `publish=false` (default), the workflow runs full reusable CI, builds fresh
application and MCP images for the selected commit, and tests the exact images:

- application: production HTTPS/sign-in/local SMTP plus database/keyring restore
  and image replacement;
- MCP: the saved PostgreSQL/HTTP/stdio protocol scenario against the built image.

Both images use the digest-pinned stable Python 3.13/Debian Trixie base. Node's
build-stage tag is resolved once to a digest and recorded. Version, source revision
and repository source labels are retained. Required library vulnerability and
license-inventory scans read exported image archives; the third-party Trivy
container receives no Docker socket. No OS scan runs by default. OS findings
remain optional/advisory, never a zero-CVE release gate.

The existing application builder/finalizer is used without bypassing its gates.
Security evidence identifies source tests at the same revision; runtime evidence
identifies the exact image's successful smoke run. This is not a complete
source-code or exploitability audit. MCP receives the same application-focused
finalization policy. Indexed candidates are never rewritten.

The artifact contains application/MCP Docker archives, the SDK wheel and frozen
contract extracted from the application image, dependency/license reports,
release metadata, build inputs, source/security/runtime evidence, MIT license and
available third-party notices. An outer `SHA256SUMS` covers the bundle and its
unchanged inner indexes. Historical local release directories are never inputs.
Artifacts expire after 14 days; a workflow artifact is not a published release.

Publishing additionally requires:

1. An explicit `publish=true` dispatch from the matching `vVERSION` tag.
2. Successful preparation of this run's images and evidence.
3. The `ghcr-publish` environment; configure its reviewers/tag policies before use.
4. Owner-approved package names, platform scope and redistribution review.

Only the separate `publish` job has `packages: write`. It verifies this run's
checksums, version/revision, image IDs and target names before authentication,
loads the already tested archives, then pushes version tags using `GITHUB_TOKEN`.
It never rebuilds an image in the privileged job. Only registry manifest HTTP 404
counts as an absent version; auth/network errors block publication. Existing
version tags are refused. Registry pushes are not transactional: a second-image
failure can leave the first published; there is no destructive automatic rollback.
Separate digest evidence records completed pushes, including partial outcomes.
The preflight is not a registry-side immutability guarantee against external actors.

## GitHub Pages

`workflows/pages.yml` is separate from image publishing. A manual `deploy=false`
run builds a strict Pages preview without reading or requiring a configured Pages
site. Manual runs require the selected ref to be the actual default branch.

Making the repository public and subsequent documentation pushes on its default
branch trigger automatic builds. They deploy when an existing Pages site is
available; otherwise they retain a preview and put setup instructions in the run
summary. Private repository pushes skip this workflow's jobs. A manual
`deploy=true` fails clearly when Pages is unavailable or not configured. Untrusted
PRs never trigger deployment or receive a Pages/OIDC write token.

After the repository is public, set **Settings → Pages → Build and deployment →
Source → GitHub Actions** once, then dispatch with `deploy=true` or push a docs
change. Private repository Pages requires an eligible GitHub plan; this workflow
never changes repository visibility or plan. Configure the `github-pages`
environment to permit only the default branch and any required reviewers.

Only deployment requests call `configure-pages` (`enablement: false`) to read the
real configured URL. Automatic enablement requires credentials beyond the
workflow token and is deliberately not attempted. The strict build receives the
real URL through `VOXRIVA_DOCS_SITE_URL` when available. Its token has only
`contents: read`; the separate configuration job adds `pages: read`, and only
deployment has `pages: write` and `id-token: write`. The official upload/deploy
actions use this run's generated documentation artifact.

## Source-only GitHub prerelease

`workflows/source-release.yml` runs manually with version `0.1.0` and defaults to
`publish=false`. It requires matching application/frontend/SDK metadata, runs the
full reusable CI (including audits, Trivy and E2E), then uses `git archive` for
source `.tar.gz` and `.zip` files from that exact tested commit. Release notes come
from the tracked `voxriva/docs/releases/VERSION.md` at the same commit; source-relative
prose links become absolute links to that release tag, while code is preserved. An index
covers both archives, notes and workflow provenance. Common local/generated paths,
real environment files, symlinks and submodules are refused; review source for
secrets before its first commit because this path check is not a content scanner.

After reviewing a successful candidate, create/push the matching `vVERSION` tag
and dispatch from that tag with `publish=true`. Only the `publish` job/environment
`source-release` has `contents: write`. It verifies the downloaded artifact's
checksums, exact file list and run/commit provenance before authenticating to `gh`,
requires the remote tag to still point at the tested commit, and creates a
prerelease that is not marked latest.
Existing releases are refused; authentication/network failures never count as
absence. It does not rebuild source, publish images, distribute dependency wheels
or claim completion of the separate image redistribution prerequisites. Release
creation/uploads are not atomic, so inspect failures before retrying.

## Local validation and action maintenance

From the workspace root:

```sh
bash .github/scripts/lint-workflows.sh
```

The helper downloads actionlint 1.7.12 over HTTPS and verifies its fixed SHA256
before execution (Linux x86-64 or macOS arm64). CI also requires ShellCheck, which
is present in the selected hosted runner; local ShellCheck is used when installed.
Helper tests use fictional temporary fixtures and mocked registry calls. They do
not create a Git repository, run Docker builds, publish packages or contact GHCR.

All top-level actions are official GitHub actions pinned to full commit SHAs;
version comments identify the reviewed releases. Review upstream code and
transitive composite-action dependencies when updating pins. Relevant official
references: [least privilege and immutable action pins](https://docs.github.com/en/actions/reference/security/secure-use),
[GHCR authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry),
[custom Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages),
[Pages artifact action](https://github.com/actions/upload-pages-artifact), and
[actionlint usage](https://github.com/rhysd/actionlint/blob/main/docs/usage.md).

Local syntax/helper validation is separate from the final integrated runtime
checks. Inspect the exact commit's GitHub run and the deployed URL before reporting
a successful release or Pages deployment.

# Changelog

User-visible changes, compatibility breaks, migration requirements and deprecations
are recorded here. Releases remain prereleases; see
[release status](docs/release-status.md) for actual artifact availability.

## Unreleased

## 0.1.1 — container and SDK distribution

- Versioned linux/amd64 application and MCP images, promoted from the exact tested candidate.
- An operator download that starts the local email example without a checkout or build.
- Python SDK wheel and sdist, clean installation checks on Python 3.10/3.13 and OIDC publishing through TestPyPI to PyPI.
- Retained dependency notices/source inventories in both images; jsonschema uses its supported `format-nongpl` extra for URI/IRI validation.

No database migrations or Delivery v1 contract changes. See
[release notes](docs/releases/0.1.1.md).

## 0.1.0 — source prerelease

This release distributes source code and operator documentation. It does not
announce published container images, a PyPI package or a running production
installation. See [release notes](docs/releases/0.1.0.md).

### Added

- A repository-root product README with local setup and a Python delivery example.
- Dashboard, MCP walkthrough, self-hosting and release/compatibility guides.
- Contribution, support, security and community guidelines, plus issue/PR templates.
- CI, an explicit source-prerelease workflow, separate gated GHCR publication and
  documentation Pages deployment workflows.

### Changed

- The documentation landing page now leads with product benefits, dashboard,
  API/SDK/MCP entry points and a local-start route.
- Local onboarding now covers source checkout, dashboard/inbox inspection,
  the first API request and scoped cleanup in one quickstart.
- Detailed capabilities and runtime topology have dedicated reference routes.
- License scope now explicitly distinguishes MIT own code from Redis 7.4 and
  other third-party redistribution requirements.

### Release preparation

Public artifact namespaces, production platform commitments and dependency
redistribution review remain open. See [release status](docs/release-status.md).

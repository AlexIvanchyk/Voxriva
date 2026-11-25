# Changelog

User-visible changes, compatibility breaks, migration requirements and deprecations
are recorded here. The current 0.1.0 source is a prerelease; this file does not
announce a published package or production release.

## Unreleased

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

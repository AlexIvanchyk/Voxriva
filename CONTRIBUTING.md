# Contributing to Voxriva

Code, documentation, reproducible bug reports and integration feedback are welcome.
Use [GitHub issues](https://github.com/AlexIvanchyk/Voxriva/issues) to describe a
problem or discuss a substantial proposal before investing in a large change.
Small fixes can go directly to a pull request. Follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Get a working environment

The repository root contains the application, community files and `.github/`.
Run application commands from this root.

```sh
git clone https://github.com/AlexIvanchyk/Voxriva.git
cd Voxriva
```

To try the product, use [the isolated quickstart](docs/quickstart.md).
For code changes, follow [native development and verification](docs/development.md)
for Python, Node.js, PostgreSQL, Redis and encryption-keyring setup. Never point
mutation tests at an existing installation or real application data.

## Prepare a pull request

1. Describe the concrete problem and expected behavior. Keep the change focused.
2. Update user documentation when behavior or configuration changes. Keep the
   Delivery contract and SDK aligned for runtime API changes.
3. Run the checks relevant to the change. From the application directory,
   `make test` covers the principal backend, frontend, SDK and contract checks;
   PostgreSQL, Compose and browser suites have additional prerequisites in the
   development guide. For prose-only changes, run the strict docs build below.
4. Describe the result, validation performed and material limitations in the PR.
   Include a sanitized screenshot when changing a user-facing screen.

Use synthetic examples and keep secrets, database dumps, generated credentials,
raw traces and local release archives out of commits. If a check could not run,
state that explicitly rather than treating it as passed.

## Documentation changes

From the repository root, install the isolated pinned documentation toolchain and build:

```sh
python3 -m venv /tmp/voxriva-docs-venv
/tmp/voxriva-docs-venv/bin/python -m pip install -r requirements-docs.lock
/tmp/voxriva-docs-venv/bin/python -m mkdocs build --strict --site-dir /tmp/voxriva-docs-site
```

Use [the documentation guide](docs/contributing/documentation.md) for
preview, navigation and desktop/mobile review. Keep the landing page readable in
one minute: product, benefits, dashboard, API/SDK/MCP and the local-start route
must be visible before architectural detail. Use existing real demo screenshots.

## Review, licensing and coordination

Maintainers review changes, request revisions and decide what to merge.
The repository owner [@AlexIvanchyk](https://github.com/AlexIvanchyk) coordinates
project decisions and releases through GitHub. No formal elected governance or
guaranteed review time is currently established.

Submit only work you have the right to contribute under the project's [MIT license](LICENSE).
Identify third-party code/assets and their license/provenance explicitly; they
keep their upstream terms. See [third-party notices](THIRD_PARTY_NOTICES.md)
and [release status](docs/release-status.md) before changing distributed
dependencies or proposing release artifacts.

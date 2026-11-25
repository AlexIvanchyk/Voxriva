# Build and maintain the documentation

The documentation uses **Material for MkDocs 9.7.7** on **MkDocs 1.6.1**, with
Python 3.13 for the checked docs toolchain. `requirements-docs.lock` pins resolved
documentation dependencies separately from server/SDK runtime requirements.
No runtime dependency is installed or changed by a docs build.

## Build and preview locally

Run from the repository root:

```sh
python3.13 -m venv /tmp/voxriva-docs-venv
/tmp/voxriva-docs-venv/bin/python -m pip install -r requirements-docs.lock
/tmp/voxriva-docs-venv/bin/python -m mkdocs build --strict
/tmp/voxriva-docs-venv/bin/python -m mkdocs serve --dev-addr 127.0.0.1:8008
```

Open `http://127.0.0.1:8008/`. Build output is `build/docs/`, already covered by
the repository's `build/` ignore rules. To choose a different output directory:

```sh
/tmp/voxriva-docs-venv/bin/python -m mkdocs build --strict --site-dir /tmp/voxriva-docs-site
```

The build requires only source documentation and docs dependencies; it does not
start Compose, read deployment secrets, migrate a database or contact a provider.
Search, theme scripts, fonts and branding are local. There are no analytics,
remote widgets or CDN assets. The system font stack avoids remote font requests.
The source-link override in `docs/overrides/partials/source.html` retains the
GitHub link without Material's live repository-statistics requests.

## Canonical content and navigation

Edit user-journey pages under `docs/journeys/`; edit detailed contracts in the
existing guides beside them. `mkdocs.yml` owns navigation, search, admonitions
and linked code tabs. The repository-root application README introduces the product
on GitHub and serves source/release users. Keep its core claims aligned with the
documentation home.

The landing page leads with the product, three benefits, dashboard and API/SDK/MCP
entry points, a real product screenshot and a local-start route. Detailed
capabilities live in `capabilities.md`; runtime topology belongs to
`journeys/model.md`. The quickstart is the main first-run path; `evaluate.md`
documents launcher details rather than a competing tutorial.

`docs/_hooks/canonical.py` exposes an explicit allowlist of existing production,
MCP, SDK, license and root community documents as virtual MkDocs pages. It rewrites their
source-relative links for the site. No competing copies of those guides are
checked in. Contract JSON files, the infrastructure SVG and the existing Voxriva logo are
allowlisted assets. PUBLIC_SCREENSHOTS selects the five existing product frames
used by the guides; other original captures remain in source but are not copied
into the generated site. The source README remains a short product landing page and maps to the
site home when linked from a guide.

Internal QA/history/design reports, image archives, environment files,
application sources, databases and secret directories are not scanned or copied
into the site. Links to source-only non-Markdown artifacts become readable
source paths. Unknown Markdown links remain subject to strict build validation.
Keep evidence records in the secondary reference section, not the first tutorial.
Internal reports and planning documents stay outside docs/ in ignored local
archives. They are not canonical imports, navigation entries, search records or
site downloads. Keep public content limited to the product, contracts, operation
and useful contributor instructions.

After a docs edit, run the strict build and check HTML links/assets, search,
primary navigation and a narrow viewport. Audit content appropriateness as well
as link validity. Use the existing real screenshots selectively.

## Review the first minute

Keep the product definition, MIT-own-code/self-hosting scope, dashboard, API,
Python SDK, MCP and a start link in the opening section. Put detailed transport,
replication and operational contracts on their reference routes. Examples must
name their URL/key, SDK-install and deployed-template prerequisites.

For a reader check, give 3–5 developers the landing page for 60 seconds, then ask:

1. What is Voxriva and which application problem does it solve?
2. Which two benefits would matter in your own integration?
3. What can a team do in the dashboard, and what can an AI client do through MCP?
4. Which application integration options exist?
5. Where would you start a local evaluation, and what prerequisites are needed?

Record misunderstandings and whether the developer wants to try it. A successful
build or an automated word count does not establish that this reader check passed.

## GitHub Pages handoff

The CI workflow is maintained separately. Its build contract is:

1. Use Python 3.13 and install `requirements-docs.lock` from the repository root.
2. Set `VOXRIVA_DOCS_SITE_URL` to the **actual** Pages base URL, including the
   repository subpath when applicable.
3. Run `python -m mkdocs build --strict --config-file mkdocs.yml` from the
   repository root. The configured artifact directory is `build/docs/`.
4. Publish that static directory only through the owner's configured Pages
   workflow after publication is requested. This task performs no deploy.

For local subpath verification, use a temporary fictional base:

```sh
VOXRIVA_DOCS_SITE_URL='http://127.0.0.1:8008/example-repository/' \
  /tmp/voxriva-docs-venv/bin/python -m mkdocs build --strict --site-dir /tmp/voxriva-docs-subpath
```

`site_url` defaults to the local preview URL until hosting is assigned. `repo_url`
uses the owner-provided `AlexIvanchyk/Voxriva` GitHub repository. No live Pages
address, custom domain or public package namespace is assumed.
Do not run `mkdocs gh-deploy` during local validation: it writes/pushes a publishing
branch. The [official Material publishing guide](https://squidfunk.github.io/mkdocs-material/publishing-your-site/)
explains branch publishing; an artifact-based Pages workflow can publish the
same static output with its own configured permissions and deployment environment.

## Maintain the build dependencies

`requirements-docs.in` lists the direct dependencies. Refresh the isolated docs
environment deliberately, record the full resolved pins in
`requirements-docs.lock`, and rerun build/search/viewport checks. The lock is a
version lock rather than a hash-locked supply-chain attestation. Check platform
compatibility before claiming additional docs-build platforms.

Material 9.7 is in its final maintenance period; the upstream
[security policy](https://github.com/squidfunk/mkdocs-material/blob/master/SECURITY.md)
states an end-of-life date of May 5, 2027. The requested Material implementation
is retained here. Before that date, review the maintained successor and plugin
compatibility as an explicit follow-up; do not silently change the documentation
framework. Ordinary Markdown and the small allowlisted hook keep that review
bounded.

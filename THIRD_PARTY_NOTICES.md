# Third-party licenses and source materials

Voxriva's own code and documentation use [MIT](LICENSE). Dependencies, raster
codecs, data, browser assets and base/service images retain their upstream
copyrights and terms. The application image is not an MIT-only distribution.

## What accompanies the images and candidate

The application and MCP image builds run `scripts/collect-third-party.py`
against their actual installed, locked packages. They retain the result at
`/app/release-metadata/third-party/python/`; the application also retains the
dashboard production dependency bundle at `third-party/frontend/`. Candidate
packaging extracts these directories from the same tested images.

Each bundle includes original installed and source-archive license/NOTICE texts,
exact upstream source archives, source URLs, SHA256 values, package versions,
and `SHA256SUMS`. The Python bundle also preserves wheel SBOMs and native-library
file hashes. A completed `inventory.json` requires actual notices and sources;
package-metadata license names alone do not complete collection. Check the
bundle's `SHA256SUMS` before using its contents. Collection failure blocks the
image build; candidate checksum verification is separate from security scans.

| Component | Retained terms and source material |
| --- | --- |
| JSON Schema formats | `jsonschema[format-nongpl]` 4.26 uses MIT `rfc3987-syntax` and Lark for IRI validation and MIT `rfc3986-validator` for URI validation. This is jsonschema's [supported extra](https://github.com/python-jsonschema/jsonschema/blob/v4.26.0/pyproject.toml), with IRI support introduced in [4.25](https://github.com/python-jsonschema/jsonschema/blob/v4.26.0/CHANGELOG.rst). The GPL `rfc3987` package is absent from the runtime lock; standard URI/IRI vectors and validator registration are checked in CI. |
| certifi and fqdn | MPL-2.0 notices and exact unmodified PyPI source archives are included. Certifi's upstream notice identifies the Mozilla root-certificate data provenance. |
| phonenumbers | Apache-2.0 notices and the exact source archive, including numbering data/provenance, are included. |
| Pillow 13 and native codecs | The installed wheel's combined license text, wheel SBOMs, exact Pillow source, and checksum-pinned codec source supplements are included. These preserve the Pillow/PIL MIT-CMU notices and the upstream JPEG, PNG, TIFF, WebP, OpenJPEG, FreeType, HarfBuzz, Brotli, XCB, AVIF and compression-library notices. **This software is based in part on the work of the Independent JPEG Group. Portions of this software are copyright the FreeType Project.** The FreeType License alternative is used. Pillow's own FriBiDi loader shim is included in its source; a FriBiDi library implementation and GPL libimagequant are not supplied by the selected upstream manylinux wheel. |
| cryptography and native Rust/OpenSSL components | Apache-2.0 is selected for cryptography; both original alternative texts remain retained. The installed wheel SBOM identifies the bundled OpenSSL source URL/checksum and required Rust crates. Those archives and their notices are included. Required native dependencies for pydantic-core and rpds-py are collected from their own wheel SBOMs; excluded build/test crates are not represented as shipped runtime components. |
| packaging and python-dateutil | Apache-2.0 is selected for packaging and BSD-3-Clause for python-dateutil; the original alternative license texts and exact sources remain included. |
| greenlet and typing_extensions | Their complete installed/source license texts are retained, including greenlet's PSF-derived portions. Their terms are not reduced to one metadata label. |
| Dashboard and DOMPurify | Only the installed production npm dependency closure is collected, conservatively including code that the bundler may remove. Original license texts, package attribution and integrity-verified npm source archives accompany it. Apache-2.0 is selected for DOMPurify; its original dual-license notice remains retained. Packages publishing only MIT attribution in package.json/README retain those originals alongside the MIT terms. |
| Documentation | Its separate theme/browser/icon notices are retained under `docs/assets/licenses/`; see [documentation asset licenses](docs/documentation-licenses.md). These are separate from the runtime image inventory. |
| Python and Debian base | The images inherit the pinned official Python/Debian base. CPython source and license texts, Debian installed copyright/common-license texts, and exact Debian binary/source package versions and snapshot source locations are retained. Debian base packages are not rebuilt by Voxriva. The base-image digest remains part of candidate build provenance. |

The pinned Pillow codec supplements are recorded in
`scripts/licenses/native-sources.json`. Vendored Pillow sources and patches remain
in its original source archive/SBOM. Updating Pillow or changing the image's
platform requires reviewing this mapping against the new wheel. The collector
does not claim that every optional component named by an upstream generic SBOM
is installed; the wheel's native file inventory identifies the delivered files.

## Redis and other separately pulled services

Production Compose references **Redis 7.4.7** as a separate upstream service
image. The application and MCP Dockerfiles are based on Python, and candidate
packaging saves only those application/MCP images. **Redis server binaries or a
Redis image archive are not included in those archives.** The MIT `redis` Python
client is a separate component and does not relicense the server.

Redis 7.4 is offered under [RSALv2 or SSPLv1](https://redis.io/legal/licenses/),
which are source-available terms. Operators obtain that image separately and
must evaluate their selected terms for their use and any subsequent server-image
redistribution. The same separation applies to upstream PostgreSQL, Caddy and
local demo Mailpit images: Compose contains references, not redistributed image
archives. No replacement broker or compatibility claim is introduced here.

This page records distribution scope, selected offered license alternatives and
retained materials. It is not a legal opinion, an assurance about all downstream
uses, or a complete source/security audit. Generated candidate inventories and
their checksums establish what actually accompanied that version's images.

# Third-party licenses and redistribution

Voxriva's own code and documentation use [MIT](LICENSE), attributed to Voxriva
contributors. Dependencies, raster codecs, data and container base/service images
retain their upstream copyrights and license terms. The own-code declaration
does not relicense everything in an image or generated documentation site.

The resolved dependency sources are `pyproject.toml`, `requirements-runtime.lock`,
`requirements-mcp.lock`, `sdk/python/pyproject.toml`, `frontend/package-lock.json`
and `requirements-docs.lock`. Compare the exact distributed artifact with those
inputs and preserve its applicable license/NOTICE/source provisions. Metadata
alone is not a complete redistribution notice bundle or legal clearance.

## Items requiring redistribution review

| Component | Recorded terms / scope | Review required |
| --- | --- | --- |
| rfc3987 1.3.8 | GPL-3.0-or-later; [upstream release](https://pypi.org/project/rfc3987/1.3.8/) | The current runtime retains this JSON Schema IRI dependency. Resolve its inclusion/distribution obligations before redistribution; do not describe the image as MIT-only. |
| certifi / fqdn | MPL-2.0 package metadata | Preserve the applicable notices and source availability for the exact shipped versions. |
| phonenumbers | Apache-2.0; [upstream license](https://github.com/daviddrysdale/python-phonenumbers/blob/dev/LICENSE) | Retain license and numbering-data provenance. |
| Pillow and bundled codecs | PIL/Pillow MIT-CMU lineage; [upstream license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) | Verify the actual pinned wheel's license and native codec/library notices; retain original attributions. |
| cryptography, packaging, python-dateutil, greenlet, typing_extensions | Multi-license/Apache/BSD/PSF terms in package metadata | Review applicable choices and bundled native components; separate metadata rows do not by themselves establish a choice. |
| DOMPurify | MPL-2.0 OR Apache-2.0; [upstream license](https://github.com/cure53/DOMPurify/blob/main/LICENSE) | Record the applicable choice and retain required notices. |
| Frontend build/data packages | Includes MIT, BSD, ISC, Apache, CC-BY-4.0, Python-2.0 and MIT-0 metadata | Distinguish build-only dependencies from redistributed content and preserve attribution where included. |
| Optional MCP and documentation toolchains | Separately resolved packages; Material/MkDocs theme/static assets | Review those artifacts separately from the main runtime and preserve bundled notices. |
| Redis 7.4.7 production default | RSALv2 OR SSPLv1; [official version/license table](https://redis.io/legal/licenses/) | These are source-available, non-open-source licenses. The default stack is not wholly OSI-licensed; review the actual server image and selected terms independently of the MIT redis-py client. A replacement broker requires compatibility tests. |
| Python/Debian, PostgreSQL, Redis, Caddy and demo Mailpit images | Exact upstream tags/digests and their terms | Review each distributed image; the Python Redis client's MIT label does not describe a Redis server image. |
| Plugins and supplied assets | Plugin/asset-specific provenance | Confirm redistribution rights. Original fictional Northstar artwork is separate from third-party brand material. |

The current release must include the applicable upstream texts/notices and any
required corresponding source according to a reviewed distribution plan. This
page records a concrete open dependency issue; it does not claim a completed
source-license audit. Optional OS vulnerability scanning is a separate security
policy from license obligations.

See [release status](docs/release-status.md) for artifact availability, package
namespaces, platform commitments and outstanding redistribution prerequisites.
An inventory or documentation build does not complete artifact-specific review.

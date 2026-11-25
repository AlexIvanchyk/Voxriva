"""Expose allowlisted canonical guides without copying or indexing the source tree."""

import posixpath
import re
import shutil
from pathlib import Path
from urllib.parse import unquote, urlsplit

from mkdocs.structure.files import File

ROOT = Path(__file__).resolve().parents[2]
# Only these files outside docs/ are published. Never walk release/, output/, env
# files, local databases, secret directories or the application source tree.
CANONICAL = {
    "production.md": ROOT / "PRODUCTION.md",
    "mcp.md": ROOT / "MCP.md",
    "sdk.md": ROOT / "sdk/python/README.md",
    "reference/provider-plugin.md": ROOT / "examples/provider-plugin/README.md",
    "third-party.md": ROOT / "THIRD_PARTY_NOTICES.md",
    "license.md": ROOT / "LICENSE",
    "contributing.md": ROOT / "CONTRIBUTING.md",
    "support.md": ROOT / "SUPPORT.md",
    "security.md": ROOT / "SECURITY.md",
    "code-of-conduct.md": ROOT / "CODE_OF_CONDUCT.md",
    "changelog.md": ROOT / "CHANGELOG.md",
}
DOWNLOADS = {
    "contracts/delivery-v1.openapi.json": ROOT / "contracts/delivery-v1.openapi.json",
    "contracts/image-v1.schema.json": ROOT / "contracts/image-v1.schema.json",
    "assets/brand/voxriva-logo.png": ROOT / "frontend/src/assets/voxriva-logo.png",
}
PUBLIC_SCREENSHOTS = {
    "email-preview.jpg", "deployments.jpg", "delivery-details.jpg",
    "payload-image-override.jpg", "mfa-status.jpg",
}
ORIGINS = {}
DESTINATIONS = {}
LINK = re.compile(r"(?P<image>!?)\[(?P<label>[^\]]+)\]\((?P<target>[^)]+)\)")


def on_files(files, config):
    ORIGINS.clear()
    DESTINATIONS.clear()
    for file in list(files):
        if (
            file.src_uri.startswith("assets/screenshots/")
            and Path(file.src_uri).name not in PUBLIC_SCREENSHOTS
        ):
            files.remove(file)
            continue
        if file.is_documentation_page() and file.abs_src_path:
            path = Path(file.abs_src_path).resolve()
            ORIGINS[file.src_uri] = path
            DESTINATIONS[path] = file.src_uri
        elif file.abs_src_path and file.src_uri.startswith("assets/licenses/"):
            DESTINATIONS[Path(file.abs_src_path).resolve()] = file.src_uri
        elif file.abs_src_path and file.src_uri.startswith(
            ("assets/screenshots/", "assets/diagrams/")
        ):
            # Curated, reviewed demo media is already inside docs/. Raw captures
            # and private seeding state remain outside the publication allowlist.
            if Path(file.src_uri).suffix.lower() in {
                ".jpg", ".png", ".webp", ".svg"
            }:
                DESTINATIONS[Path(file.abs_src_path).resolve()] = file.src_uri
    for uri, source in {**CANONICAL, **DOWNLOADS}.items():
        if not source.is_file():
            raise FileNotFoundError(f"Missing canonical documentation input: {source}")
        if uri in CANONICAL:
            content = source.read_text()
            if uri == "license.md":
                content = "# MIT license\n\n" + content
            files.append(File.generated(config, uri, content=content))
            ORIGINS[uri] = source.resolve()
        else:
            files.append(File.generated(config, uri, abs_src_path=str(source)))
        DESTINATIONS[source.resolve()] = uri
    # Source README is a concise product landing page; site links lead home.
    DESTINATIONS[(ROOT / "README.md").resolve()] = "index.md"
    DESTINATIONS[(ROOT / "sdk/python/LICENSE").resolve()] = "license.md"
    return files


def on_page_markdown(markdown, page, config, files):
    source = ORIGINS[page.file.src_uri]

    def rewrite(match):
        target = match["target"]
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return match[0]
        destination = (source.parent / unquote(parsed.path)).resolve()
        if destination in DESTINATIONS:
            uri = posixpath.relpath(
                DESTINATIONS[destination], posixpath.dirname(page.file.src_uri) or "."
            )
            if parsed.fragment:
                uri += "#" + parsed.fragment
            return f'{match["image"]}[{match["label"]}]({uri})'
        retained_evidence = any(
            destination.is_relative_to(directory)
            for directory in (ROOT / "release", ROOT / "output")
        )
        if retained_evidence or (destination.is_file() and destination.suffix.lower() != ".md"):
            # Source-only reports, screenshots and package metadata are not
            # silently copied to a public site. Keep a readable source location.
            relative = posixpath.relpath(str(destination), str(ROOT))
            return f'{match["label"]} (source artifact: `{relative}`)'
        # Leave unknown links intact so MkDocs strict validation catches them.
        return match[0]

    # Rewriting Markdown prose only preserves examples and fenced source code.
    segments = re.split(r"(^```[^\n]*\n.*?^```[^\n]*$)", markdown, flags=re.M | re.S)
    for index in range(0, len(segments), 2):
        segments[index] = LINK.sub(rewrite, segments[index])
    result = "".join(segments)
    return result


def on_post_build(config):
    # Material ships every optional search language. The English index and
    # worker bundle already include English; no language helpers are loaded.
    # Keep the generated public artifact limited to the configured language.
    search = config["plugins"].get("material/search") or config["plugins"].get("search")
    if search is not None and search.config["lang"] == ["en"]:
        helpers = Path(config["site_dir"]) / "assets/javascripts/lunr"
        if helpers.is_symlink():
            raise ValueError("Generated search helper directory must not be a symlink")
        if helpers.is_dir():
            shutil.rmtree(helpers)

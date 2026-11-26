#!/usr/bin/env python3
"""Package the small, source-free operator download from an explicit allowlist."""
import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

FILES = (
    "LICENSE", "THIRD_PARTY_NOTICES.md", "PRODUCTION.md",
    "compose.production.yaml", "compose.mcp.production.yaml",
    "deploy/production.env.example", "deploy/Caddyfile", "deploy/Caddyfile.mcp",
    "scripts/example.py", "scripts/example/seed.py", "scripts/example/fixture.json",
    "scripts/example/compose.yaml", "scripts/demo/fixtures.py",
    "scripts/demo/assets/northstar-logo.png", "scripts/demo/assets/northstar-welcome.png",
    "scripts/demo/assets/northstar-seasonal.png", "docs/examples/welcome.json",
    "scripts/production-data.py", "scripts/upgrade-production.sh", "scripts/init-production-secrets.py",
)


def contents(root, version, revision):
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?", version):
        raise ValueError("Invalid version")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("An exact source revision is required")
    data = {}
    for name in FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing regular operator input: {name}")
        data[name] = path.read_bytes()
    application = f"ghcr.io/alexivanchyk/voxriva:{version}"
    mcp = f"ghcr.io/alexivanchyk/voxriva-mcp:{version}"
    compose = (root / "compose.yaml").read_text()
    marker = "  image: voxriva:local\n  build: .\n"
    if compose.count(marker) != 1:
        raise ValueError("Source Compose application anchor changed")
    compose = compose.replace(marker, f"  image: {application}\n  platform: linux/amd64\n")
    production = data["compose.production.yaml"].decode()
    for component, old in (("postgres", "postgres:17-alpine"), ("redis", "redis:7-alpine")):
        pinned = re.search(r"image: \$\{VOXRIVA_" + component.upper() + r"_IMAGE:-([^}]+)\}", production)
        if not pinned:
            raise ValueError(f"Missing production pin: {component}")
        compose = compose.replace(f"image: {old}\n", f"image: {pinned[1]}\n")
    data["compose.yaml"] = compose.encode()
    overlay = (root / "compose.mcp.yaml").read_text()
    overlay = overlay.replace(overlay.splitlines()[0], "# Optional prebuilt MCP overlay; same database and migration revision as the API.")
    marker = "    image: voxriva-mcp:local\n    build:\n      context: .\n      dockerfile: Dockerfile.mcp\n"
    if overlay.count(marker) != 1:
        raise ValueError("Source MCP Compose image changed")
    data["compose.mcp.yaml"] = overlay.replace(marker, f"    image: {mcp}\n    platform: linux/amd64\n").encode()
    data["distribution.json"] = (json.dumps({
        "schema": 1, "version": version, "revision": revision,
        "platform": "linux/amd64", "application_image": application, "mcp_image": mcp,
    }, indent=2) + "\n").encode()
    data["RUN.md"] = (
        f"# Voxriva {version}\n\n"
        "Requires Docker Engine with Compose v2 and Python 3.10+ on macOS/Linux.\n"
        "Published container platform: linux/amd64. No checkout or build is needed.\n\n"
        "```sh\npython3 scripts/example.py\n```\n\n"
        "The launcher prints local dashboard/inbox URLs and a protected login-file location.\n"
        "Stop: `python3 scripts/example.py stop`. Remove this example: `python3 scripts/example.py remove`.\n\n"
        "Guide: https://alexivanchyk.github.io/Voxriva/quickstart/\n"
        "Persistent operation: PRODUCTION.md and deploy/production.env.example (data tools need Python 3.11+).\n"
        f"Source and notices: https://github.com/AlexIvanchyk/Voxriva/tree/{revision}\n"
        "Third-party images are pulled separately and keep their upstream licenses.\n"
    ).encode()
    data["SHA256SUMS"] = "".join(f"{hashlib.sha256(value).hexdigest()}  {name}\n" for name, value in sorted(data.items())).encode()
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = contents(args.root, args.version, args.revision)
    with args.output.open("xb") as stream, gzip.GzipFile(fileobj=stream, mode="wb", filename="", mtime=0) as compressed, tarfile.open(fileobj=compressed, mode="w") as archive:
        for name, value in sorted(data.items()):
            item = tarfile.TarInfo(f"Voxriva-{args.version}/{name}")
            item.size = len(value)
            item.mode = 0o644
            archive.addfile(item, io.BytesIO(value))


if __name__ == "__main__":
    main()

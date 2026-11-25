#!/usr/bin/env python3
"""Publish verified local images; never rebuild or replace an existing version."""

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def registry_head(package: str, version: str, auth: str) -> tuple[int, str | None]:
    query = urllib.parse.urlencode(
        {"service": "ghcr.io", "scope": f"repository:{package}:pull,push"}
    )
    token_request = urllib.request.Request(
        "https://ghcr.io/token?" + query, headers={"Authorization": "Basic " + auth}
    )
    try:
        with urllib.request.urlopen(token_request, timeout=30) as response:
            token = json.load(response)["token"]
        request = urllib.request.Request(
            f"https://ghcr.io/v2/{package}/manifests/{version}",
            method="HEAD",
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as error:
        if error.url.startswith("https://ghcr.io/v2/") and error.code == 404:
            return 404, None
        raise RuntimeError(
            f"Registry authentication or manifest check failed (HTTP {error.code})"
        ) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError(
            "Registry request failed; absence has not been established"
        ) from None


def main() -> None:
    root = Path(os.environ["RELEASE_OUTPUT"])
    data = json.loads((root / "release.json").read_text())
    config = json.loads((Path(os.environ["DOCKER_CONFIG"]) / "config.json").read_text())
    auth = config["auths"]["ghcr.io"]["auth"]
    packages = {
        "application": os.environ["APPLICATION_PACKAGE"],
        "mcp": os.environ["MCP_PACKAGE"],
    }
    for role, package in packages.items():
        reference = f"ghcr.io/{package}:{data['version']}"
        if data["images"][role]["reference"] != reference:
            raise RuntimeError("Publication target differs from the verified candidate")
        status, _ = registry_head(package, data["version"], auth)
        if status != 404:
            raise RuntimeError(
                "A requested version tag already exists; choose a fresh version"
            )
    digests = {}
    for role, package in packages.items():
        reference = data["images"][role]["reference"]
        subprocess.run(["docker", "push", reference], check=True)
        status, digest = registry_head(package, data["version"], auth)
        if status != 200 or not digest:
            raise RuntimeError("Published image manifest digest could not be verified")
        digests[role] = {
            "reference": reference,
            "manifest_digest": digest,
            "image_id": data["images"][role]["image_id"],
        }
        (Path(os.environ["RUNNER_TEMP"]) / "published-digests.json").write_text(
            json.dumps(
                {
                    "version": data["version"],
                    "revision": data["revision"],
                    "complete": len(digests) == len(packages),
                    "images": digests,
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Skip runtime work only when every changed path is clearly documentation."""

import json
import os
import subprocess
from pathlib import Path


def runtime_required(paths: list[str]) -> bool:
    docs_config = {
        "mkdocs.yml",
        "mkdocs.yaml",
        "requirements-docs.txt",
        "voxriva/mkdocs.yml",
        "voxriva/mkdocs.yaml",
        "voxriva/requirements-docs.txt",
        "voxriva/requirements-docs.in",
        "voxriva/requirements-docs.lock",
        ".github/workflows/pages.yml",
        "LICENSE",
        "voxriva/LICENSE",
    }
    return any(
        not (
            path.endswith(".md")
            or path in docs_config
            or path.startswith(("docs/", "voxriva/docs/"))
        )
        for path in paths
    )


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    kind = os.environ["GITHUB_EVENT_NAME"]
    base = None
    if kind == "pull_request":
        base = event["pull_request"]["base"]["sha"]
    elif kind == "push":
        base = event.get("before")
    required = True  # Manual/release runs and missing history always run all checks.
    if base and base != "0" * 40:
        result = subprocess.run(
            [
                "git",
                "diff",
                "--no-renames",
                "--name-only",
                "-z",
                base,
                os.environ["GITHUB_SHA"],
                "--",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            paths = [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]
            required = runtime_required(paths)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
        stream.write(f"runtime={str(required).lower()}\n")


if __name__ == "__main__":
    main()

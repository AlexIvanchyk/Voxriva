#!/usr/bin/env python3
"""Small, stdlib-only CI evidence and release manifest helpers."""

import argparse
import hashlib
import json
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

SECURITY_TESTS = {
    "auth_permissions": {
        "test_session_security_rotation_and_csrf",
        "test_editor_management_keys_are_owned_scoped_and_csrf_protected",
    },
    "tenant_isolation": {
        "test_project_isolation_roles_and_atomic_member_creation",
        "test_provider_permissions_bindings_and_resolution_never_cross_projects",
    },
    "secret_handling": {
        "test_provider_revisions_encrypt_redact_keep_rotate_and_pin_credentials",
        "test_bootstrap_and_validation_do_not_expose_passwords",
    },
    "preview_sandbox": {
        "test_library_lifecycle_preview_conflicts_and_no_preview_writes",
        "test_renderer_rejects_undefined_syntax_attribute_calls_and_expansion",
    },
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_request(
    version: str, revision: str, app: str, mcp: str, root: Path
) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?", version):
        raise ValueError("Use a semantic version without a leading v")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Expected the full checked-out GitHub commit SHA")
    versions = [
        tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"],
        tomllib.loads((root / "sdk/python/pyproject.toml").read_text())["project"][
            "version"
        ],
        json.loads((root / "frontend/package.json").read_text())["version"],
    ]
    if versions != [version] * 3:
        raise ValueError(
            "Version must match application, frontend and bundled SDK metadata"
        )
    owner = os.environ["GITHUB_REPOSITORY_OWNER"].lower()
    for package in (app, mcp):
        if not re.fullmatch(
            r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)+", package
        ):
            raise ValueError(
                "Use lowercase GHCR owner/package paths without a registry or tag"
            )
        if package.split("/")[0] != owner:
            raise ValueError("Packages must belong to this workflow's repository owner")
    if app == mcp:
        raise ValueError("Application and MCP packages must be distinct")
    if os.environ.get("PUBLISH_REQUESTED") == "true":
        if os.environ.get("GITHUB_REF") != f"refs/tags/v{version}":
            raise ValueError(
                "Publishing requires dispatching from the matching vVERSION tag"
            )


def source_evidence(junit: Path, revision: str, output: Path) -> None:
    report = ET.parse(junit).getroot()
    cases = list(report.iter("testcase"))
    if not cases or list(report.iter("failure")) or list(report.iter("error")):
        raise ValueError("Backend JUnit evidence is empty or contains failed tests")
    passed = {
        case.attrib["name"].split("[")[0]
        for case in cases
        if case.find("skipped") is None
    }
    checks = {}
    for category, required in SECURITY_TESTS.items():
        if not required <= passed:
            raise ValueError(f"Missing passing security cases: {category}")
        checks[category] = {"status": "passed", "tests": sorted(required)}
    write_json(
        output, {"revision": revision, "scope": "source tests", "checks": checks}
    )


def bind_evidence(
    source: Path, inspect: Path, version: str, revision: str, runtime: str, output: Path
) -> None:
    evidence = json.loads(source.read_text())
    image = json.loads(inspect.read_text())[0]
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image["Id"]) or not runtime:
        raise ValueError(
            "Expected an immutable image ID and successful runtime reference"
        )
    labels = image["Config"]["Labels"]
    if (
        evidence["revision"] != revision
        or labels["org.opencontainers.image.revision"] != revision
    ):
        raise ValueError("Source evidence and image revision differ")
    if labels["org.opencontainers.image.version"] != version:
        raise ValueError("Image version does not match the requested version")
    if image["Os"] != "linux" or image["Architecture"] != "amd64":
        raise ValueError("This CI configuration validates only linux/amd64 candidates")
    checks = {}
    for category, required in SECURITY_TESTS.items():
        record = evidence["checks"][category]
        if record["status"] != "passed" or not required <= set(record["tests"]):
            raise ValueError(f"Invalid source evidence for {category}")
        checks[category] = {
            "status": "passed",
            "evidence": {"source_revision": revision, "source_tests": record["tests"]},
        }
    # The caller runs this only after the exact image's smoke command succeeds.
    checks["runtime_smoke"] = {"status": "passed", "evidence": runtime}
    write_json(output, {"image_id": image["Id"], "checks": checks})


def index_bundle(root: Path, version: str, revision: str, app: str, mcp: str) -> None:
    if (root / "SHA256SUMS").exists():
        raise ValueError("Refusing to rewrite an indexed bundle")
    images = {}
    for role, package, archive in (
        ("application", app, "voxriva-image.tar"),
        ("mcp", mcp, "voxriva-mcp-image.tar"),
    ):
        directory = root / role
        if (
            not (directory / archive).is_file()
            or not (directory / "SHA256SUMS").is_file()
        ):
            raise ValueError(f"Missing finalized archive or index for {role}")
        if (directory / "RELEASE-BLOCKED").exists() or not (
            directory / "APP-CHECKS-PASSED"
        ).is_file():
            raise ValueError(f"Application checks did not pass for {role}")
        image = json.loads((directory / "image-inspect.json").read_text())[0]
        if image["Config"]["Labels"]["org.opencontainers.image.revision"] != revision:
            raise ValueError(f"Image revision mismatch for {role}")
        images[role] = {
            "reference": f"ghcr.io/{package}:{version}",
            "image_id": image["Id"],
            "archive": f"{role}/{archive}",
        }
    write_json(
        root / "release.json",
        {
            "version": version,
            "revision": revision,
            "platform": "linux/amd64",
            "source": os.environ["GITHUB_REPOSITORY"],
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "images": images,
            "security_policy": "app-gates-v2; OS scan optional/advisory",
        },
    )
    # Inner candidates are already immutable. This adds a separate outer index.
    lines = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Release artifacts must not contain symlinks")
        if path.is_file():
            lines.append(f"{digest(path)}  {path.relative_to(root)}\n")
    (root / "SHA256SUMS").write_text("".join(lines))


def verify_bundle(root: Path, version: str, revision: str, app: str, mcp: str) -> None:
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("Release artifacts must not contain symlinks")
    entries = set()
    for line in (root / "SHA256SUMS").read_text().splitlines():
        checksum, relative = line.split("  ", 1)
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Unsafe artifact path")
        if relative in entries or digest(path) != checksum:
            raise ValueError("Artifact checksum mismatch or duplicate entry")
        entries.add(relative)
    actual = {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and p != root / "SHA256SUMS"
    }
    if not entries or entries != actual:
        raise ValueError("Artifact index is empty or incomplete")
    data = json.loads((root / "release.json").read_text())
    if (
        data["version"] != version
        or data["revision"] != revision
        or data["platform"] != "linux/amd64"
    ):
        raise ValueError("Artifact version/revision/platform mismatch")
    for key, environment in (
        ("source", "GITHUB_REPOSITORY"),
        ("run_id", "GITHUB_RUN_ID"),
        ("run_attempt", "GITHUB_RUN_ATTEMPT"),
    ):
        if data[key] != os.environ[environment]:
            raise ValueError("Artifact workflow provenance mismatch")
    for role, package, archive in (
        ("application", app, "voxriva-image.tar"),
        ("mcp", mcp, "voxriva-mcp-image.tar"),
    ):
        record = data["images"][role]
        if (
            record["reference"] != f"ghcr.io/{package}:{version}"
            or record["archive"] != f"{role}/{archive}"
        ):
            raise ValueError("Unexpected publication target or archive")
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", record["image_id"]):
            raise ValueError("Expected an immutable image ID")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["preflight", "source", "bind", "index", "verify", "summary"]
    )
    parser.add_argument("--root", type=Path)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--inspect", type=Path)
    parser.add_argument("--runtime")
    parser.add_argument("--version")
    parser.add_argument("--revision", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument(
        "--application-package", default=os.environ.get("APPLICATION_PACKAGE")
    )
    parser.add_argument("--mcp-package", default=os.environ.get("MCP_PACKAGE"))
    parser.add_argument("--suite")
    parser.add_argument("--exit-code", type=int)
    args = parser.parse_args()
    if args.command == "source":
        source_evidence(args.junit, args.revision, args.output)
    elif args.command == "bind":
        bind_evidence(
            args.source,
            args.inspect,
            args.version,
            args.revision,
            args.runtime,
            args.output,
        )
    elif args.command == "summary":
        write_json(
            args.output,
            {
                "suite": args.suite,
                "revision": args.revision,
                "exit_code": args.exit_code,
            },
        )
    else:
        function = {
            "preflight": validate_request,
            "index": index_bundle,
            "verify": verify_bundle,
        }[args.command]
        if args.command == "preflight":
            function(
                args.version,
                args.revision,
                args.application_package,
                args.mcp_package,
                args.root,
            )
        else:
            function(
                args.root,
                args.version,
                args.revision,
                args.application_package,
                args.mcp_package,
            )


if __name__ == "__main__":
    main()

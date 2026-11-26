#!/usr/bin/env python3
"""Small, stdlib-only CI evidence and release manifest helpers."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

RELEASE_WORKFLOW = ".github/workflows/release.yml"
REQUIRED_CANDIDATE_JOBS = {
    "preflight", "package", "changes", "docs", "workflow-policy", "backend",
    "frontend-security", "trivy", "ci-ready",
    *(f"e2e ({suite})" for suite in ("chromium", "cloud", "crash", "sdk", "mcp", "mcp-keys")),
}

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


def github_json(path: str) -> dict:
    """Use the job's read-scoped GitHub token; never put it in command arguments."""
    result = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise ValueError("Candidate GitHub API lookup failed; refusing reuse")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("Candidate GitHub API response is not an object")
    return value


def github_collection(path: str, key: str) -> list[dict]:
    result = []
    for page in range(1, 101):
        batch = github_json(f"{path}?per_page=100&page={page}")[key]
        if not isinstance(batch, list):
            raise ValueError("Invalid paginated candidate API response")
        result.extend(batch)
        if len(batch) < 100:
            return result
    raise ValueError("Candidate API collection exceeds the expected bound")


def positive_id(value: object) -> str:
    text = str(value)
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ValueError("Use a positive numeric candidate run/attempt/artifact ID")
    return text


def api_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Candidate API timestamps must include a timezone")
    return parsed


def verify_notices(root: Path, scopes: list[str]) -> None:
    """Require retained notices/source evidence, without claiming legal approval."""
    for scope in scopes:
        directory = root / "third-party" / scope
        if any(path.is_symlink() for path in directory.rglob("*")):
            raise ValueError("Third-party evidence must not contain symlinks")
        entries = set()
        for line in (directory / "SHA256SUMS").read_text().splitlines():
            checksum, relative = line.split("  ", 1)
            path = directory / relative
            if (
                not path.resolve().is_relative_to(directory.resolve())
                or relative in entries or not path.is_file()
                or not re.fullmatch(r"[a-f0-9]{64}", checksum)
                or digest(path) != checksum
            ):
                raise ValueError("Third-party evidence checksum/path mismatch")
            entries.add(relative)
        actual = {
            str(path.relative_to(directory)) for path in directory.rglob("*")
            if path.is_file() and path != directory / "SHA256SUMS"
        }
        if not entries or entries != actual:
            raise ValueError("Third-party evidence checksum index is incomplete")
        inventory = json.loads((directory / "inventory.json").read_text())
        if (
            inventory["schema_version"] != 1 or inventory["complete"] is not True
            or inventory["scope"] != scope or not inventory["packages"]
        ):
            raise ValueError("Third-party inventory is missing completed package evidence")
        for package in inventory["packages"]:
            if not package["name"] or not package["version"] or not package["notices"] or not package["sources"]:
                raise ValueError("Every distributed package needs retained notices and source evidence")
            for relative in package["notices"]:
                if relative not in entries:
                    raise ValueError("Third-party package notice is absent from the index")
            for source in package["sources"]:
                if source["path"] not in entries or digest(directory / source["path"]) != source["sha256"]:
                    raise ValueError("Third-party package source is absent or has a mismatched hash")


def select_candidate(
    run_id: str,
    version: str,
    revision: str,
    expected_attempt: str | None = None,
    expected_artifact_id: str | None = None,
) -> dict[str, str]:
    """Approve only a completed full build from this workflow and exact commit."""
    run_id = positive_id(run_id)
    if run_id == os.environ["GITHUB_RUN_ID"]:
        raise ValueError("A reused candidate must come from an earlier workflow run")
    repository = os.environ["GITHUB_REPOSITORY"]
    repository_id = int(os.environ["GITHUB_REPOSITORY_ID"])
    prefix = f"repos/{repository}/actions"
    workflow = github_json(f"{prefix}/workflows/release.yml")
    run = github_json(f"{prefix}/runs/{run_id}")
    if (
        workflow["path"] != RELEASE_WORKFLOW or workflow["state"] != "active"
        or run["workflow_id"] != workflow["id"]
        or run["path"].split("@", 1)[0] != RELEASE_WORKFLOW
        or str(run["id"]) != run_id
        or run["event"] != "workflow_dispatch"
        or run["status"] != "completed" or run["conclusion"] != "success"
        or run["head_sha"] != revision
        or any(
            run[key]["id"] != repository_id
            or run[key]["full_name"].lower() != repository.lower()
            for key in ("repository", "head_repository")
        )
    ):
        raise ValueError("Candidate is not a successful same-repository/workflow/commit dispatch")
    attempt = positive_id(run["run_attempt"])
    if expected_attempt is not None and attempt != positive_id(expected_attempt):
        raise ValueError("Candidate run attempt changed after approval")
    jobs = github_collection(f"{prefix}/runs/{run_id}/attempts/{attempt}/jobs", "jobs")
    by_name = {}
    for job in jobs:
        name = job["name"].rsplit(" / ", 1)[-1]
        by_name.setdefault(name, []).append(job)
    for name in REQUIRED_CANDIDATE_JOBS:
        matches = by_name.get(name, [])
        if len(matches) != 1 or matches[0]["status"] != "completed" or matches[0]["conclusion"] != "success":
            raise ValueError(f"Candidate full build is missing a successful required job: {name}")
    publishing = by_name.get("publish", [])
    if len(publishing) != 1 or publishing[0]["status"] != "completed" or publishing[0]["conclusion"] != "skipped":
        raise ValueError("Reuse requires a build-only candidate, not a publishing/reuse run")
    name = f"release-{version}-{revision}-{run_id}-{attempt}"
    artifacts = github_collection(f"{prefix}/runs/{run_id}/artifacts", "artifacts")
    matches = [artifact for artifact in artifacts if artifact["name"] == name]
    if len(matches) != 1:
        raise ValueError("Expected exactly one versioned candidate artifact for this run attempt")
    artifact = matches[0]
    artifact_id = positive_id(artifact["id"])
    if expected_artifact_id is not None and artifact_id != positive_id(expected_artifact_id):
        raise ValueError("Candidate artifact ID changed after approval")
    origin = artifact["workflow_run"]
    now = datetime.now(UTC)
    if (
        artifact["expired"] is not False
        or api_time(artifact["expires_at"]) <= now
        or api_time(artifact["created_at"]) < api_time(run["run_started_at"])
        or artifact["size_in_bytes"] <= 0
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact["digest"])
        or str(origin["id"]) != run_id
        or origin["repository_id"] != repository_id
        or origin["head_repository_id"] != repository_id
        or origin["head_sha"] != revision
    ):
        raise ValueError("Candidate artifact is expired or has mismatched API provenance")
    return {
        "source": repository, "revision": revision, "workflow": RELEASE_WORKFLOW,
        "run_id": run_id, "run_attempt": attempt,
        "artifact_id": artifact_id, "artifact_name": name,
        "artifact_digest": artifact["digest"], "artifact_expires_at": artifact["expires_at"],
        "validated_for_run_id": os.environ["GITHUB_RUN_ID"],
        "validated_for_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
    }


def download_bundle(
    output: Path, version: str, revision: str, artifact_id: str,
    source_run: dict[str, str] | None = None,
) -> None:
    """Verify the API's archive digest before safely extracting its indexed files."""
    artifact_id = positive_id(artifact_id)
    repository = os.environ["GITHUB_REPOSITORY"]
    run_id = source_run["run_id"] if source_run else os.environ["GITHUB_RUN_ID"]
    attempt = source_run["run_attempt"] if source_run else os.environ["GITHUB_RUN_ATTEMPT"]
    endpoint = f"repos/{repository}/actions/artifacts/{artifact_id}"
    artifact = github_json(endpoint)
    origin = artifact["workflow_run"]
    repository_id = int(os.environ["GITHUB_REPOSITORY_ID"])
    if (
        str(artifact["id"]) != artifact_id
        or artifact["name"] != f"release-{version}-{revision}-{run_id}-{attempt}"
        or artifact["expired"] is not False
        or api_time(artifact["expires_at"]) <= datetime.now(UTC)
        or artifact["size_in_bytes"] <= 0
        or str(origin["id"]) != run_id or origin["head_sha"] != revision
        or origin["repository_id"] != repository_id
        or origin["head_repository_id"] != repository_id
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", artifact["digest"])
        or (source_run is not None and (
            artifact_id != source_run["artifact_id"]
            or artifact["digest"] != source_run["artifact_digest"]
        ))
    ):
        raise ValueError("Downloaded candidate artifact has mismatched API identity or expiry")
    if output.exists():
        raise ValueError("Use a fresh directory for the verified candidate")
    with tempfile.TemporaryDirectory(prefix="candidate-download-", dir=output.parent) as temporary:
        archive = Path(temporary) / "candidate.zip"
        with archive.open("wb") as stream:
            result = subprocess.run(
                ["gh", "api", endpoint + "/zip"], stdout=stream, stderr=subprocess.PIPE, check=False
            )
        if result.returncode or digest(archive) != artifact["digest"].removeprefix("sha256:"):
            raise ValueError("Candidate archive download failed or its API SHA256 does not match")
        with zipfile.ZipFile(archive) as bundle:
            seen = set()
            for entry in bundle.infolist():
                parts = PurePosixPath(entry.filename).parts
                normalized = PurePosixPath(entry.filename).as_posix()
                if (
                    not parts or entry.filename.startswith("/") or ".." in parts
                    or "\\" in entry.filename or normalized in seen
                    or (entry.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("Candidate ZIP contains an unsafe or duplicate entry")
                seen.add(normalized)
            output.mkdir()
            bundle.extractall(output)


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
            "schema_version": 2,
            "version": version,
            "revision": revision,
            "platform": "linux/amd64",
            "source": os.environ["GITHUB_REPOSITORY"],
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "workflow": RELEASE_WORKFLOW,
            "event": "workflow_dispatch",
            "publication_requested": os.environ.get("PUBLISH_REQUESTED") == "true",
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


def verify_bundle(
    root: Path, version: str, revision: str, app: str, mcp: str,
    source_run: dict[str, str] | None = None,
) -> None:
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
        data["schema_version"] != 2
        or data["workflow"] != RELEASE_WORKFLOW
        or data["event"] != "workflow_dispatch"
        or data["version"] != version
        or data["revision"] != revision
        or data["platform"] != "linux/amd64"
    ):
        raise ValueError("Artifact version/revision/platform mismatch")
    expected = {
        "source": os.environ["GITHUB_REPOSITORY"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
    }
    if source_run is not None:
        if (
            source_run["source"] != expected["source"]
            or source_run["revision"] != revision
            or source_run["workflow"] != RELEASE_WORKFLOW
            or source_run["validated_for_run_id"] != expected["run_id"]
            or source_run["validated_for_run_attempt"] != expected["run_attempt"]
            or data["publication_requested"] is not False
        ):
            raise ValueError("Reused artifact has no approved build-only source run")
        expected.update({key: source_run[key] for key in ("run_id", "run_attempt")})
    for key, value in expected.items():
        if data[key] != value:
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


def create_github_release(
    root: Path, evidence: Path, notes: Path, version: str, revision: str,
    app: str, mcp: str, source_run: dict[str, str] | None = None,
) -> None:
    from source_release import release_notes, require_absent_release, require_remote_revision

    if os.environ.get("GITHUB_REF") != f"refs/tags/v{version}":
        raise ValueError("GitHub release publication requires the matching version tag")
    verify_bundle(root, version, revision, app, mcp, source_run)
    data = json.loads((root / "release.json").read_text())
    published = json.loads(evidence.read_text())
    expected_candidate = {key: data[key] for key in ("source", "run_id", "run_attempt")}
    if (
        published["complete"] is not True
        or published["version"] != version or published["revision"] != revision
        or published["candidate"] != expected_candidate
        or published["publisher"] != {
            "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        }
        or set(published["images"]) != {"application", "mcp"}
    ):
        raise ValueError("GitHub release requires complete digest evidence from this publishing run")
    for role in ("application", "mcp"):
        record = published["images"][role]
        if (
            record["reference"] != data["images"][role]["reference"]
            or record["image_id"] != data["images"][role]["image_id"]
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", record["manifest_digest"])
        ):
            raise ValueError("Published digest evidence differs from the verified candidate images")
    operator = root / f"Voxriva-{version}-operator.tar.gz"
    if not operator.is_file():
        raise ValueError("The tested operator bundle is missing from the candidate")
    repository = os.environ["GITHUB_REPOSITORY"]
    tag = f"v{version}"
    require_remote_revision(repository, tag, revision)
    require_absent_release(repository, tag)
    with tempfile.TemporaryDirectory(prefix="github-release-", dir=os.environ["RUNNER_TEMP"]) as temporary:
        assets = Path(temporary)
        shutil.copy2(operator, assets / operator.name)
        shutil.copy2(root / "release.json", assets / "release.json")
        shutil.copy2(evidence, assets / "published-digests.json")
        (assets / "OPERATOR-SHA256SUMS").write_text(f"{digest(operator)}  {operator.name}\n")
        rendered_notes = assets / "RELEASE_NOTES.md"
        rendered_notes.write_text(release_notes(notes.read_text(), version, repository))
        subprocess.run(
            ["gh", "release", "create", tag, "--repo", repository,
             "--verify-tag", "--prerelease", "--latest=false",
             "--title", f"Voxriva {version}", "--notes-file", str(rendered_notes),
             *[str(assets / name) for name in (operator.name, "OPERATOR-SHA256SUMS", "release.json", "published-digests.json")]],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["preflight", "candidate", "download", "github-release", "notices", "source", "bind", "index", "verify", "summary"]
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
    parser.add_argument("--candidate-run-id")
    parser.add_argument("--candidate-run-attempt")
    parser.add_argument("--artifact-id")
    parser.add_argument("--scope", action="append", choices=["python", "frontend"])
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--notes", type=Path)
    args = parser.parse_args()
    if args.command == "notices":
        if not args.scope:
            raise ValueError("Select at least one third-party evidence scope")
        verify_notices(args.root, args.scope)
    elif args.command == "candidate":
        if os.environ.get("PUBLISH_REQUESTED") != "true":
            raise ValueError("candidate_run_id is only accepted for explicit publish=true")
        candidate = select_candidate(
            args.candidate_run_id, args.version, args.revision,
            args.candidate_run_attempt, args.artifact_id,
        )
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as stream:
            for key in ("run_id", "run_attempt", "artifact_id"):
                stream.write(f"{key}={candidate[key]}\n")
    elif args.command in {"verify", "download", "github-release"}:
        candidate = None
        if args.candidate_run_id:
            candidate = select_candidate(
                args.candidate_run_id, args.version, args.revision,
                args.candidate_run_attempt, args.artifact_id,
            )
        if args.command == "download":
            download_bundle(args.output, args.version, args.revision, args.artifact_id, candidate)
        elif args.command == "github-release":
            create_github_release(
                args.root, args.evidence, args.notes, args.version, args.revision,
                args.application_package, args.mcp_package, candidate,
            )
        else:
            verify_bundle(
                args.root, args.version, args.revision,
                args.application_package, args.mcp_package, candidate,
            )
    elif args.command == "source":
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

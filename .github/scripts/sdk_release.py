"""Check SDK distributions and Actions provenance without rebuilding a candidate."""

import argparse
import base64
import csv
import email.parser
import hashlib
import io
import json
import os
import re
import tarfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

WORKFLOW = ".github/workflows/sdk-release.yml"
PACKAGE = "voxriva-sdk"
MODULE = "voxriva_sdk"
MODULE_FILES = {"__init__.py", "client.py", "errors.py", "images.py", "models.py", "py.typed"}
INDEXES = {"testpypi": "https://test.pypi.org", "pypi": "https://pypi.org"}
MAX_SIZE = 10 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def filenames(version):
    return {f"{MODULE}-{version}-py3-none-any.whl", f"{MODULE}-{version}.tar.gz"}


def output(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def request_json(url, *, github=False):
    headers = {"Accept": "application/json", "User-Agent": "Voxriva-SDK-release"}
    if github:
        headers.update({"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                        "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            raw = response.read(MAX_SIZE + 1)
            require(len(raw) <= MAX_SIZE, "API response exceeded size limit")
            return json.loads(raw)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise ValueError(f"Release API returned HTTP {error.code}; absence was not established") from None


def github(path):
    value = request_json(f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/{path}", github=True)
    require(value is not None, f"Required GitHub resource is absent: {path}")
    return value


def project(root, version):
    require(re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)", version) is not None,
            "Use a plain X.Y.Z version")
    metadata = tomllib.loads((root / "sdk/python/pyproject.toml").read_text())
    require(metadata["project"]["name"] == PACKAGE, "Unexpected SDK distribution name")
    require(metadata["project"]["version"] == version, "Requested SDK version differs from pyproject.toml")
    require(metadata["project"]["license"] == "MIT", "SDK license metadata changed; review it before publishing")
    return metadata["project"]


def identity(version, run_id, attempt, workflow_id):
    repository = os.environ["GITHUB_REPOSITORY"]
    revision = os.environ["GITHUB_SHA"]
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository), "Invalid repository identity")
    require(re.fullmatch(r"[0-9a-f]{40}", revision), "Use a full commit revision")
    require(all(re.fullmatch(r"[1-9]\d*", str(value)) for value in (run_id, attempt, workflow_id)),
            "Invalid workflow run identity")
    return {"schema": 1, "repository": repository, "revision": revision,
            "workflow": WORKFLOW, "workflow_id": int(workflow_id), "run_id": int(run_id),
            "run_attempt": int(attempt), "version": version}


def artifact_name(source):
    return (f"sdk-{source['version']}-{source['revision']}-"
            f"{source['run_id']}-{source['run_attempt']}")


def require_tag(version):
    require(os.environ["GITHUB_REF"] == f"refs/tags/v{version}", "Publishing requires the matching vVERSION tag")
    tag = github(f"git/ref/tags/v{version}")["object"]
    for _ in range(5):
        if tag["type"] == "commit":
            break
        require(tag["type"] == "tag", "Release tag must resolve to a commit")
        tag = github(f"git/tags/{tag['sha']}")["object"]
    require(tag["type"] == "commit" and tag["sha"] == os.environ["GITHUB_SHA"],
            "Remote release tag does not identify this exact checked commit")


def validate_reuse(run, workflow_id):
    require(run.get("repository", {}).get("full_name") == os.environ["GITHUB_REPOSITORY"]
            and run.get("head_repository", {}).get("full_name") == os.environ["GITHUB_REPOSITORY"],
            "Candidate run belongs to another repository")
    require(run.get("workflow_id") == workflow_id and run.get("path") == WORKFLOW,
            "Candidate run belongs to another workflow")
    require(run.get("head_sha") == os.environ["GITHUB_SHA"], "Candidate commit differs from this checkout")
    require(run.get("event") == "workflow_dispatch" and run.get("status") == "completed"
            and run.get("conclusion") == "success", "Only a completed successful SDK candidate run may be reused")


def plan(args):
    project(args.root, args.version)
    if args.target != "candidate":
        require_tag(args.version)
    workflow_id = github("actions/workflows/sdk-release.yml")["id"]
    source_run, attempt = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]
    artifact_id = ""
    if args.candidate_run_id:
        require(re.fullmatch(r"[1-9]\d*", args.candidate_run_id), "Candidate run ID must be numeric")
        require(args.candidate_run_id != source_run, "A run cannot reuse itself")
        run = github(f"actions/runs/{args.candidate_run_id}")
        validate_reuse(run, workflow_id)
        source_run, attempt = str(run["id"]), str(run["run_attempt"])
        source = identity(args.version, source_run, attempt, workflow_id)
        artifacts = github(f"actions/runs/{source_run}/artifacts?per_page=100")
        matches = [item for item in artifacts["artifacts"] if item["name"] == artifact_name(source)]
        require(len(matches) == 1 and not matches[0]["expired"], "Exact candidate artifact is missing or expired")
        item = matches[0]
        require(item.get("workflow_run", {}).get("id") == int(source_run)
                and item["workflow_run"].get("head_sha") == source["revision"], "Artifact provenance differs from source run")
        require(0 < item["size_in_bytes"] <= MAX_SIZE, "Candidate artifact has an unexpected size")
        artifact_id = str(item["id"])
    source = identity(args.version, source_run, attempt, workflow_id)
    output(version=args.version, source_run=source_run, source_attempt=attempt,
           workflow_id=workflow_id, artifact=artifact_name(source), artifact_id=artifact_id)


def source_bytes(root, relative):
    path = root / "sdk/python" / relative
    require(path.is_file() and not path.is_symlink(), f"Missing regular SDK source: {relative}")
    return path.read_bytes()


def safe_entry(name):
    path = PurePosixPath(name)
    require(name and str(path) == name and not path.is_absolute() and ".." not in path.parts
            and "\\" not in name and all(ord(c) >= 32 and ord(c) != 127 for c in name),
            "Unsafe distribution archive entry")
    return path


def metadata_check(raw, root, version):
    metadata = email.parser.BytesParser().parsebytes(raw)
    expected = {"Name": PACKAGE, "Version": version, "Requires-Python": ">=3.10", "License-Expression": "MIT"}
    for key, value in expected.items():
        require(metadata.get_all(key) == [value], f"Unexpected SDK metadata: {key}")
    require(metadata.get_all("License-File") == ["LICENSE"], "SDK license file must be declared")
    dependencies = [re.sub(r"\s+", "", value) for value in metadata.get_all("Requires-Dist", [])]
    require(dependencies in (["httpx<1,>=0.28.1"], ["httpx>=0.28.1,<1"]), "Unexpected SDK runtime dependencies")
    # Core metadata stores its description as raw UTF-8 without MIME charset
    # headers. Message.get_payload() otherwise substitutes non-ASCII characters.
    _, separator, body = raw.replace(b"\r\n", b"\n").partition(b"\n\n")
    require(separator, "Package metadata is missing its description body")
    description = body.decode("utf-8")
    readme = source_bytes(root, "README.md").decode("utf-8").replace("\r\n", "\n")
    # setuptools 80.9.0 appends one final newline only when the README lacks it.
    require(description == readme or (not readme.endswith("\n") and description == readme + "\n"),
            "Package description differs from the checked SDK README")


def wheel_check(path, root, version):
    info = f"{MODULE}-{version}.dist-info"
    required = {f"{MODULE}/{name}" for name in MODULE_FILES} | {
        f"{info}/{name}" for name in ("METADATA", "WHEEL", "RECORD", "top_level.txt", "licenses/LICENSE")}
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        require(len(entries) == len(required) and {entry.filename for entry in entries} == required,
                "Wheel contains missing, duplicate, private, or unreviewed files")
        require(sum(entry.file_size for entry in entries) <= MAX_SIZE, "Wheel contents exceeded size limit")
        for entry in entries:
            safe_entry(entry.filename)
            require(not entry.is_dir() and (entry.external_attr >> 16) & 0o170000 in (0, 0o100000),
                    "Wheel must only contain regular files")
        for name in MODULE_FILES:
            require(archive.read(f"{MODULE}/{name}") == source_bytes(root, f"src/{MODULE}/{name}"),
                    f"Wheel module differs from checked source: {name}")
        require(archive.read(f"{info}/licenses/LICENSE") == source_bytes(root, "LICENSE"), "Wheel license differs from source")
        metadata_check(archive.read(f"{info}/METADATA"), root, version)
        wheel = email.parser.BytesParser().parsebytes(archive.read(f"{info}/WHEEL"))
        require(wheel["Root-Is-Purelib"] == "true" and wheel.get_all("Tag") == ["py3-none-any"],
                "Expected a platform-independent pure Python wheel")
        rows = list(csv.reader(io.StringIO(archive.read(f"{info}/RECORD").decode())))
        require(len(rows) == len(required) and {row[0] for row in rows} == required, "Invalid wheel RECORD file list")
        for row in rows:
            require(len(row) == 3, "Invalid wheel RECORD row")
            name, checksum, size = row
            if name.endswith("/RECORD"):
                require(not checksum and not size, "RECORD must not hash itself")
            else:
                content = archive.read(name)
                encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
                require(checksum == f"sha256={encoded}" and size == str(len(content)), "Wheel RECORD integrity failure")


def sdist_check(path, root, version):
    prefix = f"{MODULE}-{version}"
    sources = {f"src/{MODULE}/{name}" for name in MODULE_FILES} | {"LICENSE", "README.md", "MANIFEST.in", "pyproject.toml", "tests/test_client.py"}
    generated = {"PKG-INFO", "setup.cfg"} | {f"src/{MODULE}.egg-info/{name}" for name in (
        "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "requires.txt", "top_level.txt")}
    expected = sources | generated
    with tarfile.open(path, "r:gz") as archive:
        entries = archive.getmembers()
        require(len(entries) == len({entry.name for entry in entries}), "Duplicate sdist archive entries")
        require(sum(entry.size for entry in entries) <= MAX_SIZE, "Sdist contents exceeded size limit")
        files = {}
        directories = set()
        for entry in entries:
            safe_entry(entry.name)
            require(entry.name == prefix or entry.name.startswith(prefix + "/"), "Unexpected sdist root")
            relative = entry.name.removeprefix(prefix).lstrip("/")
            if entry.isdir():
                directories.add(relative)
                continue
            require(entry.isfile() and relative in expected, "Sdist contains a link, private, or unreviewed file")
            files[relative] = archive.extractfile(entry).read()
        require(set(files) == expected, "Sdist is missing required sources or metadata")
        allowed_directories = {""} | {str(parent) for name in expected for parent in PurePosixPath(name).parents if str(parent) != "."}
        require(directories <= allowed_directories, "Unexpected sdist directory")
        for name in sources:
            require(files[name] == source_bytes(root, name), f"Sdist source differs from checkout: {name}")
        for name in ("PKG-INFO", f"src/{MODULE}.egg-info/PKG-INFO"):
            metadata_check(files[name], root, version)
        require(files[f"src/{MODULE}.egg-info/dependency_links.txt"] == b"\n"
                and files[f"src/{MODULE}.egg-info/top_level.txt"] == b"voxriva_sdk\n"
                and files[f"src/{MODULE}.egg-info/requires.txt"] in (b"httpx<1,>=0.28.1\n", b"httpx>=0.28.1,<1\n"),
                "Unexpected generated SDK dependency metadata")
        listed = set(files[f"src/{MODULE}.egg-info/SOURCES.txt"].decode().splitlines())
        require(listed == expected - {"setup.cfg", "PKG-INFO"}, "Sdist source manifest contains unreviewed paths")


def distributions(bundle, root, version):
    project(root, version)
    directory = bundle / "dist"
    require(directory.is_dir() and not directory.is_symlink(), "Missing SDK dist directory")
    entries = list(directory.iterdir())
    require({path.name for path in entries} == filenames(version), "Exactly one wheel and one sdist are required")
    require(all(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_SIZE for path in entries),
            "Distribution must be a bounded regular file")
    wheel_check(directory / f"{MODULE}-{version}-py3-none-any.whl", root, version)
    sdist_check(directory / f"{MODULE}-{version}.tar.gz", root, version)
    return {f"dist/{path.name}": digest(path.read_bytes()) for path in sorted(entries)}


def seal(args):
    require({path.name for path in args.bundle.iterdir()} == {"dist"}, "Candidate output must be new and contain only dist/")
    files = distributions(args.bundle, args.root, args.version)
    source = identity(args.version, args.source_run, args.source_attempt, args.workflow_id)
    manifest = {"source": source, "sha256": files}
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    (args.bundle / "sdk-release.json").write_bytes(manifest_bytes)
    files["sdk-release.json"] = digest(manifest_bytes)
    (args.bundle / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in sorted(files.items())))
    verify(args)


def verify(args):
    require({path.name for path in args.bundle.iterdir()} == {"dist", "sdk-release.json", "SHA256SUMS"},
            "Unexpected candidate bundle files")
    require(all(not path.is_symlink() for path in args.bundle.iterdir()), "Candidate bundle contains a symlink")
    expected = identity(args.version, args.source_run, args.source_attempt, args.workflow_id)
    manifest = json.loads((args.bundle / "sdk-release.json").read_text())
    require(manifest.get("source") == expected, "Bundle provenance differs from trusted GitHub run identity")
    files = distributions(args.bundle, args.root, args.version)
    require(manifest.get("sha256") == files, "Distribution checksum differs from reviewed candidate")
    files["sdk-release.json"] = digest((args.bundle / "sdk-release.json").read_bytes())
    checksums = "".join(f"{value}  {name}\n" for name, value in sorted(files.items()))
    require((args.bundle / "SHA256SUMS").read_text() == checksums, "Candidate checksums are incomplete or altered")


def index_match(row, bundle, version):
    require(row["info"]["name"] == PACKAGE and row["info"]["version"] == version, "Index returned another SDK version")
    expected = json.loads((bundle / "sdk-release.json").read_text())["sha256"]
    urls = row["urls"]
    require(len(urls) == 2 and {entry["filename"] for entry in urls} == filenames(version),
            "Index does not contain the exact reviewed wheel and sdist")
    for entry in urls:
        require(not entry.get("yanked") and entry["digests"]["sha256"] == expected[f"dist/{entry['filename']}"],
                "Index distribution was yanked or differs from reviewed bytes")


def index(args):
    require_tag(args.version)
    url = f"{INDEXES[args.index]}/pypi/{PACKAGE}/{args.version}/json"
    if args.mode == "require-absent":
        require(request_json(url) is None, "This version already exists; publishing never overwrites an index release")
        return
    row = request_json(url)
    if args.mode == "prepare-test":
        require(args.index == "testpypi", "Only TestPyPI may reuse an identical existing test release")
        if row is None:
            output(upload="true")
        else:
            index_match(row, args.bundle, args.version)
            output(upload="false")
        return
    for attempt in range(12):
        if row is not None and len(row.get("urls", [])) == 2:
            index_match(row, args.bundle, args.version)
            return
        if attempt < 11:
            time.sleep(10)
            row = request_json(url)
    raise ValueError("Exact SDK release has not appeared in the index")


def downloaded(args):
    name = f"{MODULE}-{args.version}-py3-none-any.whl"
    require({path.name for path in args.directory.iterdir()} == {name}, "Index download must contain only the expected wheel")
    path = args.directory / name
    require(path.is_file() and not path.is_symlink(), "Downloaded wheel is not a regular file")
    expected = json.loads((args.bundle / "sdk-release.json").read_text())["sha256"][f"dist/{name}"]
    require(digest(path.read_bytes()) == expected, "Downloaded index wheel differs from reviewed candidate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "seal", "verify", "index", "downloaded"):
        item = commands.add_parser(command)
        item.add_argument("--version", required=True)
        item.add_argument("--root", type=Path, default=Path.cwd())
        if command == "plan":
            item.add_argument("--target", choices=("candidate", "testpypi", "pypi"), required=True)
            item.add_argument("--candidate-run-id", default="")
        else:
            item.add_argument("--bundle", type=Path, required=True)
        if command in ("seal", "verify"):
            item.add_argument("--source-run", required=True)
            item.add_argument("--source-attempt", required=True)
            item.add_argument("--workflow-id", required=True)
        if command == "index":
            item.add_argument("--index", choices=INDEXES, required=True)
            item.add_argument("--mode", choices=("require-absent", "prepare-test", "match"), required=True)
        if command == "downloaded":
            item.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        globals()[args.command](args)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, tarfile.TarError) as error:
        raise SystemExit(f"SDK release check failed: {error}") from None


if __name__ == "__main__":
    main()

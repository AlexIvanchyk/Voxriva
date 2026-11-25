#!/usr/bin/env python3
"""Package reviewed Git source and publish a source-only GitHub prerelease."""

import argparse
import hashlib
import json
import os
import posixpath
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

PRIVATE_DIRECTORIES = {
    ".git", ".aws", ".codex", ".agents", ".idea", ".vscode", ".venv", "venv",
    "node_modules", "__pycache__", "secrets", "backups", "output", "release",
    "build", "dist", "test-results", "playwright-report", "blob-report",
}


def validate_request(root: Path, version: str, revision: str, publish: bool) -> None:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.]+)?", version):
        raise ValueError("Use a semantic version without a leading v")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Expected the checked-out full commit SHA")
    versions = [
        tomllib.loads((root / "voxriva/pyproject.toml").read_text())["project"]["version"],
        tomllib.loads((root / "voxriva/sdk/python/pyproject.toml").read_text())["project"]["version"],
        json.loads((root / "voxriva/frontend/package.json").read_text())["version"],
    ]
    if versions != [version] * 3:
        raise ValueError("Version must match application, frontend and SDK metadata")
    if publish and os.environ.get("GITHUB_REF") != f"refs/tags/v{version}":
        raise ValueError("Publishing requires dispatch from the matching vVERSION tag")


def validate_source_entry(mode: str, path: str) -> None:
    # This catches accidental local state; the source still needs review before
    # its initial commit. It is not a complete content/secret scanner.
    if mode not in {"100644", "100755"}:
        raise ValueError(f"Source archives do not accept symlinks or submodules: {path}")
    parts = PurePosixPath(path).parts
    if (
        not parts or path.startswith("/") or ".." in parts
        or any(ord(character) < 32 for character in path)
        or PRIVATE_DIRECTORIES.intersection(parts)
    ):
        raise ValueError(f"Private/generated or unsafe tracked source path: {path}")
    name = parts[-1]
    environment = name == ".env" or name.startswith(".env.") or name.endswith(".env")
    example = name.endswith(".example")
    if environment and not example:
        raise ValueError(f"Real environment files must not enter source archives: {path}")
    if name.endswith((".sqlite", ".sqlite3", ".pyc", ".pyo")):
        raise ValueError(f"Local data must not enter source archives: {path}")


def filenames(version: str) -> set[str]:
    return {
        f"Voxriva-{version}-source.tar.gz", f"Voxriva-{version}-source.zip",
        "RELEASE_NOTES.md", "source-release.json",
    }


def checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def provenance(version: str, revision: str) -> dict[str, str]:
    return {
        "version": version, "revision": revision, "scope": "source-only prerelease",
        "repository": os.environ["GITHUB_REPOSITORY"],
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
    }


def release_notes(markdown: str, version: str, repository: str) -> str:
    """Make source-relative prose links usable on the GitHub Release page."""
    source_directory = "voxriva/docs/releases"
    link = re.compile(r"(?P<prefix>!?\[[^\]]+\]\()(?P<target>[^)]+)\)")
    inline_code = re.compile(r"(`+)(.*?)\1(?!`)")

    def rewrite(match):
        target = match["target"]
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
            return match[0]
        path = posixpath.normpath(posixpath.join(source_directory, unquote(parsed.path)))
        if path == ".." or path.startswith("../") or path.startswith("/"):
            raise ValueError("Release note link escapes the source repository")
        absolute = f"https://github.com/{repository}/blob/v{version}/{quote(path, safe='/')}"
        if parsed.query:
            absolute += "?" + parsed.query
        if parsed.fragment:
            absolute += "#" + parsed.fragment
        return f'{match["prefix"]}{absolute})'

    result = []
    fence = None
    for line in markdown.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            result.append(line)
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{fence[1]},}}[ \t]*\r?\n?", line):
                fence = None
        elif marker:
            fence = (marker[1][0], len(marker[1]))
            result.append(line)
        else:
            position = 0
            for code in inline_code.finditer(line):
                result.append(link.sub(rewrite, line[position:code.start()]))
                result.append(code[0])
                position = code.end()
            result.append(link.sub(rewrite, line[position:]))
    return "".join(result)


def package_source(root: Path, output: Path, version: str, revision: str) -> None:
    if output.exists():
        raise ValueError("Use a fresh source artifact directory")
    resolved = subprocess.check_output(
        ["git", "rev-parse", f"{revision}^{{commit}}"], cwd=root, text=True
    ).strip()
    if resolved != revision:
        raise ValueError("Source revision does not resolve to the selected commit")
    tree = subprocess.check_output(
        ["git", "ls-tree", "-r", "--full-tree", "-z", revision], cwd=root
    )
    if not tree:
        raise ValueError("Source tree is empty")
    for record in tree.split(b"\0"):
        if record:
            metadata, path = os.fsdecode(record).split("\t", 1)
            validate_source_entry(metadata.split()[0], path)
    notes = subprocess.check_output(
        ["git", "show", f"{revision}:voxriva/docs/releases/{version}.md"], cwd=root
    )
    if not notes.strip():
        raise ValueError("Reviewed source-only release notes are required")
    output.mkdir(parents=True)
    for kind, suffix in (("tar.gz", "tar.gz"), ("zip", "zip")):
        subprocess.run(
            ["git", "archive", f"--format={kind}", f"--prefix=Voxriva-{version}/",
             f"--output={output.resolve() / f'Voxriva-{version}-source.{suffix}'}", revision],
            cwd=root, check=True,
        )
    (output / "RELEASE_NOTES.md").write_text(
        release_notes(notes.decode("utf-8"), version, os.environ["GITHUB_REPOSITORY"])
    )
    (output / "source-release.json").write_text(
        json.dumps(provenance(version, revision), indent=2, sort_keys=True) + "\n"
    )
    (output / "SHA256SUMS").write_text("".join(
        f"{checksum(output / name)}  {name}\n" for name in sorted(filenames(version))
    ))


def verify_source(output: Path, version: str, revision: str) -> None:
    expected = filenames(version)
    paths = list(output.iterdir())
    if (
        {path.name for path in paths} != expected | {"SHA256SUMS"}
        or any(path.is_symlink() or not path.is_file() for path in paths)
    ):
        raise ValueError("Source artifact contains missing, extra or unsafe files")
    indexed = set()
    for line in (output / "SHA256SUMS").read_text().splitlines():
        value, name = line.split("  ", 1)
        if name not in expected or name in indexed or checksum(output / name) != value:
            raise ValueError("Source artifact checksum mismatch or unsafe entry")
        indexed.add(name)
    if indexed != expected:
        raise ValueError("Source checksum index is incomplete")
    if json.loads((output / "source-release.json").read_text()) != provenance(version, revision):
        raise ValueError("Source artifact workflow provenance does not match")


def require_absent_release(repository: str, tag: str) -> None:
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/releases/tags/{tag}", "--include"],
        capture_output=True, text=True, check=False,
    )
    statuses = re.findall(r"^HTTP/[0-9.]+\s+([0-9]{3})(?:\s|$)", result.stdout, re.M)
    status = statuses[-1] if statuses else None
    if result.returncode == 0 or status == "200":
        raise ValueError("A release already exists; refusing to overwrite it")
    if status != "404":
        raise ValueError("Release lookup failed; absence has not been established")


def require_remote_revision(repository: str, tag: str, revision: str) -> None:
    actual = subprocess.check_output(
        ["gh", "api", f"repos/{repository}/commits/{tag}", "--jq", ".sha"], text=True
    ).strip()
    if actual != revision:
        raise ValueError("The remote tag no longer points to the tested source commit")


def publish_source(output: Path, version: str, revision: str) -> None:
    if os.environ.get("GITHUB_REF") != f"refs/tags/v{version}":
        raise ValueError("Publishing requires dispatch from the matching vVERSION tag")
    verify_source(output, version, revision)
    repository = os.environ["GITHUB_REPOSITORY"]
    tag = f"v{version}"
    require_remote_revision(repository, tag, revision)
    require_absent_release(repository, tag)
    subprocess.run(
        ["gh", "release", "create", tag, "--repo", repository, "--verify-tag",
         "--prerelease", "--latest=false", "--title", f"Voxriva {version} — source prerelease",
         "--notes-file", str(output / "RELEASE_NOTES.md"),
         *[str(output / name) for name in sorted(filenames(version) | {"SHA256SUMS"})]],
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preflight", "package", "verify", "publish"])
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--publish", choices=["true", "false"], default="false")
    args = parser.parse_args()
    validate_request(args.root, args.version, args.revision, args.publish == "true")
    if args.command == "package":
        package_source(args.root, args.output, args.version, args.revision)
    elif args.command == "verify":
        verify_source(args.output, args.version, args.revision)
    elif args.command == "publish":
        publish_source(args.output, args.version, args.revision)


if __name__ == "__main__":
    main()

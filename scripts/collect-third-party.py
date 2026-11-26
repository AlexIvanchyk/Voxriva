#!/usr/bin/env python3
"""Retain installed notices and verified upstream sources without executing them.

Run in the matching image/build stage in CI. A completed inventory records
artifact evidence, not a legal opinion or a vulnerability/security assessment.
"""

import argparse
import base64
import hashlib
import importlib.metadata
import io
import json
import re
import subprocess
import sys
import tarfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

NOTICE = re.compile(
    r"^(?:(?:licen[cs]es?|copying|notice|authors|copyright|patents?)(?:[._-].*)?|FTL\.TXT|README\.ijg)$",
    re.I,
)
MAX_DOWNLOAD = 256 * 1024 * 1024
CHOICES = {
    "cryptography": "Apache-2.0",
    "packaging": "Apache-2.0",
    "python-dateutil": "BSD-3-Clause",
    "dompurify": "Apache-2.0",
}


def normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def safe_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive/record path: {name}")
    return path


def download(url, expected=None, algorithm="sha256"):
    if urlsplit(url).scheme != "https":
        raise ValueError("Source downloads require HTTPS")
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError("Source archive exceeds the size limit")
    actual = hashlib.new(algorithm, data).digest()
    if expected is not None:
        valid = (
            base64.b64encode(actual).decode() == expected
            if algorithm.startswith("sha") and not re.fullmatch(r"[0-9a-f]+", expected)
            else actual.hex() == expected
        )
        if not valid:
            raise ValueError(f"Source checksum mismatch: {url}")
    return data


def archive_files(data):
    """Read regular members only; never extract paths, links or executable code."""
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.infolist():
                safe_path(member.filename)
                if not member.is_dir():
                    yield member.filename, archive.read(member)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
            for member in archive:
                safe_path(member.name)
                if member.isfile():
                    source = archive.extractfile(member)
                    assert source is not None
                    yield member.name, source.read()


class Bundle:
    def __init__(self, root, scope):
        self.root = Path(root)
        if self.root.exists():
            raise ValueError("Use a fresh third-party output directory")
        self.root.mkdir(parents=True)
        self.inventory = {
            "schema_version": 1,
            "complete": False,
            "scope": scope,
            "packages": [],
            "native_components": [],
            "meaning": "Retained artifact notices/sources; not blanket legal clearance.",
        }
        self.cached_sources = {}

    def write(self, relative, data):
        path = self.root.joinpath(*safe_path(relative).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path.relative_to(self.root).as_posix()

    def source(self, label, url, expected=None, algorithm="sha256"):
        key = (url, expected, algorithm)
        if key in self.cached_sources:
            return self.cached_sources[key]
        data = download(url, expected, algorithm)
        name = PurePosixPath(unquote(urlsplit(url).path)).name
        relative = self.write(f"sources/{label}/{name}", data)
        notices = []
        locks = []
        for member, content in archive_files(data):
            path = safe_path(member)
            if any(NOTICE.fullmatch(part) for part in path.parts):
                notices.append(self.write(f"source-notices/{label}/{path}", content))
            if path.name == "Cargo.lock":
                locks.append(tomllib.loads(content.decode()))
        result = {
            "path": relative,
            "url": url,
            "sha256": hashlib.sha256(data).hexdigest(),
            "notices": notices,
        }
        self.cached_sources[key] = (result, locks)
        return result, locks

    def finish(self):
        for package in self.inventory["packages"]:
            if not package["notices"] or not package["sources"]:
                raise ValueError(f"Missing notices or source for {package['name']}")
        self.inventory["complete"] = True
        self.write("inventory.json", (json.dumps(self.inventory, indent=2) + "\n").encode())
        self.write(
            "README.txt",
            b"Original third-party notices and upstream source archives are retained here.\n"
            b"inventory.json identifies actual installed package versions, chosen license\n"
            b"alternatives where applicable, source URLs and SHA256. SHA256SUMS covers\n"
            b"every retained file. Native wheel SBOMs retain upstream provenance/patches.\n"
            b"This evidence is not a blanket legal opinion or an application MIT-only claim.\n",
        )
        checksums = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                checksums.append(f"{digest}  {path.relative_to(self.root).as_posix()}\n")
        self.write("SHA256SUMS", "".join(checksums).encode())


def locked_requirements(paths):
    result = {}
    for path in paths:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(r"([\w.-]+)==([^\s;]+)", line)
            if match is None:
                raise ValueError(f"Expected an exact runtime requirement: {line}")
            name, version = normalized(match[1]), match[2]
            if name in result and result[name] != version:
                raise ValueError(f"Conflicting version for {name}")
            result[name] = version
    if "rfc3987" in result:
        raise ValueError("Use jsonschema's supported format-nongpl dependency set")
    return result


def pypi_source(bundle, name, version):
    metadata_url = f"https://pypi.org/pypi/{quote(name)}/{quote(version)}/json"
    data = json.loads(download(metadata_url))
    archives = sorted(
        (item for item in data["urls"] if item["packagetype"] == "sdist"),
        key=lambda item: item["filename"],
    )
    if not archives:
        raise ValueError(f"No exact PyPI source archive for {name} {version}")
    archive = archives[0]
    if urlsplit(archive["url"]).hostname != "files.pythonhosted.org":
        raise ValueError("Unexpected PyPI source host")
    source, locks = bundle.source(
        f"{name}-{version}", archive["url"], archive["digests"]["sha256"]
    )
    source["metadata_url"] = metadata_url
    return source, locks


def native_components(bundle, owner, sboms, cargo_locks):
    """Retain exact native crate/OpenSSL sources from wheel SBOMs or Cargo.lock."""
    seen = set()
    has_cargo_sbom = any(
        component.get("purl", "").startswith("pkg:cargo/")
        for sbom in sboms for component in sbom.get("components", [])
    )
    for sbom in sboms:
        for component in sbom.get("components", []):
            if component.get("scope") == "excluded":
                continue
            name, version = component.get("name"), component.get("version")
            purl = component.get("purl", "")
            digest = next(
                (x["content"] for x in component.get("hashes", []) if x["alg"] == "SHA-256"),
                None,
            )
            url = None
            if purl.startswith("pkg:cargo/") and version:
                url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
            elif digest:
                url = next(
                    (
                        x["url"] for x in component.get("externalReferences", [])
                        if x["type"] == "distribution"
                        and re.search(r"\.(?:tar\.(?:gz|xz|bz2)|tgz|zip)$", x["url"])
                    ),
                    None,
                )
            if url and digest:
                source, _ = bundle.source(f"native/{name}-{version}", url, digest)
                bundle.inventory["native_components"].append({
                    "owner": owner, "name": name, "version": version,
                    "provenance": "installed-wheel-sbom", "source": source,
                    "licenses": component.get("licenses", []),
                })
                seen.add((name, version))
    # A wheel SBOM distinguishes shipped crates from excluded build/test crates.
    # Only fall back to the conservative lock closure when no Cargo SBOM exists.
    for lock in ([] if has_cargo_sbom else cargo_locks):
        for package in lock.get("package", []):
            if not package.get("source", "").startswith("registry+"):
                continue
            name, version = package["name"], package["version"]
            if (name, version) in seen:
                continue
            digest = package.get("checksum")
            if not digest:
                raise ValueError(f"Native crate has no source checksum: {name}")
            source, _ = bundle.source(
                f"native/{name}-{version}",
                f"https://static.crates.io/crates/{name}/{name}-{version}.crate", digest,
            )
            bundle.inventory["native_components"].append({
                "owner": owner, "name": name, "version": version,
                "provenance": "exact-sdist-Cargo.lock", "source": source,
            })
            seen.add((name, version))


def collect_python(bundle, requirements, native_manifest, base_runtime):
    for name, version in sorted(locked_requirements(requirements).items()):
        dist = importlib.metadata.distribution(name)
        if dist.version != version:
            raise ValueError(f"Installed version differs from lock: {name}")
        source, locks = pypi_source(bundle, name, version)
        package = {
            "name": name, "version": version,
            "license_expression": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
            "selected_license": CHOICES.get(name),
            "project_urls": dist.metadata.get_all("Project-URL", []),
            "notices": list(source["notices"]), "sources": [source],
            "installed_native_files": [], "sboms": [],
        }
        sboms = []
        for item in dist.files or []:
            relative = str(item)
            if ".." in PurePosixPath(relative).parts:
                continue  # Generated entry-point paths outside site-packages.
            path = Path(dist.locate_file(item))
            if not path.is_file():
                continue
            if any(NOTICE.fullmatch(part) for part in PurePosixPath(relative).parts):
                package["notices"].append(bundle.write(f"installed/{name}-{version}/{relative}", path.read_bytes()))
            if ".dist-info/sboms/" in relative and path.suffix == ".json":
                package["sboms"].append(bundle.write(f"installed/{name}-{version}/{relative}", path.read_bytes()))
                sboms.append(json.loads(path.read_text()))
            if ".so" in path.name or path.suffix in {".dll", ".dylib", ".pyd"}:
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                package["installed_native_files"].append({"path": relative, "sha256": digest})
        bundle.inventory["packages"].append(package)
        native_components(bundle, name, sboms, locks)
    manifest = json.loads(Path(native_manifest).read_text())
    if manifest.get("unresolved"):
        raise ValueError("Native source manifest contains unresolved source materials")
    installed = {x["name"]: x for x in bundle.inventory["packages"]}
    for component in manifest["components"]:
        owner = installed.get(component["owner"])
        if owner is None:
            continue
        if owner["version"] != component["owner_version"]:
            raise ValueError("Native source manifest needs review for changed package version")
        source, _ = bundle.source(
            f"native/{component['name']}-{component['version']}",
            component["url"], component["sha256"],
        )
        bundle.inventory["native_components"].append({**component, "source": source})
    if base_runtime:
        collect_base(bundle)


def collect_base(bundle):
    """Preserve licenses already shipped in the unchanged pinned Python/Debian base."""
    copied = []
    for path in sorted(Path("/usr/share/doc").glob("*/copyright")):
        if path.is_file():
            copied.append(bundle.write(f"base/debian/{path.parent.name}/copyright", path.read_bytes()))
    for path in sorted(Path("/usr/share/common-licenses").glob("*")):
        if path.is_file():
            copied.append(bundle.write(f"base/debian/common-licenses/{path.name}", path.read_bytes()))
    version = ".".join(str(x) for x in sys.version_info[:3])
    source, _ = bundle.source(
        f"base/cpython-{version}",
        f"https://www.python.org/ftp/python/{version}/Python-{version}.tar.xz",
    )
    query = subprocess.check_output([
        "dpkg-query", "--show", "--showformat=${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\n",
    ], text=True)
    packages = []
    for line in query.splitlines():
        name, binary_version, source_name, source_version = line.split("\t")
        packages.append({
            "name": name, "version": binary_version,
            "source_package": source_name, "source_version": source_version,
            "source_url": f"https://snapshot.debian.org/package/{quote(source_name)}/{quote(source_version, safe='')}/",
        })
    bundle.inventory["base_runtime"] = {
        "python_version": version, "python_source": source,
        "debian_packages": packages, "retained_notices": copied,
        "scope": "Unmodified base binaries; Debian exact source versions/locations recorded, not recompiled.",
    }


def production_npm(packages):
    return sorted(
        (path, info) for path, info in packages.items()
        if path and not info.get("dev") and not info.get("link")
    )


def collect_npm(bundle, root):
    root = Path(root)
    lock = json.loads((root / "package-lock.json").read_text())
    for relative, info in production_npm(lock["packages"]):
        directory = root.joinpath(*safe_path(relative).parts)
        if info.get("optional") and not directory.exists():
            continue  # Optional packages for other platforms are not installed.
        metadata = json.loads((directory / "package.json").read_text())
        name, version = metadata["name"], metadata["version"]
        if version != info["version"]:
            raise ValueError(f"Installed npm version differs from lock: {name}")
        url = info["resolved"]
        if urlsplit(url).hostname != "registry.npmjs.org":
            raise ValueError("Expected a locked official npm archive")
        algorithm, digest = info["integrity"].split("-", 1)
        label = normalized(name.replace("/", "-")) + "-" + version
        source, _ = bundle.source(label, url, digest, algorithm)
        notices = list(source["notices"])
        for path in directory.rglob("*"):
            child = path.relative_to(directory)
            if "node_modules" in child.parts or not path.is_file():
                continue
            if any(NOTICE.fullmatch(part) for part in child.parts):
                notices.append(bundle.write(f"installed/{label}/{child.as_posix()}", path.read_bytes()))
        if not notices:
            # Some MIT packages publish only an explicit package.json/README
            # attribution. Preserve both original texts, plus the MIT terms.
            if metadata.get("license") != "MIT":
                raise ValueError(f"No retained npm license text for {name}")
            notices.append(bundle.write(f"installed/{label}/package.json", (directory / "package.json").read_bytes()))
            for path in directory.iterdir():
                if path.is_file() and path.name.lower().startswith("readme"):
                    notices.append(bundle.write(f"installed/{label}/{path.name}", path.read_bytes()))
            notices.append(bundle.write(f"installed/{label}/MIT-terms.txt", (Path(__file__).parent / "licenses/MIT.txt").read_bytes()))
        bundle.inventory["packages"].append({
            "name": name, "version": version, "license_expression": metadata.get("license"),
            "selected_license": CHOICES.get(name), "notices": notices, "sources": [source],
            "scope": "Conservative production dependency closure; may include code tree-shaken from final JS.",
        })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", choices=["python", "npm"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--requirements", action="append", default=[])
    parser.add_argument("--native-manifest", default=str(Path(__file__).parent / "licenses/native-sources.json"))
    parser.add_argument("--base-runtime", action="store_true")
    parser.add_argument("--root", default="frontend")
    args = parser.parse_args()
    bundle = Bundle(args.output, "python" if args.scope == "python" else "frontend")
    if args.scope == "python":
        if not args.requirements:
            parser.error("python collection requires --requirements")
        collect_python(bundle, args.requirements, args.native_manifest, args.base_runtime)
    else:
        collect_npm(bundle, args.root)
    bundle.finish()


if __name__ == "__main__":
    main()

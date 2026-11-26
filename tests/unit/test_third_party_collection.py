import hashlib
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/collect-third-party.py"
spec = importlib.util.spec_from_file_location("third_party_collector", SCRIPT)
assert spec and spec.loader
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def archive_bytes(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


@pytest.mark.parametrize("name", ["../LICENSE", "/LICENSE", "pkg/../../LICENSE", "pkg\\LICENSE"])
def test_source_archive_paths_cannot_escape_the_bundle(name):
    data = archive_bytes({name: b"synthetic public license"})
    with pytest.raises(ValueError, match="Unsafe"):
        list(collector.archive_files(data))


def test_zip_paths_are_checked_too():
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.writestr("../LICENSE", "synthetic")
    with pytest.raises(ValueError, match="Unsafe"):
        list(collector.archive_files(output.getvalue()))


def test_source_checksum_failure_does_not_complete_an_inventory(tmp_path, monkeypatch):
    data = archive_bytes({"example/LICENSE": b"synthetic public license"})
    monkeypatch.setattr(collector.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(data))
    bundle = collector.Bundle(tmp_path / "bundle", "python")
    with pytest.raises(ValueError, match="checksum mismatch"):
        bundle.source("example", "https://pypi.org/synthetic.tar.gz", "0" * 64)
    assert not (bundle.root / "inventory.json").exists()


def test_completed_bundle_preserves_original_notice_source_and_every_checksum(tmp_path, monkeypatch):
    notice = b"Copyright Synthetic Contributor. MIT.\n"
    data = archive_bytes({"example/LICENSE": notice, "example/source.py": b"# source\n"})
    monkeypatch.setattr(collector.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(data))
    bundle = collector.Bundle(tmp_path / "bundle", "python")
    source, _ = bundle.source("example", "https://pypi.org/synthetic.tar.gz", hashlib.sha256(data).hexdigest())
    bundle.inventory["packages"].append({
        "name": "example", "version": "1", "notices": source["notices"], "sources": [source],
    })
    bundle.finish()
    inventory = json.loads((bundle.root / "inventory.json").read_text())
    assert inventory["complete"] is True
    assert (bundle.root / source["path"]).read_bytes() == data
    assert (bundle.root / source["notices"][0]).read_bytes() == notice
    entries = (bundle.root / "SHA256SUMS").read_text().splitlines()
    names = set()
    for entry in entries:
        digest, name = entry.split("  ", 1)
        assert hashlib.sha256((bundle.root / name).read_bytes()).hexdigest() == digest
        names.add(name)
    assert "inventory.json" in names
    assert "SHA256SUMS" not in names


@pytest.mark.parametrize("missing", ["notices", "sources"])
def test_metadata_only_is_not_a_completed_distribution_bundle(tmp_path, missing):
    bundle = collector.Bundle(tmp_path / "bundle", "python")
    package = {"name": "example", "version": "1", "notices": ["license"], "sources": ["source"]}
    package[missing] = []
    bundle.inventory["packages"].append(package)
    with pytest.raises(ValueError, match="Missing notices or source"):
        bundle.finish()
    assert not (bundle.root / "inventory.json").exists()


def test_locked_requirement_set_does_not_silently_reintroduce_rfc3987(tmp_path):
    path = tmp_path / "runtime.lock"
    path.write_text("jsonschema==4.26.0\nrfc3987==1.3.8\n")
    with pytest.raises(ValueError, match="format-nongpl"):
        collector.locked_requirements([path])


def test_frontend_collection_uses_production_dependency_closure():
    packages = {
        "": {"name": "own-app"},
        "node_modules/runtime": {"version": "1"},
        "node_modules/build-tool": {"version": "2", "dev": True},
        "node_modules/optional-runtime": {"version": "3", "optional": True},
    }
    assert [path for path, _ in collector.production_npm(packages)] == [
        "node_modules/optional-runtime", "node_modules/runtime",
    ]


def test_excluded_wheel_sbom_components_are_not_claimed_as_shipped(tmp_path, monkeypatch):
    bundle = collector.Bundle(tmp_path / "bundle", "python")
    monkeypatch.setattr(bundle, "source", lambda *a, **k: pytest.fail("Excluded source fetched"))
    collector.native_components(bundle, "owner", [{"components": [{
        "name": "build-only", "version": "1", "scope": "excluded", "purl": "pkg:cargo/build-only@1",
        "hashes": [{"alg": "SHA-256", "content": "0" * 64}],
    }]}], [])
    assert bundle.inventory["native_components"] == []

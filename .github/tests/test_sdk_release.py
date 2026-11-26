import argparse
import base64
import csv
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/sdk_release.py"
spec = importlib.util.spec_from_file_location("sdk_release", SCRIPT)
sdk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk)
VERSION = "0.1.1"
REVISION = "a" * 40


class SDKReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "sdk/python"
        self.source.mkdir(parents=True)
        self.environment = patch.dict(os.environ, {
            "GITHUB_REPOSITORY": "AlexIvanchyk/Voxriva", "GITHUB_SHA": REVISION,
            "GITHUB_REF": f"refs/tags/v{VERSION}", "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "1",
            "GH_TOKEN": "synthetic-actions-token", "GITHUB_OUTPUT": str(self.root / "outputs"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        contents = {
            "pyproject.toml": f'[project]\nname="voxriva-sdk"\nversion="{VERSION}"\nlicense="MIT"\n',
            "README.md": "# SDK\n\nSynthetic SDK test description.\n",
            "LICENSE": "MIT License\nSynthetic license fixture.\n", "MANIFEST.in": "prune .venv\n",
            "tests/test_client.py": "# synthetic test source\n",
            **{f"src/voxriva_sdk/{name}": "" if name == "py.typed" else f"# {name}\n" for name in sdk.MODULE_FILES},
        }
        for name, value in contents.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        self.bundle = self.root / "candidate"
        (self.bundle / "dist").mkdir(parents=True)
        self.args = argparse.Namespace(root=self.root, version=VERSION, bundle=self.bundle,
                                       source_run="123", source_attempt="1", workflow_id="42")

    def metadata(self):
        return (f"Metadata-Version: 2.4\nName: voxriva-sdk\nVersion: {VERSION}\nRequires-Python: >=3.10\n"
                "License-Expression: MIT\nLicense-File: LICENSE\nRequires-Dist: httpx<1,>=0.28.1\n\n"
                + (self.source / "README.md").read_text()).encode()

    def wheel(self, mutate=None):
        info = f"voxriva_sdk-{VERSION}.dist-info"
        files = {f"voxriva_sdk/{name}": (self.source / f"src/voxriva_sdk/{name}").read_bytes()
                 for name in sdk.MODULE_FILES}
        files.update({f"{info}/METADATA": self.metadata(), f"{info}/licenses/LICENSE": (self.source / "LICENSE").read_bytes(),
                      f"{info}/top_level.txt": b"voxriva_sdk\n",
                      f"{info}/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"})
        if mutate:
            mutate(files)
        record = io.StringIO()
        writer = csv.writer(record, lineterminator="\n")
        for name, value in files.items():
            encoded = base64.urlsafe_b64encode(bytes.fromhex(sdk.digest(value))).rstrip(b"=").decode()
            writer.writerow([name, f"sha256={encoded}", str(len(value))])
        writer.writerow([f"{info}/RECORD", "", ""])
        files[f"{info}/RECORD"] = record.getvalue().encode()
        path = self.bundle / "dist" / f"voxriva_sdk-{VERSION}-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            for name, value in files.items():
                archive.writestr(name, value)
        return path

    def sdist(self, mutate=None):
        files = {str(path.relative_to(self.source)): path.read_bytes() for path in self.source.rglob("*") if path.is_file()}
        files.update({"PKG-INFO": self.metadata(), "setup.cfg": b"[egg_info]\ntag_build = \ntag_date = 0\n\n",
                      "src/voxriva_sdk.egg-info/PKG-INFO": self.metadata(),
                      "src/voxriva_sdk.egg-info/dependency_links.txt": b"\n",
                      "src/voxriva_sdk.egg-info/requires.txt": b"httpx<1,>=0.28.1\n",
                      "src/voxriva_sdk.egg-info/top_level.txt": b"voxriva_sdk\n"})
        manifest = "src/voxriva_sdk.egg-info/SOURCES.txt"
        # SOURCES.txt refers to the original project files, not generated sdist-only files.
        files[manifest] = ("\n".join(sorted((set(files) | {manifest}) - {"setup.cfg", "PKG-INFO"})) + "\n").encode()
        if mutate:
            mutate(files)
        path = self.bundle / "dist" / f"voxriva_sdk-{VERSION}.tar.gz"
        with tarfile.open(path, "w:gz") as archive:
            for name, value in files.items():
                entry = tarfile.TarInfo(f"voxriva_sdk-{VERSION}/{name}")
                entry.size = len(value)
                archive.addfile(entry, io.BytesIO(value))
        return path

    def sealed(self):
        self.wheel()
        self.sdist()
        sdk.seal(self.args)

    def test_publication_tag_must_match_live_commit(self):
        with patch.object(sdk, "github", return_value={"object": {"type": "commit", "sha": REVISION}}):
            sdk.require_tag(VERSION)
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}), self.assertRaises(ValueError):
            sdk.require_tag(VERSION)
        with patch.object(sdk, "github", return_value={"object": {"type": "commit", "sha": "b" * 40}}), self.assertRaises(ValueError):
            sdk.require_tag(VERSION)

    def test_reuse_rejects_other_repository_workflow_commit_attempt_and_failed_run(self):
        run = {"repository": {"full_name": "AlexIvanchyk/Voxriva"}, "head_repository": {"full_name": "AlexIvanchyk/Voxriva"},
               "workflow_id": 42, "path": sdk.WORKFLOW, "head_sha": REVISION,
               "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
        sdk.validate_reuse(run, 42)
        for key, value in (("head_repository", {"full_name": "another/fork"}), ("workflow_id", 43),
                           ("path", ".github/workflows/other.yml"), ("head_sha", "b" * 40),
                           ("event", "pull_request"), ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                sdk.validate_reuse({**run, key: value}, 42)
        self.sealed()
        self.args.source_attempt = "2"
        with self.assertRaises(ValueError):
            sdk.verify(self.args)

    def test_wheel_blocks_private_files_changed_source_missing_type_marker_and_license(self):
        sdk.wheel_check(self.wheel(), self.root, VERSION)
        mutations = [
            lambda files: files.update({".env": b"synthetic-local-state"}),
            lambda files: files.update({"voxriva_sdk/client.py": b"# changed code\n"}),
            lambda files: files.pop("voxriva_sdk/py.typed"),
            lambda files: files.update({f"voxriva_sdk-{VERSION}.dist-info/licenses/LICENSE": b"another license"}),
            lambda files: files.update({f"voxriva_sdk-{VERSION}.dist-info/METADATA": self.metadata().replace(b"License-Expression: MIT", b"License-Expression: GPL-3.0-only")}),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                sdk.wheel_check(self.wheel(mutate), self.root, VERSION)

    def test_sdist_blocks_path_traversal_and_unreviewed_sources(self):
        sdk.sdist_check(self.sdist(), self.root, VERSION)
        for name in ("../escape", ".aws/config", "build/generated.py", "src/voxriva_sdk/local.env"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                sdk.sdist_check(self.sdist(lambda files: files.update({name: b"synthetic"})), self.root, VERSION)
        with self.assertRaises(ValueError):
            sdk.sdist_check(self.sdist(lambda files: files.update({"src/voxriva_sdk/client.py": b"changed"})), self.root, VERSION)

    def test_candidate_verification_rejects_checksum_provenance_extra_files_and_links(self):
        self.sealed()
        sdk.verify(self.args)
        wheel = self.bundle / "dist" / f"voxriva_sdk-{VERSION}-py3-none-any.whl"
        original = wheel.read_bytes()
        wheel.write_bytes(original + b"trailing change")
        with self.assertRaises(ValueError):
            sdk.verify(self.args)
        wheel.write_bytes(original)
        extra = self.bundle / "private.env"
        extra.write_text("synthetic")
        with self.assertRaises(ValueError):
            sdk.verify(self.args)
        extra.unlink()
        checksum = self.bundle / "SHA256SUMS"
        saved = checksum.read_bytes()
        checksum.unlink()
        checksum.symlink_to(self.root / "outside")
        with self.assertRaises(ValueError):
            sdk.verify(self.args)
        checksum.unlink()
        checksum.write_bytes(saved)
        self.args.source_run = "456"
        with self.assertRaises(ValueError):
            sdk.verify(self.args)

    def test_only_http_404_establishes_index_absence(self):
        for status in (401, 403, 404, 429, 500):
            failure = urllib.error.HTTPError("https://pypi.org/fixture", status, "fixture", {}, None)
            with self.subTest(status=status), patch.object(sdk.urllib.request, "urlopen", side_effect=failure):
                if status == 404:
                    self.assertIsNone(sdk.request_json("https://pypi.org/fixture"))
                else:
                    with self.assertRaises(ValueError):
                        sdk.request_json("https://pypi.org/fixture")

    def test_index_requires_exact_files_and_bytes_and_never_overwrites(self):
        self.sealed()
        checksums = json.loads((self.bundle / "sdk-release.json").read_text())["sha256"]
        row = {"info": {"name": "voxriva-sdk", "version": VERSION}, "urls": [
            {"filename": Path(name).name, "digests": {"sha256": value}, "yanked": False}
            for name, value in checksums.items()]}
        sdk.index_match(row, self.bundle, VERSION)
        self.args.index, self.args.mode = "pypi", "require-absent"
        with patch.object(sdk, "require_tag"), patch.object(sdk, "request_json", return_value=row), self.assertRaises(ValueError):
            sdk.index(self.args)
        self.args.index, self.args.mode = "testpypi", "prepare-test"
        with patch.object(sdk, "require_tag"), patch.object(sdk, "request_json", return_value=row):
            sdk.index(self.args)
            self.assertIn("upload=false", (self.root / "outputs").read_text())
        row["urls"][0]["digests"]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            sdk.index_match(row, self.bundle, VERSION)
        row["urls"] = row["urls"][1:]
        with self.assertRaises(ValueError):
            sdk.index_match(row, self.bundle, VERSION)


if __name__ == "__main__":
    unittest.main()

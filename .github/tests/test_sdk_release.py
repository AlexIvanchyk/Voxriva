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
from unittest.mock import call, patch

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
                                       source_run="123", source_attempt="1", workflow_id="42", source_revision=REVISION)

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

    def test_metadata_description_preserves_utf8_and_normalizes_transport_newlines(self):
        readme = "# SDK → Voxriva\n\nСинхронне та асинхронне надсилання.\n"
        (self.source / "README.md").write_text(readme, encoding="utf-8")
        raw = self.metadata()
        sdk.metadata_check(raw, self.root, VERSION)
        sdk.metadata_check(raw.replace(b"\n", b"\r\n"), self.root, VERSION)
        sdk.wheel_check(self.wheel(), self.root, VERSION)
        sdk.sdist_check(self.sdist(), self.root, VERSION)
        for changed in (raw.replace("→".encode(), b"->"), raw.replace("Синхронне".encode(), b"changed"),
                        raw.replace("→".encode(), b"\xff")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                sdk.metadata_check(changed, self.root, VERSION)

    def test_metadata_allows_only_setuptools_added_final_newline(self):
        (self.source / "README.md").write_text("# SDK → Voxriva\n\nDescription without a final newline", encoding="utf-8")
        raw = self.metadata()
        sdk.metadata_check(raw, self.root, VERSION)
        sdk.metadata_check(raw + b"\n", self.root, VERSION)
        for changed in (raw + b"\n\n", raw + b" ", raw.replace(b"# SDK", b" # SDK")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                sdk.metadata_check(changed, self.root, VERSION)
        (self.source / "README.md").write_text("# SDK\n\nDescription with a final newline\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            sdk.metadata_check(self.metadata() + b"\n", self.root, VERSION)

    def test_publication_tag_must_match_live_commit(self):
        with patch.object(sdk, "github", return_value={"object": {"type": "commit", "sha": REVISION}}):
            sdk.require_tag(VERSION)
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}), self.assertRaises(ValueError):
            sdk.require_tag(VERSION)
        with patch.object(sdk, "github", return_value={"object": {"type": "commit", "sha": "b" * 40}}), self.assertRaises(ValueError):
            sdk.require_tag(VERSION)

    def test_reuse_rejects_other_repository_workflow_ref_attempt_and_failed_run(self):
        run = {"repository": {"full_name": "AlexIvanchyk/Voxriva"}, "head_repository": {"full_name": "AlexIvanchyk/Voxriva"},
               "workflow_id": 42, "path": sdk.WORKFLOW, "head_sha": REVISION,
               "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
        sdk.validate_reuse(run, 42)
        for key, value in (("head_repository", {"full_name": "another/fork"}), ("workflow_id", 43),
                           ("path", ".github/workflows/other.yml"), ("head_sha", "refs/heads/main"),
                           ("event", "pull_request"), ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                sdk.validate_reuse({**run, key: value}, 42)
        self.sealed()
        self.args.source_attempt = "2"
        with self.assertRaises(ValueError):
            sdk.verify(self.args)

    def test_reuse_across_commits_requires_identical_entire_sdk_git_tree(self):
        run = {"repository": {"full_name": "AlexIvanchyk/Voxriva"}, "head_repository": {"full_name": "AlexIvanchyk/Voxriva"},
               "workflow_id": 42, "path": sdk.WORKFLOW, "head_sha": "b" * 40,
               "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
        with patch.object(sdk, "sdk_tree", return_value="c" * 40) as lookup:
            sdk.validate_reuse(run, 42)
            self.assertEqual(lookup.call_args_list, [call("b" * 40), call(REVISION)])
        with patch.object(sdk, "sdk_tree", side_effect=["c" * 40, "d" * 40]), self.assertRaises(ValueError):
            sdk.validate_reuse(run, 42)
        # Verification binds the original source revision provided by plan, not
        # the publisher revision and never a revision read from the manifest.
        self.sealed()
        with patch.dict(os.environ, {"GITHUB_SHA": "b" * 40}):
            sdk.verify(self.args)
            self.args.source_revision = "b" * 40
            with self.assertRaises(ValueError):
                sdk.verify(self.args)
            self.args.source_revision = REVISION
            (self.source / "README.md").write_text("Changed README\n")
            with self.assertRaises(ValueError):
                sdk.verify(self.args)

    def test_sdk_tree_uses_immutable_git_objects_and_rejects_refs_and_symlinks(self):
        root, child, expected = "c" * 40, "d" * 40, "e" * 40
        responses = {
            f"git/commits/{REVISION}": {"sha": REVISION, "tree": {"sha": root}},
            f"git/trees/{root}": {"sha": root, "truncated": False, "tree": [
                {"path": "sdk", "mode": "040000", "type": "tree", "sha": child}]},
            f"git/trees/{child}": {"sha": child, "truncated": False, "tree": [
                {"path": "python", "mode": "040000", "type": "tree", "sha": expected}]},
        }
        with patch.object(sdk, "github", side_effect=responses.__getitem__) as api:
            self.assertEqual(sdk.sdk_tree(REVISION), expected)
            self.assertEqual(api.call_count, 3)
        for revision in ("main", "refs/tags/v0.1.1", REVISION[:7]):
            with self.subTest(revision=revision), patch.object(sdk, "github") as api, self.assertRaises(ValueError):
                sdk.sdk_tree(revision)
            api.assert_not_called()
        responses[f"git/trees/{root}"]["truncated"] = True
        with patch.object(sdk, "github", side_effect=responses.__getitem__), self.assertRaises(ValueError):
            sdk.sdk_tree(REVISION)
        responses[f"git/trees/{root}"]["truncated"] = False
        responses[f"git/trees/{child}"]["tree"][0].update({"mode": "120000", "type": "blob"})
        with patch.object(sdk, "github", side_effect=responses.__getitem__), self.assertRaises(ValueError):
            sdk.sdk_tree(REVISION)

    def install_jobs(self, run):
        return {"total_count": 4, "jobs": [
            {"name": f"install ({python}, {format})", "run_id": run["id"], "run_attempt": run["run_attempt"],
             "head_sha": run["head_sha"], "status": "completed", "conclusion": "success"}
            for python in ("3.10", "3.13") for format in ("wheel", "sdist")]}

    def test_all_four_install_jobs_must_pass_in_exact_candidate_attempt(self):
        run = {"id": 456, "run_attempt": 2, "head_sha": REVISION}
        sdk.validate_install_jobs(self.install_jobs(run), run)
        for key, value in (("run_id", 999), ("run_attempt", 1), ("head_sha", "b" * 40),
                           ("conclusion", "failure"), ("conclusion", "skipped"), ("status", "in_progress")):
            jobs = self.install_jobs(run)
            jobs["jobs"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                sdk.validate_install_jobs(jobs, run)
        jobs = self.install_jobs(run)
        jobs["jobs"].pop()
        jobs["total_count"] = 3
        with self.assertRaises(ValueError):
            sdk.validate_install_jobs(jobs, run)

    def test_reuse_plan_exports_original_revision_and_rejects_another_artifact_source(self):
        run = {"id": 456, "run_attempt": 1, "head_sha": "b" * 40,
               "repository": {"full_name": "AlexIvanchyk/Voxriva"}, "head_repository": {"full_name": "AlexIvanchyk/Voxriva"},
               "workflow_id": 42, "path": sdk.WORKFLOW, "event": "workflow_dispatch", "status": "completed", "conclusion": "success"}
        artifact = {"id": 789, "name": f"sdk-{VERSION}-{'b' * 40}-456-1", "expired": False, "size_in_bytes": 100,
                    "workflow_run": {"id": 456, "head_sha": "b" * 40}}
        responses = {"actions/workflows/sdk-release.yml": {"id": 42}, "actions/runs/456": run,
                     "actions/runs/456/attempts/1/jobs?per_page=100": self.install_jobs(run),
                     "actions/runs/456/artifacts?per_page=100": {"artifacts": [artifact]}}
        args = argparse.Namespace(root=self.root, version=VERSION, target="candidate", candidate_run_id="456")
        with patch.object(sdk, "github", side_effect=responses.__getitem__), patch.object(sdk, "sdk_tree", return_value="c" * 40):
            sdk.plan(args)
        outputs = (self.root / "outputs").read_text()
        self.assertIn("source_revision=" + "b" * 40, outputs)
        self.assertIn("artifact=" + artifact["name"], outputs)
        artifact["workflow_run"]["head_sha"] = REVISION
        with patch.object(sdk, "github", side_effect=responses.__getitem__), patch.object(sdk, "sdk_tree", return_value="c" * 40), self.assertRaises(ValueError):
            sdk.plan(args)

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

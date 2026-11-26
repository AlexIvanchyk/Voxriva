import copy
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/release_metadata.py"
spec = importlib.util.spec_from_file_location("candidate_metadata", SCRIPT)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)
publish_spec = importlib.util.spec_from_file_location("candidate_publish", SCRIPT.with_name("publish.py"))
publish = importlib.util.module_from_spec(publish_spec)
publish_spec.loader.exec_module(publish)
REVISION = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64


class CandidateReuseTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {
            "GITHUB_REPOSITORY": "example/source", "GITHUB_REPOSITORY_ID": "7",
            "GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "1",
            "PUBLISH_REQUESTED": "false",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.prefix = "repos/example/source/actions"
        now = datetime.now(UTC)
        self.workflow = {"id": 42, "path": metadata.RELEASE_WORKFLOW, "state": "active"}
        self.run = {
            "id": 123, "workflow_id": 42, "path": metadata.RELEASE_WORKFLOW + "@main",
            "event": "workflow_dispatch", "status": "completed", "conclusion": "success",
            "head_sha": REVISION, "run_attempt": 2,
            "repository": {"id": 7, "full_name": "example/source"},
            "head_repository": {"id": 7, "full_name": "example/source"},
            "run_started_at": (now - timedelta(hours=1)).isoformat(),
        }
        self.jobs = [
            {"name": ("checks / " if name not in {"preflight", "package"} else "") + name,
             "status": "completed", "conclusion": "success"}
            for name in sorted(metadata.REQUIRED_CANDIDATE_JOBS)
        ] + [{"name": "publish", "status": "completed", "conclusion": "skipped"}]
        self.artifact = {
            "id": 456, "name": f"release-0.1.1-{REVISION}-123-2",
            "expired": False, "size_in_bytes": 100,
            "created_at": (now - timedelta(minutes=30)).isoformat(),
            "expires_at": (now + timedelta(days=1)).isoformat(),
            "digest": "sha256:" + "c" * 64,
            "workflow_run": {"id": 123, "repository_id": 7, "head_repository_id": 7, "head_sha": REVISION},
        }

    def select(self, **kwargs):
        responses = {
            f"{self.prefix}/workflows/release.yml": self.workflow,
            f"{self.prefix}/runs/123": self.run,
            f"{self.prefix}/runs/123/attempts/{self.run['run_attempt']}/jobs?per_page=100&page=1": {"jobs": self.jobs},
            f"{self.prefix}/runs/123/artifacts?per_page=100&page=1": {"artifacts": [self.artifact]},
        }
        with patch.object(metadata, "github_json", side_effect=lambda path: copy.deepcopy(responses[path])):
            return metadata.select_candidate("123", "0.1.1", REVISION, **kwargs)

    def test_completed_full_candidate_has_source_identity_separate_from_publisher(self):
        selected = self.select(expected_attempt="2", expected_artifact_id="456")
        self.assertEqual(selected["run_id"], "123")
        self.assertEqual(selected["run_attempt"], "2")
        self.assertEqual(selected["artifact_id"], "456")
        self.assertEqual(selected["validated_for_run_id"], "999")

    def test_other_repository_workflow_event_commit_or_failed_run_is_rejected(self):
        baseline = copy.deepcopy(self.run)
        for field, value in (
            ("event", "pull_request"), ("head_sha", "d" * 40),
            ("workflow_id", 43), ("path", ".github/workflows/other.yml"),
            ("status", "in_progress"), ("conclusion", "failure"),
            ("repository", {"id": 8, "full_name": "example/source"}),
            ("head_repository", {"id": 8, "full_name": "fork/source"}),
        ):
            self.run = {**copy.deepcopy(baseline), field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.select()
        self.run = baseline
        with self.assertRaises(ValueError):
            self.select(expected_attempt="1")
        with self.assertRaises(ValueError):
            self.select(expected_artifact_id="455")

    def test_missing_skipped_or_failed_ci_runtime_and_publish_gates_are_rejected(self):
        baseline = copy.deepcopy(self.jobs)
        for name, conclusion in (("trivy", "skipped"), ("e2e (cloud)", "failure"), ("package", "skipped"), ("publish", "success")):
            self.jobs = copy.deepcopy(baseline)
            next(job for job in self.jobs if job["name"].rsplit(" / ", 1)[-1] == name)["conclusion"] = conclusion
            with self.subTest(job=name), self.assertRaises(ValueError):
                self.select()
        self.jobs = [job for job in baseline if job["name"] != "checks / ci-ready"]
        with self.assertRaises(ValueError):
            self.select()

    def test_expired_artifacts_wrong_run_or_attempt_and_origin_are_rejected(self):
        baseline = copy.deepcopy(self.artifact)
        for field, value in (
            ("expired", True), ("expires_at", "2000-01-01T00:00:00Z"),
            ("name", f"release-0.1.1-{REVISION}-123-1"),
            ("digest", "missing"),
            ("workflow_run", {"id": 124, "repository_id": 7, "head_repository_id": 7, "head_sha": REVISION}),
        ):
            self.artifact = {**copy.deepcopy(baseline), field: value}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.select()

    def test_reused_bundle_requires_api_approved_source_run_and_unchanged_checksums(self):
        selected = self.select()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for role, archive in (("application", "voxriva-image.tar"), ("mcp", "voxriva-mcp-image.tar")):
                directory = root / role
                directory.mkdir()
                (directory / archive).write_bytes(b"exact tested image archive")
                (directory / "SHA256SUMS").write_text("fixture index")
                (directory / "APP-CHECKS-PASSED").write_text("fixture evidence")
                metadata.write_json(directory / "image-inspect.json", [{
                    "Id": IMAGE_ID, "Config": {"Labels": {"org.opencontainers.image.revision": REVISION}},
                }])
            with patch.dict(os.environ, {"GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2"}):
                metadata.index_bundle(root, "0.1.1", REVISION, "example/app", "example/mcp")
            with self.assertRaises(ValueError):
                metadata.verify_bundle(root, "0.1.1", REVISION, "example/app", "example/mcp")
            metadata.verify_bundle(root, "0.1.1", REVISION, "example/app", "example/mcp", selected)
            for version, app, source in (
                ("0.1.2", "example/app", selected),
                ("0.1.1", "example/other", selected),
                ("0.1.1", "example/app", {**selected, "run_attempt": "1"}),
                ("0.1.1", "example/app", {**selected, "validated_for_run_id": "998"}),
            ):
                with self.subTest(version=version, app=app), self.assertRaises(ValueError):
                    metadata.verify_bundle(root, version, REVISION, app, "example/mcp", source)
            (root / "mcp/voxriva-mcp-image.tar").write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                metadata.verify_bundle(root, "0.1.1", REVISION, "example/app", "example/mcp", selected)

    def test_api_failure_never_becomes_a_valid_reuse_or_a_fallback_build(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr="fixture API failure")
        with patch.object(metadata.subprocess, "run", return_value=result):
            with self.assertRaises(ValueError):
                metadata.select_candidate("123", "0.1.1", REVISION)

    def test_download_requires_the_api_archive_digest_before_extraction(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("release.json", "synthetic manifest")
        payload = buffer.getvalue()
        self.artifact["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
        selected = self.select()

        def download(command, **kwargs):
            self.assertTrue(command[-1].endswith("/456/zip"))
            kwargs["stdout"].write(payload)
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(metadata, "github_json", return_value=self.artifact), patch.object(metadata.subprocess, "run", side_effect=download):
                metadata.download_bundle(root / "candidate", "0.1.1", REVISION, "456", selected)
                self.assertEqual((root / "candidate/release.json").read_text(), "synthetic manifest")
                self.artifact["digest"] = "sha256:" + "0" * 64
                selected["artifact_digest"] = self.artifact["digest"]
                with self.assertRaises(ValueError):
                    metadata.download_bundle(root / "corrupt", "0.1.1", REVISION, "456", selected)
                self.assertFalse((root / "corrupt").exists())

    def test_correctly_hashed_zip_still_cannot_escape_the_candidate_directory(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../outside", "unsafe")
        payload = buffer.getvalue()
        self.artifact["digest"] = "sha256:" + hashlib.sha256(payload).hexdigest()
        selected = self.select()

        def download(command, **kwargs):
            kwargs["stdout"].write(payload)
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(metadata, "github_json", return_value=self.artifact), patch.object(metadata.subprocess, "run", side_effect=download), self.assertRaises(ValueError):
                metadata.download_bundle(root / "candidate", "0.1.1", REVISION, "456", selected)
            self.assertFalse((root / "outside").exists())


class NoticeEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "third-party/python"
        self.directory.mkdir(parents=True)
        (self.directory / "LICENSE").write_text("Synthetic upstream notice")
        (self.directory / "source.tar.gz").write_bytes(b"synthetic corresponding source")
        self.inventory = {
            "schema_version": 1, "scope": "python", "complete": True,
            "packages": [{
                "name": "synthetic", "version": "1.0", "notices": ["LICENSE"],
                "sources": [{"path": "source.tar.gz", "sha256": metadata.digest(self.directory / "source.tar.gz")}],
            }],
        }

    def index(self):
        metadata.write_json(self.directory / "inventory.json", self.inventory)
        (self.directory / "SHA256SUMS").write_text("".join(
            f"{metadata.digest(path)}  {path.name}\n"
            for path in sorted(self.directory.iterdir()) if path.name != "SHA256SUMS"
        ))

    def test_complete_retained_notices_and_source_inventory_is_required(self):
        self.index()
        metadata.verify_notices(self.root, ["python"])
        self.inventory["complete"] = False
        self.index()
        with self.assertRaises(ValueError):
            metadata.verify_notices(self.root, ["python"])
        self.inventory["complete"] = True
        self.inventory["packages"][0]["notices"] = []
        self.index()
        with self.assertRaises(ValueError):
            metadata.verify_notices(self.root, ["python"])

    def test_retained_source_hashes_and_complete_index_cannot_be_bypassed(self):
        self.index()
        (self.directory / "source.tar.gz").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            metadata.verify_notices(self.root, ["python"])
        self.index()  # Even a recomputed file index must match the source inventory.
        with self.assertRaises(ValueError):
            metadata.verify_notices(self.root, ["python"])


class PartialPublicationTests(unittest.TestCase):
    def test_second_image_failure_retains_first_digest_and_both_run_identities(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = {
                role: {"reference": f"ghcr.io/example/{package}:0.1.1", "image_id": IMAGE_ID}
                for role, package in (("application", "app"), ("mcp", "mcp"))
            }
            metadata.write_json(root / "release.json", {
                "source": "example/source", "run_id": "123", "run_attempt": "2",
                "version": "0.1.1", "revision": REVISION, "images": images,
            })
            metadata.write_json(root / "config.json", {"auths": {"ghcr.io": {"auth": "synthetic"}}})
            environment = {
                "RELEASE_OUTPUT": str(root), "DOCKER_CONFIG": str(root), "RUNNER_TEMP": str(root),
                "APPLICATION_PACKAGE": "example/app", "MCP_PACKAGE": "example/mcp",
                "GITHUB_RUN_ID": "999", "GITHUB_RUN_ATTEMPT": "1",
            }
            responses = [(404, None), (404, None), (200, "sha256:" + "d" * 64)]
            failure = subprocess.CalledProcessError(1, ["docker", "push"])
            with patch.dict(os.environ, environment), patch.object(publish, "registry_head", side_effect=responses), patch.object(
                publish.subprocess, "run", side_effect=[None, failure]
            ), self.assertRaises(subprocess.CalledProcessError):
                publish.main()
            evidence = json.loads((root / "published-digests.json").read_text())
            self.assertFalse(evidence["complete"])
            self.assertEqual(set(evidence["images"]), {"application"})
            self.assertEqual(evidence["images"]["application"]["image_id"], IMAGE_ID)
            self.assertEqual(evidence["candidate"]["run_id"], "123")
            self.assertEqual(evidence["publisher"]["run_id"], "999")


class GitHubReleaseTests(unittest.TestCase):
    def test_release_needs_complete_matching_digests_and_only_uploads_selected_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            operator = root / "Voxriva-0.1.1-operator.tar.gz"
            operator.write_bytes(b"exact tested operator")
            notes = root / "notes.md"
            notes.write_text("Source release notes")
            data = {
                "source": "example/source", "run_id": "123", "run_attempt": "2",
                "version": "0.1.1", "revision": REVISION,
                "images": {role: {"reference": f"ghcr.io/example/{role}:0.1.1", "image_id": IMAGE_ID} for role in ("application", "mcp")},
            }
            metadata.write_json(root / "release.json", data)
            published = {
                "version": "0.1.1", "revision": REVISION, "complete": True,
                "candidate": {key: data[key] for key in ("source", "run_id", "run_attempt")},
                "publisher": {"run_id": "999", "run_attempt": "1"},
                "images": {role: {**record, "manifest_digest": "sha256:" + "d" * 64} for role, record in data["images"].items()},
            }
            evidence = root / "published-digests.json"
            helper = SimpleNamespace(
                require_remote_revision=Mock(), require_absent_release=Mock(),
                release_notes=lambda text, version, repository: text,
            )
            environment = {
                "GITHUB_REPOSITORY": "example/source", "GITHUB_RUN_ID": "999",
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF": "refs/tags/v0.1.1", "RUNNER_TEMP": str(root),
            }

            def release(command, **kwargs):
                self.assertEqual(command[:4], ["gh", "release", "create", "v0.1.1"])
                self.assertIn("--verify-tag", command)
                self.assertIn("--prerelease", command)
                self.assertNotIn("--clobber", command)
                self.assertEqual({Path(name).name for name in command[-4:]}, {operator.name, "OPERATOR-SHA256SUMS", "release.json", "published-digests.json"})
                checksum_file = next(Path(name) for name in command[-4:] if name.endswith("OPERATOR-SHA256SUMS"))
                self.assertEqual(checksum_file.read_text(), f"{metadata.digest(operator)}  {operator.name}\n")

            with patch.dict(os.environ, environment), patch.dict(sys.modules, {"source_release": helper}), patch.object(metadata, "verify_bundle"), patch.object(metadata.subprocess, "run", side_effect=release) as publish_command:
                for changes in ({"complete": False}, {"publisher": {"run_id": "998", "run_attempt": "1"}}):
                    metadata.write_json(evidence, {**published, **changes})
                    with self.assertRaises(ValueError):
                        metadata.create_github_release(root, evidence, notes, "0.1.1", REVISION, "example/application", "example/mcp")
                publish_command.assert_not_called()
                metadata.write_json(evidence, published)
                metadata.create_github_release(root, evidence, notes, "0.1.1", REVISION, "example/application", "example/mcp")
                publish_command.assert_called_once()
            helper.require_remote_revision.assert_called_once_with("example/source", "v0.1.1", REVISION)
            helper.require_absent_release.assert_called_once_with("example/source", "v0.1.1")


if __name__ == "__main__":
    unittest.main()

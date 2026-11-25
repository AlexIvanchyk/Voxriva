import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


metadata = load("release_metadata")
publish = load("publish")
changed_paths = load("changed_paths")
REVISION = "a" * 40
IMAGE_ID = "sha256:" + "b" * 64


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def junit(self, extra="", omitted=None):
        tests = sorted(set().union(*metadata.SECURITY_TESTS.values()) - {omitted})
        path = self.root / "junit.xml"
        path.write_text(
            "<testsuites><testsuite>"
            + "".join(f'<testcase name="{name}"/>' for name in tests)
            + extra
            + "</testsuite></testsuites>"
        )
        return path

    def test_source_evidence_requires_real_successful_security_cases(self):
        output = self.root / "source.json"
        metadata.source_evidence(self.junit(), REVISION, output)
        result = json.loads(output.read_text())
        self.assertEqual(result["revision"], REVISION)
        self.assertEqual(set(result["checks"]), set(metadata.SECURITY_TESTS))
        with self.assertRaises(ValueError):
            metadata.source_evidence(
                self.junit(omitted="test_session_security_rotation_and_csrf"),
                REVISION,
                output,
            )
        for extra in (
            '<testcase name="other"><failure/></testcase>',
            '<testcase name="other"><error/></testcase>',
        ):
            with self.assertRaises(ValueError):
                metadata.source_evidence(self.junit(extra), REVISION, output)

    def test_skipped_security_test_does_not_count_as_passed(self):
        path = self.junit()
        path.write_text(
            path.read_text().replace(
                'name="test_session_security_rotation_and_csrf"/>',
                'name="test_session_security_rotation_and_csrf"><skipped/></testcase>',
            )
        )
        with self.assertRaises(ValueError):
            metadata.source_evidence(path, REVISION, self.root / "source.json")

    def test_source_evidence_is_explicitly_bound_to_the_image_revision(self):
        source = self.root / "source.json"
        metadata.source_evidence(self.junit(), REVISION, source)
        inspect = self.root / "inspect.json"
        image = {
            "Id": IMAGE_ID,
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": REVISION,
                    "org.opencontainers.image.version": "0.1.0",
                }
            },
        }
        metadata.write_json(inspect, [image])
        output = self.root / "bound.json"
        metadata.bind_evidence(
            source, inspect, "0.1.0", REVISION, "synthetic-successful-smoke", output
        )
        bound = json.loads(output.read_text())
        self.assertEqual(bound["image_id"], IMAGE_ID)
        self.assertEqual(bound["checks"]["runtime_smoke"]["status"], "passed")
        for field, changed in (("Architecture", "arm64"), ("Os", "windows")):
            metadata.write_json(inspect, [{**image, field: changed}])
            with self.assertRaises(ValueError):
                metadata.bind_evidence(
                    source, inspect, "0.1.0", REVISION, "smoke", output
                )
        metadata.write_json(inspect, [image])
        with self.assertRaises(ValueError):
            metadata.bind_evidence(source, inspect, "0.1.0", "c" * 40, "smoke", output)

    def project(self):
        (self.root / "sdk/python").mkdir(parents=True)
        (self.root / "frontend").mkdir()
        for file in ("pyproject.toml", "sdk/python/pyproject.toml"):
            (self.root / file).write_text('[project]\nversion="0.1.0"\n')
        metadata.write_json(self.root / "frontend/package.json", {"version": "0.1.0"})

    @patch.dict(
        os.environ,
        {
            "GITHUB_REPOSITORY_OWNER": "Example",
            "PUBLISH_REQUESTED": "true",
            "GITHUB_REF": "refs/tags/v0.1.0",
        },
    )
    def test_publish_request_requires_versions_namespace_and_matching_tag(self):
        self.project()
        metadata.validate_request(
            "0.1.0", REVISION, "example/app", "example/mcp", self.root
        )
        for version, app, mcp in (
            ("0.2.0", "example/app", "example/mcp"),
            ("0.1.0", "other/app", "example/mcp"),
            ("0.1.0", "example/app", "example/app"),
            ("0.1.0", "example/APP", "example/mcp"),
        ):
            with self.assertRaises(ValueError):
                metadata.validate_request(version, REVISION, app, mcp, self.root)
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}):
            with self.assertRaises(ValueError):
                metadata.validate_request(
                    "0.1.0", REVISION, "example/app", "example/mcp", self.root
                )

    @patch.dict(
        os.environ,
        {
            "GITHUB_REPOSITORY": "example/source",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
        },
    )
    def test_bundle_is_complete_immutable_and_detects_tampering(self):
        for role in ("application", "mcp"):
            path = self.root / role
            path.mkdir()
            (path / "APP-CHECKS-PASSED").write_text("synthetic fixture")
            (path / "SHA256SUMS").write_text("synthetic inner index")
            metadata.write_json(
                path / "image-inspect.json",
                [
                    {
                        "Id": IMAGE_ID,
                        "Config": {
                            "Labels": {"org.opencontainers.image.revision": REVISION}
                        },
                    }
                ],
            )
            (
                path
                / (
                    "voxriva-image.tar"
                    if role == "application"
                    else "voxriva-mcp-image.tar"
                )
            ).write_bytes(b"synthetic archive")
        metadata.index_bundle(
            self.root, "0.1.0", REVISION, "example/app", "example/mcp"
        )
        metadata.verify_bundle(
            self.root, "0.1.0", REVISION, "example/app", "example/mcp"
        )
        with self.assertRaises(ValueError):
            metadata.index_bundle(
                self.root, "0.1.0", REVISION, "example/app", "example/mcp"
            )
        with self.assertRaises(ValueError):
            metadata.verify_bundle(
                self.root, "0.1.0", "c" * 40, "example/app", "example/mcp"
            )
        (self.root / "unindexed.txt").write_text("must not slip into a release")
        with self.assertRaises(ValueError):
            metadata.verify_bundle(
                self.root, "0.1.0", REVISION, "example/app", "example/mcp"
            )
        (self.root / "unindexed.txt").unlink()
        (self.root / "mcp/voxriva-mcp-image.tar").write_bytes(b"changed archive")
        with self.assertRaises(ValueError):
            metadata.verify_bundle(
                self.root, "0.1.0", REVISION, "example/app", "example/mcp"
            )


class RegistryAbsenceTests(unittest.TestCase):
    def test_auth_failure_never_counts_as_an_absent_version(self):
        for code in (401, 403, 429, 500):
            error = urllib.error.HTTPError(
                "https://ghcr.io/token", code, "fixture", {}, None
            )
            with patch.object(publish.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(RuntimeError):
                    publish.registry_head("example/app", "0.1.0", "synthetic-auth")

    def test_only_manifest_404_counts_as_absent(self):
        error = urllib.error.HTTPError(
            "https://ghcr.io/v2/example/app/manifests/0.1.0", 404, "fixture", {}, None
        )
        with patch.object(publish.urllib.request, "urlopen", side_effect=error):
            self.assertEqual(
                publish.registry_head("example/app", "0.1.0", "synthetic-auth"),
                (404, None),
            )
        error = urllib.error.HTTPError(
            "https://ghcr.io/token", 404, "fixture", {}, None
        )
        with patch.object(publish.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(RuntimeError):
                publish.registry_head("example/app", "0.1.0", "synthetic-auth")

    def test_network_failure_never_counts_as_absent(self):
        with patch.object(
            publish.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("synthetic failure"),
        ):
            with self.assertRaises(RuntimeError):
                publish.registry_head("example/app", "0.1.0", "synthetic-auth")


class DocumentationScopeTests(unittest.TestCase):
    def test_documentation_only_changes_skip_runtime(self):
        self.assertFalse(
            changed_paths.runtime_required(
                [
                    "docs/mfa.md",
                    "README.md",
                    "docs/product-development-plan.md",
                    "mkdocs.yml",
                    "requirements-docs.txt",
                    "requirements-docs.in",
                    ".github/workflows/pages.yml",
                ]
            )
        )

    def test_source_dependency_test_or_ci_changes_require_runtime(self):
        for path in (
            "backend/app/main.py",
            "frontend/package-lock.json",
            "tests/integration/test_images.py",
            "Dockerfile",
            ".github/scripts/changed_paths.py",
            ".github/workflows/ci.yml",
            "requirements-runtime.lock",
        ):
            self.assertTrue(
                changed_paths.runtime_required(["README.md", path]), path
            )

    def test_missing_git_history_fails_closed_and_diff_disables_rename_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event = root / "event.json"
            event.write_text(json.dumps({"pull_request": {"base": {"sha": "c" * 40}}}))
            output = root / "output"
            with patch.dict(
                os.environ,
                {
                    "GITHUB_EVENT_PATH": str(event),
                    "GITHUB_EVENT_NAME": "pull_request",
                    "GITHUB_SHA": REVISION,
                    "GITHUB_OUTPUT": str(output),
                },
            ):
                result = subprocess.CompletedProcess([], 1, stdout=b"")
                with patch.object(
                    changed_paths.subprocess, "run", return_value=result
                ) as command:
                    changed_paths.main()
                self.assertIn("--no-renames", command.call_args.args[0])
                self.assertEqual(output.read_text(), "runtime=true\n")


class SuiteFailureTests(unittest.TestCase):
    def test_mcp_smoke_failure_is_preserved_after_compose_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docker = root / "docker"
            docker.write_text(
                '#!/usr/bin/env bash\nfor arg in "$@"; do if [[ "$arg" = exec ]]; then exit 37; fi; done\nexit 0\n'
            )
            docker.chmod(0o700)
            environment = {
                **os.environ,
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "CI_ARTIFACT_DIR": str(root / "artifacts"),
                "CI_MCP_IMAGE": IMAGE_ID,
            }
            result = subprocess.run(
                ["bash", str(SCRIPTS / "e2e.sh"), "mcp"],
                env=environment,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 37, result.stderr.decode())
            summary = json.loads((root / "artifacts/mcp/summary.json").read_text())
            self.assertEqual(summary["exit_code"], 37)


if __name__ == "__main__":
    unittest.main()

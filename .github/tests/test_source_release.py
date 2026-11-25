import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/source_release.py"
spec = importlib.util.spec_from_file_location("source_release", SCRIPT)
source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
REVISION = "a" * 40


class SourceReleaseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "GITHUB_REPOSITORY": "example/source",
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_REF": "refs/tags/v0.1.0",
        })
        environment.start()
        self.addCleanup(environment.stop)
        (self.root / "sdk/python").mkdir(parents=True)
        (self.root / "frontend").mkdir()
        for relative in ("pyproject.toml", "sdk/python/pyproject.toml"):
            (self.root / relative).write_text('[project]\nversion="0.1.0"\n')
        (self.root / "frontend/package.json").write_text('{"version":"0.1.0"}')

    def candidate(self):
        output = self.root / "candidate"
        output.mkdir()
        for name in source.filenames("0.1.0"):
            (output / name).write_text("synthetic source artifact\n")
        (output / "source-release.json").write_text(
            json.dumps(source.provenance("0.1.0", REVISION))
        )
        (output / "SHA256SUMS").write_text("".join(
            f"{source.checksum(output / name)}  {name}\n"
            for name in sorted(source.filenames("0.1.0"))
        ))
        return output

    def test_source_paths_reject_local_state_but_allow_public_test_fixtures(self):
        for path in (
            ".env", ".env.production", "production.env",
            "secrets/tls.key", ".aws/config", "output/report.json",
            "release/image.tar", "frontend/node_modules/index.js",
            "data.sqlite3", "../escape", "README.md\nunsafe",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                source.validate_source_entry("100644", path)
        for path in (
            "deploy/production.env.example",
            "frontend/e2e/fixtures/ses-events/signing-key.pem",
            ".github/workflows/source-release.yml",
        ):
            source.validate_source_entry("100644", path)
        for mode in ("120000", "160000"):
            with self.assertRaises(ValueError):
                source.validate_source_entry(mode, "external")

    def test_publish_requires_matching_version_and_tag(self):
        source.validate_request(self.root, "0.1.0", REVISION, True)
        for version, revision in (("v0.1.0", REVISION), ("0.2.0", REVISION), ("0.1.0", "HEAD")):
            with self.assertRaises(ValueError):
                source.validate_request(self.root, version, revision, True)
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}):
            source.validate_request(self.root, "0.1.0", REVISION, False)
            with self.assertRaises(ValueError):
                source.validate_request(self.root, "0.1.0", REVISION, True)

    def test_archives_and_notes_are_read_from_the_selected_git_commit(self):
        output = self.root / "source"
        calls = []

        def git_output(command, **kwargs):
            calls.append(command)
            if command[1] == "rev-parse":
                return REVISION + "\n"
            if command[1] == "ls-tree":
                return b"100644 blob " + b"b" * 40 + b"\tREADME.md\0"
            self.assertEqual(command[-1], f"{REVISION}:docs/releases/0.1.0.md")
            return b"Reviewed source-only notes\n"

        def archive(command, **kwargs):
            self.assertEqual(command[-1], REVISION)
            self.assertIn("--prefix=Voxriva-0.1.0/", command)
            destination = next(value for value in command if value.startswith("--output="))
            Path(destination.removeprefix("--output=")).write_bytes(b"synthetic archive")

        with patch.object(source.subprocess, "check_output", side_effect=git_output), patch.object(
            source.subprocess, "run", side_effect=archive
        ) as archives:
            source.package_source(self.root, output, "0.1.0", REVISION)
        self.assertEqual(archives.call_count, 2)
        self.assertEqual((output / "RELEASE_NOTES.md").read_bytes(), b"Reviewed source-only notes\n")
        source.verify_source(output, "0.1.0", REVISION)
        with self.assertRaises(ValueError):
            source.package_source(self.root, output, "0.1.0", REVISION)

    def test_artifact_verification_blocks_tampering_extra_files_and_wrong_run(self):
        output = self.candidate()
        source.verify_source(output, "0.1.0", REVISION)
        with patch.dict(os.environ, {"GITHUB_RUN_ID": "456"}), self.assertRaises(ValueError):
            source.verify_source(output, "0.1.0", REVISION)
        extra = output / "private.env"
        extra.write_text("synthetic")
        with self.assertRaises(ValueError):
            source.verify_source(output, "0.1.0", REVISION)
        extra.unlink()
        (output / "RELEASE_NOTES.md").write_text("changed")
        with self.assertRaises(ValueError):
            source.verify_source(output, "0.1.0", REVISION)

    def test_only_http_404_establishes_release_absence(self):
        for status, exit_code, accepted in ((404, 1, True), (200, 0, False), (401, 1, False), (403, 1, False), (500, 1, False), (None, 1, False)):
            stdout = f"HTTP/2.0 {status} fixture\n\n{{}}" if status else ""
            result = subprocess.CompletedProcess([], exit_code, stdout=stdout, stderr="fixture")
            with self.subTest(status=status), patch.object(source.subprocess, "run", return_value=result):
                if accepted:
                    source.require_absent_release("example/source", "v0.1.0")
                else:
                    with self.assertRaises(ValueError):
                        source.require_absent_release("example/source", "v0.1.0")

    def test_publish_uses_verified_allowlisted_assets_and_prerelease_flags(self):
        output = self.candidate()
        with patch.object(source, "require_remote_revision") as remote, patch.object(source, "require_absent_release") as absent, patch.object(source.subprocess, "run") as run:
            source.publish_source(output, "0.1.0", REVISION)
        remote.assert_called_once_with("example/source", "v0.1.0", REVISION)
        absent.assert_called_once_with("example/source", "v0.1.0")
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["gh", "release", "create", "v0.1.0"])
        self.assertIn("--prerelease", command)
        self.assertIn("--verify-tag", command)
        self.assertIn("--latest=false", command)
        self.assertNotIn("--clobber", command)
        self.assertEqual(set(command[-5:]), {str(output / name) for name in source.filenames("0.1.0") | {"SHA256SUMS"}})
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}), patch.object(source.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                source.publish_source(output, "0.1.0", REVISION)
            run.assert_not_called()

    def test_moved_remote_tag_cannot_publish_tested_source_as_another_commit(self):
        with patch.object(source.subprocess, "check_output", return_value=REVISION + "\n"):
            source.require_remote_revision("example/source", "v0.1.0", REVISION)
        with patch.object(source.subprocess, "check_output", return_value="b" * 40 + "\n"):
            with self.assertRaises(ValueError):
                source.require_remote_revision("example/source", "v0.1.0", REVISION)

    def test_release_notes_resolve_source_links_and_preserve_code_and_absolute_targets(self):
        prose = (
            "[Quickstart](../quickstart.md) [Production](../../PRODUCTION.md#prepare-and-install)\n"
            "[Nested](../journeys/operate.md?plain=1#recovery) [Here](#same-page)\n"
            "[Web](https://example.test/guide) `[Inline](../unchanged.md)`\n"
        )
        code = (
            "```markdown\n[Example](../quickstart.md)\n```\n"
            "~~~markdown\n[Other](../../PRODUCTION.md)\n~~~\n"
        )
        result = source.release_notes(prose + code, "0.1.0", "example/source")
        base = "https://github.com/example/source/blob/v0.1.0/"
        self.assertIn(f"[Quickstart]({base}docs/quickstart.md)", result)
        self.assertIn(f"[Production]({base}PRODUCTION.md#prepare-and-install)", result)
        self.assertIn(f"[Nested]({base}docs/journeys/operate.md?plain=1#recovery)", result)
        self.assertIn("[Here](#same-page)", result)
        self.assertIn("[Web](https://example.test/guide)", result)
        self.assertIn("`[Inline](../unchanged.md)`", result)
        self.assertTrue(result.endswith(code))


if __name__ == "__main__":
    unittest.main()

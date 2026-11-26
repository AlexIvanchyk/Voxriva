import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("operator_bundle", ROOT / ".github/scripts/operator_bundle.py")
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class OperatorBundleTests(unittest.TestCase):
    def test_bundle_has_no_build_or_application_source_and_records_revision(self):
        files = bundle.contents(ROOT, "0.1.1", "a" * 40)
        self.assertFalse(any(name.startswith(("backend/", "frontend/", ".git/")) for name in files))
        for name in ("compose.yaml", "compose.mcp.yaml"):
            self.assertNotIn(b"build:", files[name])
            self.assertIn(b"platform: linux/amd64", files[name])
        self.assertIn(b"ghcr.io/alexivanchyk/voxriva:0.1.1", files["distribution.json"])
        self.assertIn(b"a" * 40, files["distribution.json"])
        self.assertIn(b"redis:7.4.7-alpine@sha256:", files["compose.yaml"])

    def test_credentials_and_machine_state_are_excluded(self):
        files = bundle.contents(ROOT, "0.1.1", "a" * 40)
        for path in files:
            self.assertFalse(path.startswith(("output/", "secrets/", ".aws/", ".codex/")))
            self.assertFalse(Path(path).name == ".env")

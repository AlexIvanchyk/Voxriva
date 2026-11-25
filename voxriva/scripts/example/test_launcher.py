"""Safety and retry properties without Docker or product test services."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location(
    "first_email_launcher", Path(__file__).parents[1] / "example.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


class OwnershipTests(unittest.TestCase):
    def test_remote_docker_daemon_is_rejected(self):
        with patch.dict(
            launcher.os.environ,
            {"DOCKER_HOST": "tcp://remote.example.test:2376", "DOCKER_CONTEXT": ""},
        ):
            with self.assertRaisesRegex(launcher.ExampleError, "local Unix-socket"):
                launcher.require_local_docker()

    def test_all_resource_kinds_require_matching_owner(self):
        calls = []

        def docker(*arguments):
            calls.append(arguments)
            if "inspect" in arguments:
                labels = {launcher.OWNER_LABEL: "mine"}
                return json.dumps(
                    [{"Config": {"Labels": labels}}]
                    if arguments[0] == "container"
                    else [{"Labels": labels}]
                )
            return "resource"

        with patch.object(launcher, "docker", side_effect=docker):
            launcher.check_ownership("voxriva-example-test", "mine")
        self.assertEqual(
            [call[0] for call in calls if "inspect" in call],
            ["container", "volume", "network"],
        )

    def test_lost_state_never_adopts_existing_resources(self):
        with patch.object(
            launcher, "docker", side_effect=["container", '[{"Config":{"Labels":{}}}]']
        ):
            with self.assertRaisesRegex(launcher.ExampleError, "Nothing was deleted"):
                launcher.check_ownership("voxriva-example-test", None)

    def test_mismatched_volume_blocks_remove_before_compose(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state = {
                "format": 1,
                "project": "voxriva-example-test",
                "owner": "a" * 32,
                "port": 28080,
                "mailpit_port": 28025,
            }
            (directory / "state.json").write_text(json.dumps(state))

            def docker(*arguments):
                if arguments[:2] == ("context", "inspect"):
                    return "unix:///local/docker.sock"
                if arguments[:2] == ("volume", "ls"):
                    return "some-volume"
                if arguments[:2] == ("volume", "inspect"):
                    return '[{"Labels":{"io.voxriva.example.owner":"someone-else"}}]'
                return ""

            with (
                patch.object(launcher, "docker", side_effect=docker),
                patch.object(launcher, "compose") as compose,
            ):
                with self.assertRaisesRegex(launcher.ExampleError, "volume"):
                    launcher.run(
                        SimpleNamespace(action="remove"), state["project"], directory
                    )
                compose.assert_not_called()
            self.assertTrue((directory / "state.json").exists())

    def test_project_identity_cannot_be_replaced_in_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            path.write_text(
                json.dumps({"format": 1, "project": "voxriva", "owner": "a" * 32})
            )
            with self.assertRaisesRegex(
                launcher.ExampleError, "ownership state is invalid"
            ):
                launcher.load_state(path, "voxriva-example-local")

    def test_saved_url_cannot_redirect_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            path.write_text(
                json.dumps(
                    {
                        "format": 1,
                        "project": "voxriva-example-test",
                        "owner": "a" * 32,
                        "port": 28080,
                        "mailpit_port": 28025,
                        "base_url": "https://outside.example.test",
                    }
                )
            )
            self.assertEqual(
                launcher.load_state(path, "voxriva-example-test")["base_url"],
                "http://127.0.0.1:28080",
            )

    def test_explicit_busy_port_is_not_silently_changed(self):
        with patch.object(launcher, "port_available", return_value=False):
            with self.assertRaisesRegex(launcher.ExampleError, "busy"):
                launcher.choose_port(28080, 18080)

    def test_automatic_ports_avoid_other_selected_port(self):
        with patch.object(launcher, "port_available", return_value=True):
            self.assertEqual(launcher.choose_port(None, 18080, excluded=[18080]), 18081)

    def test_environment_profiles_cannot_enable_collector(self):
        state = {
            "project": "voxriva-example-test",
            "owner": "a" * 32,
            "port": 28080,
            "mailpit_port": 28025,
        }
        with patch.dict(
            launcher.os.environ,
            {"COMPOSE_PROFILES": "monitoring", "COMPOSE_FILE": "production.yaml"},
        ):
            env = launcher.compose_environment(state)
        self.assertNotIn("COMPOSE_PROFILES", env)
        self.assertNotIn("COMPOSE_FILE", env)
        self.assertEqual(env["VOXRIVA_CONTAINER_MONITORING_ENABLED"], "false")


class RetryTests(unittest.TestCase):
    def test_changed_provider_blocks_send_before_acceptance(self):
        state = {
            "base_url": "http://127.0.0.1:28080",
            "delivery_key": "synthetic-test-value",
            "provider_revision_id": "local-mailpit",
        }
        api_class = Mock()
        api_class.return_value.call.return_value = {
            "provider_revision_id": "changed-provider"
        }
        with patch.dict(launcher.send_and_wait.__globals__, {"API": api_class}):
            with self.assertRaisesRegex(
                launcher.ExampleError, "only through its original local Mailpit"
            ):
                launcher.send_and_wait(state, lambda: None)
        self.assertEqual(api_class.return_value.call.call_count, 1)

    def test_repeat_only_reads_original_notification(self):
        state = {
            "base_url": "http://127.0.0.1:28080",
            "delivery_key": "synthetic-test-value",
            "notification_id": "original",
        }
        api_class = Mock()
        api_class.return_value.call.return_value = {"id": "original", "status": "sent"}
        with patch.dict(launcher.send_and_wait.__globals__, {"API": api_class}):
            detail = launcher.send_and_wait(state, lambda: None)
        self.assertEqual(detail["id"], "original")
        self.assertEqual(api_class.return_value.call.call_count, 1)
        self.assertEqual(
            api_class.return_value.call.call_args.args[:2],
            ("GET", "/notifications/original"),
        )

    def test_uncertain_acceptance_retries_exact_key_and_payload(self):
        calls = []

        class Runtime:
            def __init__(self, base):
                pass

            def call(self, method, path, data=None, headers=None):
                if path == "/notifications":
                    calls.append((data, headers["Idempotency-Key"]))
                    if len(calls) == 1:
                        raise OSError("simulated lost response after commit")
                    return {"id": "original"}
                if method == "GET":
                    return {"id": "original", "status": "sent"}
                return {"valid": True, "provider_revision_id": "local-mailpit"}

        state = {
            "base_url": "http://127.0.0.1:28080",
            "delivery_key": "synthetic-test-value",
            "provider_revision_id": "local-mailpit",
        }
        with patch.dict(launcher.send_and_wait.__globals__, {"API": Runtime}):
            with self.assertRaises(OSError):
                launcher.send_and_wait(state, lambda: None)
            launcher.send_and_wait(state, lambda: None)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(state["notification_id"], "original")

    def test_private_state_is_mode_600(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            launcher.private_write(path, "{}")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()

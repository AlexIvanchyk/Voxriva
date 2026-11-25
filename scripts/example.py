#!/usr/bin/env python3
"""Start an isolated, source-built Voxriva and receive one fictional local email.

Requires Python 3.10+, Docker Engine and Docker Compose v2 on macOS/Linux.
No Python packages, cloud credentials or prebuilt Voxriva image are required.
"""

import argparse
import fcntl
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/example"))
from seed import API, ExampleError, prepare, send_and_wait, verify_receipt  # noqa: E402

OWNER_LABEL = "io.voxriva.example.owner"
SERVICES = ["api", "mailpit", "relay", "email-worker", "push-worker"]
BOOTSTRAP = """import asyncio, sys
from backend.app.features.identity.bootstrap import bootstrap
from backend.app.features.identity.schemas import NewAccount
from backend.app.infrastructure.errors import ApplicationError
from backend.app.infrastructure.settings import Settings
try:
    asyncio.run(bootstrap(Settings().database_url, NewAccount.model_validate_json(sys.stdin.read())))
except ApplicationError as error:
    if error.status_code != 409:
        raise
"""


def private_write(path, content):
    descriptor, name = tempfile.mkstemp(prefix=".example-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def port_available(port):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_port(explicit, preferred, excluded=()):
    candidates = (
        [explicit] if explicit is not None else range(preferred, preferred + 100)
    )
    for port in candidates:
        if port not in excluded and port_available(port):
            return port
    raise ExampleError(
        "The requested local port is busy. Choose --port and --mailpit-port, or stop its owner."
    )


def docker(*arguments, env=None):
    result = subprocess.run(
        ["docker", *arguments], cwd=ROOT, env=env, capture_output=True, text=True
    )
    if result.returncode:
        # Do not copy arbitrary daemon/environment output into console logs.
        raise ExampleError(
            "Docker is unavailable or a resource inspection failed. Check Docker Engine and Compose v2."
        )
    return result.stdout.strip()


def require_local_docker():
    endpoint = (
        os.environ["DOCKER_HOST"]
        if os.environ.get("DOCKER_HOST") and not os.environ.get("DOCKER_CONTEXT")
        else docker("context", "inspect", "--format", "{{.Endpoints.docker.Host}}")
    )
    if not endpoint.startswith("unix://"):
        raise ExampleError(
            "Use a local Unix-socket Docker context for this loopback-only example."
        )


def check_ownership(project, owner):
    """Fail closed before up/down if *any* project resource has another owner."""
    for kind, list_arguments in (
        ("container", ["ps", "-aq"]),
        ("volume", ["volume", "ls", "-q"]),
        ("network", ["network", "ls", "-q"]),
    ):
        identifiers = docker(
            *list_arguments, "--filter", f"label=com.docker.compose.project={project}"
        ).split()
        if not identifiers:
            continue
        resources = json.loads(docker(kind, "inspect", *identifiers))
        for resource in resources:
            labels = (
                resource.get("Config", {}).get("Labels")
                if kind == "container"
                else resource.get("Labels")
            )
            if not owner or (labels or {}).get(OWNER_LABEL) != owner:
                raise ExampleError(
                    f"Refusing to change {project}: a {kind} has no matching example ownership label. "
                    "Choose another --name. Nothing was deleted."
                )


def compose_environment(state):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("COMPOSE_")
    }
    env.update(
        {
            "COMPOSE_PROJECT_NAME": state["project"],
            "VOXRIVA_EXAMPLE_OWNER": state["owner"],
            "VOXRIVA_EXAMPLE_IMAGE": state["project"] + ":local",
            "VOXRIVA_PORT": str(state["port"]),
            "VOXRIVA_MAILPIT_PORT": str(state["mailpit_port"]),
            "VOXRIVA_CONTAINER_MONITORING_ENABLED": "false",
            "VOXRIVA_SMTP_ALLOWED_HOSTS": '["mailpit"]',
            "VOXRIVA_MFA_POLICY": "optional",
        }
    )
    return env


def compose(state, directory, *arguments, input_text=None, private=False):
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(ROOT),
        "-p",
        state["project"],
        "-f",
        str(ROOT / "compose.yaml"),
        "-f",
        str(ROOT / "scripts/example/compose.yaml"),
        *arguments,
    ]
    # Bootstrap uses stdin, never command arguments, environment or a saved log.
    if private:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=compose_environment(state),
            input=input_text,
            capture_output=True,
            text=True,
        )
    else:
        with (directory / "compose.log").open("a") as log:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=compose_environment(state),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
            )
    if result.returncode:
        raise ExampleError(
            "Administrator bootstrap failed; credentials remain in protected local state."
            if private
            else f"Compose {' '.join(arguments[:2])} failed. See {directory / 'compose.log'}. "
            "Your state was preserved; fix the Docker/port error and rerun."
        )


def wait_ready(base, timeout=90):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(base + "/health/ready", timeout=3) as response:
                if json.load(response)["status"] == "ready":
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(1)
    raise ExampleError(
        "The example API is not ready. Check its private compose.log, then rerun."
    )


def load_state(path, project):
    if path.is_symlink():
        raise ExampleError("Refusing a symlink for private example state.")
    state = json.loads(path.read_text())
    if (
        state.get("format") != 1
        or state.get("project") != project
        or not re.fullmatch(r"[a-f0-9]{32}", state.get("owner", ""))
    ):
        raise ExampleError(
            "Example ownership state is invalid; no resources were changed."
        )
    # Derive loopback URLs; never trust an edited state URL with credentials.
    for key in ("port", "mailpit_port"):
        if type(state.get(key)) is not int or not 1024 <= state[key] <= 65535:
            raise ExampleError("Invalid local port in private example state.")
    state["base_url"] = f"http://127.0.0.1:{state['port']}"
    state["mailpit_url"] = f"http://127.0.0.1:{state['mailpit_port']}"
    path.chmod(0o600)
    return state


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "action", nargs="?", choices=["up", "stop", "remove"], default="up"
    )
    result.add_argument(
        "--name", default="local", help="isolated example suffix (default: local)"
    )
    result.add_argument(
        "--port", type=int, help="first-run app port (default: first free from 18080)"
    )
    result.add_argument(
        "--mailpit-port",
        type=int,
        help="first-run Mailpit web port (default: first free from 18025)",
    )
    return result


def main():
    options = parser().parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", options.name):
        raise ExampleError("--name must be 1–32 lowercase letters, numbers or hyphens.")
    for value in (options.port, options.mailpit_port):
        if value is not None and not 1024 <= value <= 65535:
            raise ExampleError("Ports must be between 1024 and 65535.")
    if not shutil.which("docker"):
        raise ExampleError(
            "Install and start Docker Engine with Compose v2, then rerun."
        )
    os.umask(0o077)
    project = "voxriva-example-" + options.name
    directory = ROOT / "output/example" / options.name
    # Protect generated files and refuse redirected output destinations.
    for path in (ROOT / "output", ROOT / "output/example", directory):
        if path.is_symlink():
            raise ExampleError("Refusing a symlink in the private example output path.")
        path.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    with (directory / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ExampleError(
                "Another command owns this example. Wait for it to finish."
            ) from None
        run(options, project, directory)


def run(options, project, directory):
    path = directory / "state.json"
    state = load_state(path, project) if path.exists() else None
    require_local_docker()
    docker("version", "--format", "{{.Server.Version}}")
    docker("compose", "version")
    check_ownership(project, state["owner"] if state else None)
    if options.action != "up":
        if not state:
            print("No owned example state exists. Nothing was changed.")
            return
        print(
            f"{'Removing' if options.action == 'remove' else 'Stopping'} only {project}…",
            flush=True,
        )
        compose(
            state,
            directory,
            "down",
            *(["--volumes", "--remove-orphans"] if options.action == "remove" else []),
        )
        if options.action == "remove":
            for name in (
                "state.json",
                "access.txt",
                "verification.json",
                "compose.log",
            ):
                (directory / name).unlink(missing_ok=True)
            print(
                "Owned example containers, network, volumes and generated credentials removed."
            )
        else:
            print(
                "Example stopped. Data and credentials preserved; rerun the first-email command to resume."
            )
        return
    if state:
        for name in ("port", "mailpit_port"):
            requested = getattr(options, name)
            if requested is not None and requested != state[name]:
                raise ExampleError(
                    "Ports are saved for this example. Use another --name for different ports."
                )
    else:
        port = choose_port(options.port, 18080)
        mailpit_port = choose_port(options.mailpit_port, 18025, excluded=[port])
        state = {
            "format": 1,
            "project": project,
            "owner": secrets.token_hex(16),
            "port": port,
            "mailpit_port": mailpit_port,
            "base_url": f"http://127.0.0.1:{port}",
            "mailpit_url": f"http://127.0.0.1:{mailpit_port}",
            "email": "admin@example.test",
            "password": secrets.token_urlsafe(32),
        }

    def save():
        private_write(path, json.dumps(state, indent=2) + "\n")

    save()
    private_write(
        directory / "access.txt",
        f"Local example administrator only\nApp: {state['base_url']}\nEmail: {state['email']}\nPassword: {state['password']}\n\nKeep private. Never use these credentials outside this disposable example.\n",
    )
    print(
        f"Building {project} from local source (first run may take several minutes)…",
        flush=True,
    )
    compose(state, directory, "build", "api")
    print(
        "Starting isolated services; waiting for migrations and worker health…",
        flush=True,
    )
    compose(
        state,
        directory,
        "up",
        "-d",
        "--no-build",
        "--wait",
        "--wait-timeout",
        "240",
        *SERVICES,
    )
    wait_ready(state["base_url"])
    credentials = {key: state[key] for key in ("email", "password")}
    if not state.get("bootstrapped"):
        compose(
            state,
            directory,
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            BOOTSTRAP,
            input_text=json.dumps(credentials),
            private=True,
        )
        # A conflict after an interrupted bootstrap is safe only if login succeeds.
        API(state["base_url"], credentials)
        state["bootstrapped"] = True
        save()
    repeated = "notification_id" in state
    if not state.get("configured"):
        print(
            "Preparing Northstar template, local SMTP binding and scoped Delivery key…",
            flush=True,
        )
        prepare(API(state["base_url"], credentials), state, save)
    print(
        "Checking the first email…"
        if repeated
        else "Sending first email through the runtime API and worker…",
        flush=True,
    )
    detail = send_and_wait(state, save)
    verification = verify_receipt(state, detail)
    state["mailpit_id"] = verification["mailpit_id"]
    save()
    private_write(
        directory / "verification.json", json.dumps(verification, indent=2) + "\n"
    )
    print(
        f"\n{'Existing sample verified; no duplicate sent.' if repeated else 'First email received in Mailpit.'} Status: sent; 2 inline images verified."
    )
    print(f"App:     {state['base_url']}/")
    print(f"Email:   {state['mailpit_url']}/view/{state['mailpit_id']}")
    print(f"API docs: {state['base_url']}/docs")
    print(f"Guide:   {ROOT / 'docs/quickstart.md'}")
    print(f"Login:   protected local file {directory / 'access.txt'}")
    print(
        "Next: sign in, open Northstar → Templates, preview variables, then publish and deploy a change."
    )
    print(f"Stop:    python3 scripts/example.py stop --name {options.name}")
    print(f"Remove:  python3 scripts/example.py remove --name {options.name}")


if __name__ == "__main__":
    try:
        main()
    except (ExampleError, OSError, ValueError) as error:
        print(f"Example: {error}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Owned state was preserved; rerun to resume.",
            file=sys.stderr,
        )
        sys.exit(130)

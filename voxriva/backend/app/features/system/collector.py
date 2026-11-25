import argparse
import http.client
import json
import logging
import re
import socket
import tempfile
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from backend.app.infrastructure.settings import Settings

PROJECT_LABEL = "com.docker.compose.project"
SERVICE_LABEL = "com.docker.compose.service"
ONE_OFF_LABEL = "com.docker.compose.oneoff"
CONTAINER_ID = re.compile("[a-f0-9]{64}")
STATES = {"created", "running", "paused", "restarting", "removing", "exited", "dead"}
HEALTH_STATES = {"healthy", "unhealthy", "starting"}
LOGGER = logging.getLogger("voxriva.collector")


class DockerConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str) -> None:
        super().__init__("localhost", timeout=2)
        self.socket_path = socket_path

    def connect(self) -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(self.timeout)
            connection.connect(self.socket_path)
            self.sock = connection.dup()


class DockerEngine:
    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path

    def get(self, path: str) -> Any:
        connection = DockerConnection(self.socket_path)
        try:
            connection.request("GET", f"/v1.44{path}")
            response = connection.getresponse()
            if (
                response.status == 404
                and path.endswith("/json")
                and (path != "/containers/json")
            ):
                return None
            if response.status != 200:
                raise RuntimeError(f"Docker returned HTTP {response.status}")
            return json.load(response)
        finally:
            connection.close()


def is_project_service(labels: dict[str, str], project: str, service: str) -> bool:
    return (
        labels.get(PROJECT_LABEL) == project
        and labels.get(SERVICE_LABEL) == service
        and (labels.get(ONE_OFF_LABEL, "false").lower() != "true")
    )


def collect(
    get: Callable[[str], Any],
    project: str,
    services: Sequence[str],
    jobs: frozenset[str],
) -> dict[str, Any]:
    filters = json.dumps({"label": [f"{PROJECT_LABEL}={project}"]})
    query = urlencode({"all": "true", "filters": filters})
    candidates = get(f"/containers/json?{query}")
    observed_at = datetime.now(UTC).isoformat()
    containers: list[dict[str, Any]] = []
    by_service: dict[str, list[dict[str, Any]]] = {service: [] for service in services}
    for candidate in candidates:
        labels = candidate.get("Labels") or {}
        service = labels.get(SERVICE_LABEL)
        identifier = candidate["Id"]
        if (
            service not in by_service
            or not is_project_service(labels, project, service)
            or (not CONTAINER_ID.fullmatch(identifier))
        ):
            continue
        details = get(f"/containers/{identifier}/json")
        if details is None:
            continue
        config = details.get("Config") or {}
        if not is_project_service(config.get("Labels") or {}, project, service):
            continue
        state = details["State"]
        lifecycle = state["Status"]
        if service in jobs and lifecycle == "exited" and (state.get("ExitCode") == 0):
            lifecycle = "completed"
        elif lifecycle not in STATES:
            lifecycle = "unknown"
        health = (state.get("Health") or {}).get("Status")
        health_command = (config.get("Healthcheck") or {}).get("Test")
        if health not in HEALTH_STATES:
            health = (
                "unknown"
                if health_command and health_command != ["NONE"]
                else "not_configured"
            )
        by_service[service].append(
            {
                "service": service,
                "name": details["Name"].lstrip("/"),
                "state": lifecycle,
                "health": health,
                "restart_count": details["RestartCount"],
                "observed_at": observed_at,
            }
        )
    for service, observed in by_service.items():
        containers.extend(
            sorted(observed, key=lambda row: row["name"])
            or [
                {
                    "service": service,
                    "name": None,
                    "state": "missing",
                    "health": "unknown",
                    "restart_count": None,
                    "observed_at": observed_at,
                }
            ]
        )
    return {"observed_at": observed_at, "containers": containers}


def publish(path: Path, snapshot: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(snapshot, stream)
            stream.flush()
            temporary.chmod(420)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def refresh(
    get: Callable[[str], Any],
    project: str,
    services: Sequence[str],
    jobs: frozenset[str],
    output: Path,
) -> None:
    try:
        publish(output, collect(get, project, services, jobs))
    except (
        OSError,
        RuntimeError,
        ValueError,
        TypeError,
        KeyError,
        http.client.HTTPException,
    ) as error:
        LOGGER.warning("Could not refresh Docker status: %s", type(error).__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if not Settings().container_monitoring_enabled:
        LOGGER.info("Container monitoring is disabled; collector stopped")
        return
    parser = argparse.ArgumentParser(
        description="Publish read-only Voxriva Compose status"
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--socket", default="/var/run/docker.sock")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=3)
    parser.add_argument("--job", action="append", default=[])
    parser.add_argument("services", nargs="+")
    options = parser.parse_args()
    if options.interval <= 0:
        parser.error("--interval must be positive")
    engine = DockerEngine(options.socket)
    while True:
        refresh(
            engine.get,
            options.project,
            options.services,
            frozenset(options.job),
            options.output,
        )
        time.sleep(options.interval)


if __name__ == "__main__":
    main()

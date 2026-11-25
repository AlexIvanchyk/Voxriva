import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from backend.app.features.system.collector import (
    ONE_OFF_LABEL,
    PROJECT_LABEL,
    SERVICE_LABEL,
    DockerConnection,
    DockerEngine,
    collect,
    main,
    publish,
    refresh,
)


def labels(service, project="voxriva", **extra):
    return {PROJECT_LABEL: project, SERVICE_LABEL: service, **extra}


def container(service, state="running", health=None, healthcheck=None, exit_code=0):
    return {
        "Config": {"Labels": labels(service), "Healthcheck": {"Test": healthcheck}},
        "State": {"Status": state, "ExitCode": exit_code, "Health": {"Status": health}},
        "Name": f"/voxriva-{service}-1",
        "RestartCount": 2,
    }


class Engine:
    def __init__(self, *rows):
        self.rows = rows
        self.inspected = []

    def get(self, path):
        if path.startswith("/containers/json?"):
            query = parse_qs(urlparse(path).query)
            assert query["all"] == ["true"]
            assert json.loads(query["filters"][0]) == {
                "label": [f"{PROJECT_LABEL}=voxriva"]
            }
            return [
                {"Id": f"{index:064x}", "Labels": row[0]}
                for index, row in enumerate(self.rows)
            ]
        index = int(path.split("/")[2], 16)
        self.inspected.append(index)
        return self.rows[index][1]


def collect_services(engine, *services):
    return collect(engine.get, "voxriva", services, frozenset({"migrate"}))


def test_only_configured_project_services_are_inspected_and_reported():
    misplaced = container("api")
    misplaced["Config"]["Labels"] = labels("api", "other")
    engine = Engine(
        (labels("redis", "other"), container("redis")),
        (labels("extra"), container("extra")),
        (labels("redis", **{ONE_OFF_LABEL: "True"}), container("redis")),
        (labels("api"), misplaced),
        (labels("redis"), container("redis", health="healthy")),
    )

    report = collect_services(engine, "api", "redis")
    api, redis = report["containers"]
    assert engine.inspected == [3, 4]
    assert api["state"] == "missing"
    assert api["restart_count"] is None
    assert redis["name"] == "voxriva-redis-1"
    assert redis["restart_count"] == 2
    assert redis["health"] == "healthy"
    assert redis["observed_at"] == report["observed_at"]


@pytest.mark.parametrize(
    ("service", "details", "state", "health"),
    [
        ("migrate", container("migrate", "exited"), "completed", "not_configured"),
        (
            "migrate",
            container("migrate", "exited", exit_code=1),
            "exited",
            "not_configured",
        ),
        (
            "redis",
            container("redis", "exited", healthcheck=["CMD", "redis-cli"]),
            "exited",
            "unknown",
        ),
        ("redis", container("redis", health="unhealthy"), "running", "unhealthy"),
        ("redis", container("redis", health="starting"), "running", "starting"),
        (
            "redis",
            container("redis", healthcheck=["NONE"]),
            "running",
            "not_configured",
        ),
        ("redis", container("redis", "future"), "unknown", "not_configured"),
        ("redis", None, "missing", "unknown"),
    ],
)
def test_lifecycle_and_health_are_independent(service, details, state, health):
    report = collect_services(Engine((labels(service), details)), service)
    assert report["containers"][0]["state"] == state
    assert report["containers"][0]["health"] == health


def test_replicas_are_reported_in_stable_order():
    second = container("api")
    second["Name"] = "/voxriva-api-2"
    first = container("api")
    report = collect_services(
        Engine((labels("api"), second), (labels("api"), first)), "api"
    )
    assert [row["name"] for row in report["containers"]] == [
        "voxriva-api-1",
        "voxriva-api-2",
    ]


def test_publish_replaces_previous_snapshot_and_leaves_no_temp_files(tmp_path: Path):
    path = tmp_path / "containers.json"
    publish(path, {"containers": []})
    report = collect_services(Engine(), "api")
    publish(path, report)

    assert json.loads(path.read_text()) == report
    assert list(tmp_path.iterdir()) == [path]
    assert path.stat().st_mode & 0o777 == 0o644


def test_refresh_keeps_last_good_snapshot_on_engine_outage(tmp_path, caplog):
    path = tmp_path / "containers.json"
    refresh(
        Engine((labels("redis"), container("redis"))).get,
        "voxriva",
        ["redis"],
        frozenset(),
        path,
    )
    before = path.read_bytes()

    def unavailable(_):
        raise OSError("internal socket path")

    refresh(unavailable, "voxriva", ["redis"], frozenset(), path)
    assert path.read_bytes() == before
    assert "Could not refresh Docker status" in caplog.text
    assert "internal socket path" not in caplog.text


@pytest.mark.parametrize(
    ("status", "expected"), [(200, {"ok": True}), (404, None), (500, RuntimeError)]
)
def test_docker_transport_is_read_only_and_closes_connections(status, expected):
    from io import BytesIO
    from unittest.mock import patch

    with patch(
        "backend.app.features.system.collector.DockerConnection", autospec=True
    ) as constructor:
        connection = constructor.return_value
        response = BytesIO(b'{"ok":true}')
        response.status = status
        connection.getresponse.return_value = response
        engine = DockerEngine("/run/docker.sock")
        route = "/containers/demo/json"
        if status == 500:
            with pytest.raises(expected):
                engine.get(route)
        else:
            assert engine.get(route) == expected
        connection.request.assert_called_once_with("GET", f"/v1.44{route}")
        connection.close.assert_called_once()


def test_docker_connection_opens_a_unix_socket_only():
    from socket import AF_UNIX, SOCK_STREAM
    from unittest.mock import patch

    with patch("backend.app.features.system.collector.socket.socket") as factory:
        raw = factory.return_value.__enter__.return_value
        connection = DockerConnection("/run/docker.sock")
        connection.connect()

        factory.assert_called_once_with(AF_UNIX, SOCK_STREAM)
        raw.settimeout.assert_called_once_with(2)
        raw.connect.assert_called_once_with("/run/docker.sock")
        assert connection.sock is raw.dup.return_value


def test_collector_process_refreshes_at_the_configured_interval(tmp_path):
    from unittest.mock import patch

    class EndTest(Exception):
        pass

    output = tmp_path / "snapshot.json"
    command = [
        "collector",
        "--project",
        "voxriva",
        "--output",
        str(output),
        "--interval",
        "2",
        "--job",
        "migrate",
        "migrate",
    ]
    engine = Engine((labels("migrate"), container("migrate", "exited")))
    with (
        patch("sys.argv", command),
        patch(
            "backend.app.features.system.collector.DockerEngine.get",
            side_effect=engine.get,
        ),
        patch(
            "backend.app.features.system.collector.time.sleep", side_effect=EndTest
        ) as sleep,
        pytest.raises(EndTest),
    ):
        main()
    sleep.assert_called_once_with(2)
    assert json.loads(output.read_text())["containers"][0]["state"] == "completed"


def test_collector_rejects_a_nonpositive_interval(tmp_path):
    from unittest.mock import patch

    command = [
        "collector",
        "--project",
        "voxriva",
        "--output",
        str(tmp_path),
        "--interval",
        "0",
        "api",
    ]
    with patch("sys.argv", command), pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 2


def test_disabled_collector_exits_before_configuration_or_docker_access(
    monkeypatch, caplog
):
    from unittest.mock import patch

    monkeypatch.setenv("VOXRIVA_CONTAINER_MONITORING_ENABLED", "false")
    with (
        patch("sys.argv", ["collector"]),
        patch("backend.app.features.system.collector.DockerEngine") as engine,
        patch("backend.app.features.system.collector.refresh") as refresh_snapshot,
        patch("backend.app.features.system.collector.time.sleep") as sleep,
        caplog.at_level("INFO"),
    ):
        main()
    engine.assert_not_called()
    refresh_snapshot.assert_not_called()
    sleep.assert_not_called()
    assert "Container monitoring is disabled" in caplog.text

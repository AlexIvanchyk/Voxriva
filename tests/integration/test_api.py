import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from backend.app.features.identity.dependencies import platform_admin
from backend.app.features.system.monitoring import read_monitoring
from backend.app.infrastructure.resources import Dependencies
from backend.app.infrastructure.settings import Settings
from backend.app.main import create_app


def probes():
    database = MagicMock()
    database.connect.return_value.__aenter__.return_value.execute = AsyncMock()
    database.dispose = AsyncMock()
    redis = AsyncMock()
    redis.ping.return_value = True
    return Dependencies(database=database, redis=redis)


def test_liveness_and_version_are_available_without_dependencies():
    with TestClient(create_app(Settings(version="future"))) as client:
        assert client.get("/health/live").json() == {"status": "live"}
        info = client.get("/api/v1/system/info")
        assert info.headers["cache-control"] == "no-store"
        assert info.json() == {"name": "Voxriva", "version": "future"}
        assert client.get("/openapi.json").json()["info"]["version"] == "future"
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"] == {
            "api": "ready",
            "postgres": "unconfigured",
            "redis": "unconfigured",
        }


def test_readiness_and_metrics_recover_after_redis_outage():
    resources = probes()
    app = create_app(dependencies=resources)
    app.dependency_overrides[platform_admin] = lambda: None
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        resources.redis.ping.side_effect = RedisConnectionError(
            "secret connection information"
        )
        failure = client.get("/health/ready")
        assert failure.status_code == 503
        assert failure.json() == {
            "status": "unavailable",
            "checks": {"api": "ready", "postgres": "ready", "redis": "unavailable"},
        }
        assert client.get("/health/live").status_code == 200
        assert (
            'voxriva_dependency_ready{dependency="redis"} 0'
            in client.get("/metrics").text
        )
        status = client.get("/api/v1/system/status")
        assert status.status_code == 200
        assert status.json()["readiness"] == failure.json()
        assert "secret" not in status.text
        resources.redis.ping.side_effect = None
        assert client.get("/health/ready").status_code == 200
    resources.redis.aclose.assert_awaited_once()
    resources.database.dispose.assert_awaited_once()


@pytest.mark.parametrize("failure", ["timeout", "os_error", "false_ping"])
def test_failed_dependency_probes_are_bounded_and_reported(failure):
    resources = probes()
    resources.timeout = 0.02
    if failure == "timeout":

        async def slow():
            await asyncio.sleep(1)

        resources.database.connect.return_value.__aenter__.side_effect = slow
    elif failure == "os_error":
        resources.database.connect.return_value.__aenter__.side_effect = OSError
    else:
        resources.redis.ping.return_value = False
    with TestClient(create_app(dependencies=resources)) as client:
        result = client.get("/health/ready").json()
    dependency = "redis" if failure == "false_ping" else "postgres"
    assert result["checks"][dependency] == "unavailable"


def snapshot(path, observed_at):
    timestamp = observed_at.isoformat()
    report = {
        "observed_at": timestamp,
        "containers": [
            {
                "service": "redis",
                "name": "voxriva-redis-1",
                "state": "running",
                "health": "healthy",
                "restart_count": 0,
                "observed_at": timestamp,
            }
        ],
    }
    path.write_text(json.dumps(report))


def test_monitoring_snapshot_is_independent_of_readiness(tmp_path):
    path = tmp_path / "containers.json"
    app = create_app(Settings(snapshot_path=path))
    app.dependency_overrides[platform_admin] = lambda: None
    with TestClient(app) as client:
        assert client.get("/api/v1/system/status").json()["monitoring"] == {
            "status": "unavailable",
            "snapshot": None,
        }
        snapshot(path, datetime.now(UTC))
        result = client.get("/api/v1/system/status").json()
        assert result["monitoring"]["status"] == "current"
        assert result["monitoring"]["snapshot"]["containers"][0]["state"] == "running"
        assert result["snapshot_max_age_seconds"] == 12
        assert result["readiness"]["status"] == "unavailable"
        snapshot(path, datetime.now(UTC) - timedelta(seconds=30))
        stale = client.get("/api/v1/system/status").json()["monitoring"]
        assert stale["status"] == "stale"
        assert stale["snapshot"]["containers"][0]["state"] == "running"


@pytest.mark.parametrize("age", [-1, 12, 13])
def test_future_or_expired_snapshots_are_stale(tmp_path, age):
    now = datetime.now(UTC)
    path = tmp_path / "containers.json"
    snapshot(path, now - timedelta(seconds=age))
    assert read_monitoring(Settings(snapshot_path=path), now).status == "stale"


@pytest.mark.parametrize(
    "content", ["{", '{"observed_at":"2026-01-01T00:00:00","containers":[]}']
)
def test_invalid_snapshot_is_unavailable(tmp_path, content):
    path = tmp_path / "containers.json"
    path.write_text(content)
    assert read_monitoring(Settings(snapshot_path=path)).status == "unavailable"


def test_static_dashboard_preserves_api_routes_and_cache_rules(tmp_path):
    (tmp_path / "index.html").write_text("<title>Voxriva Dashboard</title>")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-fixture.js").write_text("void 0")
    with TestClient(create_app(Settings(static_dir=tmp_path))) as client:
        for route in [
            "/",
            "/system/health",
            "/sign-in",
            "/api-keys",
            "/projects",
            "/projects/fixture",
            "/templates",
            "/templates/fixture",
            "/members",
            "/environments",
            "/deployments",
            "/providers",
            "/notifications",
            "/notifications/fixture",
        ]:
            response = client.get(route)
            assert "Voxriva Dashboard" in response.text
            assert response.headers["cache-control"] == "no-cache"
        assert (
            "immutable"
            in client.get("/assets/index-fixture.js").headers["cache-control"]
        )
        assert client.get("/assets/does-not-exist.js").status_code == 404
        for route in [
            "/api/missing",
            "/health/missing",
            "/metrics/missing",
            "/missing",
        ]:
            assert client.get(route).status_code == 404
        assert client.get("/metrics").headers["content-type"].startswith("text/plain")
        assert (
            client.get("/health/live")
            .headers["content-type"]
            .startswith("application/json")
        )


def test_unbuilt_dashboard_does_not_prevent_api_startup(tmp_path):
    with TestClient(create_app(Settings(static_dir=tmp_path))) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/v1/system/info").status_code == 200


@pytest.mark.parametrize("enabled", ["true", "false"])
def test_container_monitoring_environment_toggle(monkeypatch, enabled):
    monkeypatch.setenv("VOXRIVA_CONTAINER_MONITORING_ENABLED", enabled)
    assert Settings().container_monitoring_enabled is (enabled == "true")


def test_container_monitoring_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("VOXRIVA_CONTAINER_MONITORING_ENABLED", raising=False)
    assert Settings().container_monitoring_enabled is True


def test_disabled_monitoring_never_reads_snapshots_and_keeps_readiness_active(tmp_path):
    path = tmp_path / "containers.json"
    snapshot(path, datetime.now(UTC))
    resources = probes()
    app = create_app(
        Settings(container_monitoring_enabled=False, snapshot_path=path), resources
    )
    app.dependency_overrides[platform_admin] = lambda: None
    with TestClient(app) as client, patch.object(type(path), "read_bytes") as read:
        for redis_available in (True, False):
            resources.redis.ping.return_value = redis_available
            result = client.get("/api/v1/system/status")
            assert result.status_code == 200
            assert result.json()["monitoring"] == {
                "status": "disabled",
                "snapshot": None,
            }
            assert result.json()["readiness"]["checks"] == {
                "api": "ready",
                "postgres": "ready",
                "redis": "ready" if redis_available else "unavailable",
            }
            assert client.get("/health/ready").status_code == (
                200 if redis_available else 503
            )
            assert client.get("/health/live").status_code == 200
        read.assert_not_called()
    assert (
        read_monitoring(Settings(container_monitoring_enabled=False)).status
        == "disabled"
    )

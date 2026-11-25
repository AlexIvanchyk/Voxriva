from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from backend.app.infrastructure.settings import Settings


class ContainerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str
    name: str | None
    state: Literal[
        "created",
        "running",
        "paused",
        "restarting",
        "removing",
        "exited",
        "dead",
        "completed",
        "missing",
        "unknown",
    ]
    health: Literal["healthy", "unhealthy", "starting", "not_configured", "unknown"]
    restart_count: int | None = Field(ge=0)
    observed_at: AwareDatetime


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_at: AwareDatetime
    containers: list[ContainerStatus]


class MonitoringStatus(BaseModel):
    status: Literal["current", "stale", "unavailable", "disabled"]
    snapshot: Snapshot | None = None


def read_monitoring(
    settings: Settings, now: datetime | None = None
) -> MonitoringStatus:
    if not settings.container_monitoring_enabled:
        return MonitoringStatus(status="disabled")
    if settings.snapshot_path is None:
        return MonitoringStatus(status="unavailable")
    try:
        snapshot = Snapshot.model_validate_json(settings.snapshot_path.read_bytes())
    except (OSError, ValidationError):
        return MonitoringStatus(status="unavailable")
    age = ((now or datetime.now(UTC)) - snapshot.observed_at).total_seconds()
    status: Literal["current", "stale"] = (
        "current" if 0 <= age < settings.snapshot_max_age else "stale"
    )
    return MonitoringStatus(status=status, snapshot=snapshot)

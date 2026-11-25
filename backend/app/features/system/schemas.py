from pydantic import BaseModel, PositiveFloat

from backend.app.features.system.monitoring import MonitoringStatus
from backend.app.infrastructure.resources import Readiness


class SystemInfo(BaseModel):
    name: str = "Voxriva"
    version: str


class Liveness(BaseModel):
    status: str = "live"


class SystemStatus(BaseModel):
    info: SystemInfo
    readiness: Readiness
    monitoring: MonitoringStatus
    snapshot_max_age_seconds: PositiveFloat

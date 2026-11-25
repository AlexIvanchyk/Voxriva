from datetime import datetime
from uuid import UUID

from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.templates.versions_schemas import VersionSummary


class InventoryRow(ScopeInput):
    template_id: UUID
    template_name: str
    template_key: str
    channel: str
    project_name: str | None
    environment_name: str | None
    version: VersionSummary | None
    effective_version: VersionSummary | None
    effective_scope: str | None
    fallback_used: bool
    updated_at: datetime | None

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from backend.app.features.templates.locales import Locale
from backend.app.features.templates.versions_schemas import VersionSummary


class FallbackInput(BaseModel):
    locale: Locale
    expected_locale: Locale
    acknowledge_active_change: bool = False


class ScopeInput(BaseModel):
    scope: Literal["global", "project", "environment"]
    project_id: UUID | None = None
    environment_id: UUID | None = None
    locale: Locale = "en"

    @model_validator(mode="after")
    def scoped(self) -> "ScopeInput":
        if self.scope == "global" and (self.project_id or self.environment_id):
            raise ValueError("Global defaults have no project or environment")
        if self.scope == "project" and (not self.project_id or self.environment_id):
            raise ValueError("Project defaults require a project and no environment")
        if self.scope == "environment" and (
            not self.project_id or not self.environment_id
        ):
            raise ValueError(
                "Environment deployments require a project and environment"
            )
        return self

    @property
    def key(self) -> str:
        return (
            "global"
            if self.scope == "global"
            else f"{self.scope}:{(self.environment_id if self.scope == 'environment' else self.project_id)}"
        )


class ChangeInput(ScopeInput):
    expected_generation: int = Field(ge=0)
    allow_breaking: bool = False
    expected_effective_version_id: UUID | None = None


class DeployInput(ChangeInput):
    version_id: UUID


class PromoteInput(BaseModel):
    source: ScopeInput
    target: ChangeInput
    expected_source_generation: int = Field(ge=1)


class HistoryView(BaseModel):
    id: UUID
    action: str
    generation: int
    before: VersionSummary | None
    after: VersionSummary | None
    author: str
    created_at: datetime


class DeploymentRow(ScopeInput):
    label: str
    project_name: str | None = None
    environment_name: str | None = None
    generation: int
    version: VersionSummary | None
    effective_version: VersionSummary | None
    effective_scope: str | None
    fallback_used: bool
    editable: bool
    inherited_version: VersionSummary | None
    history: list[HistoryView]


class DeploymentMatrix(BaseModel):
    locale: str
    fallback_locale: str
    rows: list[DeploymentRow]


class Resolution(BaseModel):
    requested_locale: str
    resolved_locale: str
    fallback_used: bool
    scope: str
    version: VersionSummary

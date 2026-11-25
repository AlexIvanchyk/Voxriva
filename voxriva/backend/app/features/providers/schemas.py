from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.app.features.deployments.schemas import ScopeInput
from backend.app.features.identity.schemas import Email
from backend.app.features.projects.schemas import NamedInput
from backend.app.shared.provider_contract import PushToken


class ConfigurationInput(NamedInput):
    model_config = ConfigDict(extra="forbid")
    provider_type: str
    project_id: UUID | None = None
    config: dict[str, Any]


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    config: dict[str, Any]
    clear_secrets: list[str] = Field(default_factory=list)


class RevisionView(BaseModel):
    id: UUID
    number: int
    config: dict[str, Any]
    configured_secrets: list[str]
    created_at: datetime


class ConfigurationView(BaseModel):
    id: UUID
    name: str
    provider_type: str
    channel: str
    project_id: UUID | None
    project_name: str | None
    editable: bool
    latest: RevisionView


class BindingInput(ScopeInput):
    channel: Literal["email", "push"]
    revision_id: UUID
    expected_generation: int = Field(ge=0)


class BindingVersion(BaseModel):
    configuration_id: UUID
    configuration_name: str
    revision_id: UUID
    revision: int
    provider_type: str


class BindingView(ScopeInput):
    channel: str
    label: str
    generation: int
    direct: BindingVersion | None
    effective: BindingVersion | None
    effective_scope: str | None
    editable: bool


class TestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision_id: UUID


class SendTestInput(TestInput):
    recipient: Email
    subject: Annotated[
        str, StringConstraints(min_length=1, max_length=200, pattern="^[^\\r\\n]+$")
    ] = "Voxriva SMTP test"
    text: Annotated[str, StringConstraints(min_length=1, max_length=10000)] = (
        "This is an explicit test email from Voxriva."
    )


class SendPushTestInput(TestInput):
    device_token: PushToken
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)] = (
        "Voxriva push test"
    )
    body: Annotated[str, StringConstraints(min_length=1, max_length=2000)] = (
        "This is an explicit test push from Voxriva."
    )
    data: dict[str, str] = Field(default_factory=dict)
    validate_only: bool = True

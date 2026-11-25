import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from backend.app.features.identity.schemas import Email
from backend.app.features.providers.models import ProviderRevision
from backend.app.features.templates.locales import Locale
from backend.app.features.templates.models import Template, TemplateVersion
from backend.app.shared.provider_contract import PushToken

State = Literal[
    "queued",
    "retrying",
    "processing",
    "sent",
    "delivered",
    "bounced",
    "failed",
    "unknown",
]


class NotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_key: Annotated[str, StringConstraints(pattern="^[a-z][a-z0-9_-]{0,99}$")]
    recipient: Email | None = None
    device_token: PushToken | None = None
    locale: Locale = "en"
    context: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Runtime values. Image v1 fields accept {media_type: image/png|image/jpeg|image/webp, content_base64: canonical padded base64}. Maximum 256 KiB per decoded image, 1 MiB combined, 4096 px per side and 4 million pixels. Payload values replace top-level runtime defaults; fixtures never supply runtime values.",
    )

    @model_validator(mode="after")
    def bounded(self) -> "NotificationInput":
        if (self.recipient is None) == (self.device_token is None):
            raise ValueError("Supply exactly one email recipient or device token")
        from backend.app.features.templates.images import (
            bounded_images,
            without_image_bytes,
        )

        bounded_images(self.context)
        if (
            len(
                json.dumps(
                    without_image_bytes(self.context),
                    allow_nan=False,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            > 100000
        ):
            raise ValueError("Runtime context exceeds 100 KB")
        return self


class Accepted(BaseModel):
    id: UUID
    status: State
    environment_id: UUID
    template_version_id: UUID
    provider_revision_id: UUID
    replayed: bool
    status_url: str


class ResolutionView(BaseModel):
    project_name: str
    environment_name: str
    template_name: str
    template_key: str
    branch_name: str
    template_version: int
    resolved_locale: str
    fallback_used: bool
    provider_name: str
    provider_type: str
    provider_revision: int
    provider_scope: str | None


class ProviderEventView(BaseModel):
    id: UUID
    event: Literal["delivered", "bounced"]
    occurred_at: datetime
    received_at: datetime


class NotificationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    environment_id: UUID
    template_version_id: UUID
    provider_revision_id: UUID
    channel: Literal["email", "push"]
    locale: str
    recipient_mask: str
    recipient_email: str | None = None
    status: State
    resolution: ResolutionView
    error_code: str | None
    error_message: str | None = None
    attempt_count: int
    next_attempt_at: datetime | None
    expires_at: datetime | None
    replay_of_id: UUID | None
    payload_available: bool = False
    created_at: datetime
    updated_at: datetime


class AttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    number: int
    status: str
    error_code: str | None
    error_message: str | None = None
    retryable: bool
    provider_message_id: str | None
    started_at: datetime
    finished_at: datetime | None


class NotificationDetail(NotificationView):
    replay_allowed: bool = False
    attempts: list[AttemptView]
    provider_events: list[ProviderEventView] = Field(default_factory=list)


class NotificationList(BaseModel):
    items: list[NotificationView]
    total: int
    limit: int
    offset: int


@dataclass
class Prepared:
    template: Template
    version: TemplateVersion
    provider_revision: ProviderRevision
    resolution: dict[str, Any]


class ValidationResult(BaseModel):
    valid: Literal[True] = True
    project_id: UUID
    environment_id: UUID
    channel: Literal["email", "push"]
    locale: str
    resolved_locale: str
    fallback_used: bool
    template_version_id: UUID
    provider_revision_id: UUID


class InputIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class RuntimeIssue(BaseModel):
    path: list[str | int]
    code: str
    message: str


class RuntimeProblem(BaseModel):
    message: str
    issues: list[RuntimeIssue]


class ApiProblem(BaseModel):
    detail: str | RuntimeProblem | list[InputIssue]


class ReplayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replay_key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=128, pattern="^[A-Za-z0-9._:-]+$"),
    ]
    expected_updated_at: datetime
    use_current_deployments: bool = False
    recipient: Email | None = None
    device_token: PushToken | None = None
    context: dict[str, JsonValue] | None = None

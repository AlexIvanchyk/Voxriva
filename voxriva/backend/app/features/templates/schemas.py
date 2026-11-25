import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    model_validator,
)

from backend.app.features.projects.schemas import NamedInput, NamedResource
from backend.app.features.templates.locales import Locale
from backend.app.features.templates.rendering import DraftContent


class ProjectBindings(BaseModel):
    project_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_projects(self) -> "ProjectBindings":
        if len(self.project_ids) != len(set(self.project_ids)):
            raise ValueError("Select each project once")
        return self


class TemplateInput(NamedInput, ProjectBindings):
    model_config = ConfigDict(extra="forbid")
    key: Annotated[str, StringConstraints(pattern="^[a-z][a-z0-9_-]{0,99}$")]
    channel: Literal["email", "push"]
    draft: DraftContent = Field(default_factory=DraftContent)
    locale: Locale = "en"


class TemplateView(NamedInput):
    id: UUID
    key: str
    channel: str
    draft: DraftContent
    draft_revision: int
    updated_at: datetime
    branch_id: UUID
    branch_name: str
    locale: str
    fallback_locale: str
    primary_locale: str
    languages: list[str]
    has_published_versions: bool
    projects: list[NamedResource]
    project_count: int
    editable: bool
    manage_bindings: bool


class DraftUpdate(BaseModel):
    draft: DraftContent
    expected_revision: int = Field(ge=1)
    branch_id: UUID | None = None


class PreviewInput(BaseModel):
    generate_example: bool = False
    draft: DraftContent | None = None
    context: dict[str, JsonValue] | None = None
    scenario: str | None = Field(default=None, max_length=80)
    branch_id: UUID | None = None

    @model_validator(mode="after")
    def bounded_context(self) -> "PreviewInput":
        from backend.app.features.templates.images import (
            bounded_images,
            without_image_bytes,
        )

        bounded_images(self.context)
        if (
            self.context is not None
            and len(
                json.dumps(
                    without_image_bytes(self.context),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            )
            > 100000
        ):
            raise ValueError("Preview context exceeds 100 KB")
        return self


class RenameInput(BaseModel):
    draft: DraftContent
    old_name: Annotated[
        str,
        StringConstraints(
            min_length=1, max_length=100, pattern="^[A-Za-z][A-Za-z0-9_]*$"
        ),
    ]
    new_name: Annotated[
        str,
        StringConstraints(
            min_length=1, max_length=100, pattern="^[A-Za-z][A-Za-z0-9_]*$"
        ),
    ]

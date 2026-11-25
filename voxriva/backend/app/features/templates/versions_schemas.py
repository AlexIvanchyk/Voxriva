from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

from backend.app.features.templates.locales import Locale
from backend.app.features.templates.rendering import DraftContent


class VersionSummary(BaseModel):
    id: UUID
    branch_id: UUID
    branch_name: str
    number: int
    locale: str
    parent_version_id: UUID | None
    draft_revision: int
    message: str
    author: str
    created_at: datetime


class VersionView(VersionSummary):
    content: DraftContent


class BranchView(BaseModel):
    id: UUID
    name: str
    locale: str
    draft_revision: int
    source_version_id: UUID | None
    head: VersionSummary | None


class BranchInput(BaseModel):
    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=64,
            pattern="^[a-z][a-z0-9/_-]*$",
        ),
    ]
    source_version_id: UUID
    locale: Locale | None = None


class PublishInput(BaseModel):
    branch_id: UUID
    expected_revision: int = Field(ge=1)
    message: str = Field(default="", max_length=500)


class LanguageInput(BaseModel):
    locale: Locale
    source_branch_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def snapshot(self) -> "LanguageInput":
        if (self.source_branch_id is None) != (self.expected_revision is None):
            raise ValueError("A copied language requires its saved source revision")
        return self


class PrimaryLanguageInput(BaseModel):
    locale: Locale
    expected_locale: Locale

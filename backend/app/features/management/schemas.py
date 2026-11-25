from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.features.templates.rendering import DraftContent


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    project_ids: list[UUID] = Field(min_length=1, max_length=100)
    scopes: list[Literal["templates:read", "templates:write"]] = Field(
        default=["templates:read"]
    )
    expires_in_days: int = Field(default=30, ge=1, le=90)

    @model_validator(mode="after")
    def unique_scopes(self) -> "CredentialInput":
        if "templates:read" not in self.scopes:
            raise ValueError("templates:read is required")
        if len(set(self.project_ids)) != len(self.project_ids) or len(
            set(self.scopes)
        ) != len(self.scopes):
            raise ValueError("Duplicate project or scope")
        return self


class CredentialView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    project_ids: list[UUID]
    scopes: list[str]
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime


class IssuedCredential(BaseModel):
    credential: CredentialView
    token: str


class DraftChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: UUID
    branch_id: UUID
    expected_revision: int = Field(ge=1)
    draft: DraftContent


class ChangeSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[DraftChange] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_branches(self) -> "ChangeSet":
        keys = [(item.template_id, item.branch_id) for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Each branch may occur once")
        if len(self.model_dump_json().encode()) > 6_000_000:
            raise ValueError("Change set exceeds 6 MB")
        return self

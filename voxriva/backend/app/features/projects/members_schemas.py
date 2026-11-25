from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.app.features.identity.schemas import Email, Password
from backend.app.features.projects.schemas import Role


class ProjectGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID
    role: Role


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=100)
    ] = ""
    password: Password | None = None
    projects: list[ProjectGrant] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_projects(self) -> "MemberCreate":
        if len({grant.project_id for grant in self.projects}) != len(self.projects):
            raise ValueError("Select each project only once")
        return self


class GrantView(ProjectGrant):
    project_name: str
    editable: bool
    created_at: datetime


class DirectoryMember(BaseModel):
    account_id: UUID
    email: str
    display_name: str
    inherited: bool
    can_edit_name: bool = False
    created_at: datetime
    projects: list[GrantView]


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] | None
    ) = None
    expected_display_name: str
    projects: list[ProjectGrant] | None = Field(default=None, max_length=100)
    expected_projects: list[ProjectGrant] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def unique_projects(self) -> "MemberUpdate":
        for grants in [self.projects or [], self.expected_projects]:
            if len({grant.project_id for grant in grants}) != len(grants):
                raise ValueError("Select each project only once")
        return self

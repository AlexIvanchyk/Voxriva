from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.app.features.identity.schemas import Email, Password

projects = "/projects"
project = f"{projects}/{{project_id}}"
environments = f"{project}/environments"
Role = Literal["project_admin", "template_editor", "operator", "viewer"]


class NamedInput(BaseModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]


class NamedResource(NamedInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID


class ProjectView(NamedResource):
    role: str


class MemberInput(BaseModel):
    email: Email
    role: Role
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=100)
    ] = ""
    password: Password | None = None


class RoleInput(BaseModel):
    role: Role


class MemberView(BaseModel):
    account_id: UUID
    email: str
    display_name: str
    role: Role | Literal["platform_admin"]
    created_at: datetime
    inherited: bool = False


class KeyInput(NamedInput):
    expires_in_days: Annotated[int, Field(ge=1, le=365)] | None = 90


class KeyView(NamedResource):
    prefix: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None


class IssuedKey(KeyView):
    key: str


class KeyEnvironment(NamedResource):
    project: NamedResource


class InventoryKey(KeyView):
    environment_id: UUID


class KeyInventory(BaseModel):
    environments: list[KeyEnvironment]
    keys: list[InventoryKey]


class DeliveryScope(BaseModel):
    key_id: UUID
    project_id: UUID
    environment_id: UUID


class EnvironmentInventory(NamedResource):
    project_id: UUID
    project_name: str
    editable: bool

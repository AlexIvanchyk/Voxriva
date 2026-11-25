from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from backend.app.features.identity.dependencies import (
    Database,
    PlatformAdmin,
    PrincipalDependency,
)
from backend.app.features.projects import service
from backend.app.features.projects.dependencies import delivery_scope
from backend.app.features.projects.models import DeliveryKey, Environment
from backend.app.features.projects.schemas import (
    DeliveryScope,
    EnvironmentInventory,
    IssuedKey,
    KeyInput,
    KeyInventory,
    KeyView,
    MemberInput,
    MemberView,
    NamedInput,
    NamedResource,
    ProjectView,
    RoleInput,
    environments,
    project,
    projects,
)
from backend.app.features.projects.service import environment
from backend.app.infrastructure.http import application_context

router = APIRouter(prefix="/api/v1", tags=["Projects and members"])
delivery = APIRouter(prefix="/api/v1/delivery", tags=["Delivery access"])


@router.get(projects)
async def list_projects(
    principal: PrincipalDependency, db: Database
) -> list[ProjectView]:
    return await service.list_projects(principal=principal, db=db)


@router.post(projects, status_code=201)
async def add_project(
    payload: NamedInput, principal: PlatformAdmin, db: Database
) -> ProjectView:
    return await service.add_project(payload=payload, principal=principal, db=db)


@router.get(project)
async def get_project(
    project_id: UUID, principal: PrincipalDependency, db: Database
) -> ProjectView:
    return await service.get_project(project_id=project_id, principal=principal, db=db)


@router.patch(project)
async def edit_project(
    project_id: UUID, payload: NamedInput, principal: PrincipalDependency, db: Database
) -> ProjectView:
    return await service.edit_project(
        project_id=project_id, payload=payload, principal=principal, db=db
    )


@router.delete(project, status_code=204)
async def delete_project(
    project_id: UUID, principal: PrincipalDependency, db: Database
) -> Response:
    await service.delete_project(project_id=project_id, principal=principal, db=db)
    return Response(status_code=204)


@router.get(environments, response_model=list[NamedResource])
async def list_envs(
    project_id: UUID, principal: PrincipalDependency, db: Database
) -> list[Environment]:
    return await service.list_envs(project_id=project_id, principal=principal, db=db)


@router.post(environments, status_code=201, response_model=NamedResource)
async def add_env(
    project_id: UUID, payload: NamedInput, principal: PrincipalDependency, db: Database
) -> Environment:
    return await service.add_env(
        project_id=project_id, payload=payload, principal=principal, db=db
    )


@router.get(environment, response_model=NamedResource)
async def get_env(
    project_id: UUID, environment_id: UUID, principal: PrincipalDependency, db: Database
) -> Environment:
    return await service.get_env(
        project_id=project_id, environment_id=environment_id, principal=principal, db=db
    )


@router.patch(environment, response_model=NamedResource)
async def edit_env(
    project_id: UUID,
    environment_id: UUID,
    payload: NamedInput,
    principal: PrincipalDependency,
    db: Database,
) -> Environment:
    return await service.edit_env(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        principal=principal,
        db=db,
    )


@router.delete(environment, status_code=204)
async def delete_env(
    project_id: UUID, environment_id: UUID, principal: PrincipalDependency, db: Database
) -> Response:
    await service.delete_env(
        project_id=project_id, environment_id=environment_id, principal=principal, db=db
    )
    return Response(status_code=204)


@router.get(f"{project}/members")
async def list_members(
    project_id: UUID, principal: PrincipalDependency, db: Database
) -> list[MemberView]:
    return await service.list_members(project_id=project_id, principal=principal, db=db)


@router.post(f"{project}/members", status_code=201)
async def add_member(
    project_id: UUID,
    payload: MemberInput,
    request: Request,
    principal: PrincipalDependency,
    db: Database,
) -> MemberView:
    return await service.add_member(
        project_id=project_id,
        payload=payload,
        runtime=application_context(request),
        principal=principal,
        db=db,
    )


@router.patch(f"{project}/members/{{account_id}}")
async def edit_member(
    project_id: UUID,
    account_id: UUID,
    payload: RoleInput,
    principal: PrincipalDependency,
    db: Database,
) -> MemberView:
    return await service.edit_member(
        project_id=project_id,
        account_id=account_id,
        payload=payload,
        principal=principal,
        db=db,
    )


@router.delete(f"{project}/members/{{account_id}}", status_code=204)
async def delete_member(
    project_id: UUID, account_id: UUID, principal: PrincipalDependency, db: Database
) -> Response:
    await service.delete_member(
        project_id=project_id, account_id=account_id, principal=principal, db=db
    )
    return Response(status_code=204)


@router.get("/api-keys")
async def key_inventory(principal: PrincipalDependency, db: Database) -> KeyInventory:
    return await service.key_inventory(principal=principal, db=db)


@router.get(f"{environment}/keys", response_model=list[KeyView])
async def list_keys(
    project_id: UUID, environment_id: UUID, principal: PrincipalDependency, db: Database
) -> list[DeliveryKey]:
    return await service.list_keys(
        project_id=project_id, environment_id=environment_id, principal=principal, db=db
    )


@router.post(f"{environment}/keys", status_code=201)
async def issue_key(
    project_id: UUID,
    environment_id: UUID,
    payload: KeyInput,
    principal: PrincipalDependency,
    db: Database,
) -> IssuedKey:
    return await service.issue_key(
        project_id=project_id,
        environment_id=environment_id,
        payload=payload,
        principal=principal,
        db=db,
    )


@router.delete(f"{environment}/keys/{{key_id}}", status_code=204)
async def revoke_key(
    project_id: UUID,
    environment_id: UUID,
    key_id: UUID,
    principal: PrincipalDependency,
    db: Database,
) -> Response:
    await service.revoke_key(
        project_id=project_id,
        environment_id=environment_id,
        key_id=key_id,
        principal=principal,
        db=db,
    )
    return Response(status_code=204)


@delivery.get("/scope")
async def get_key_scope(
    scope: Annotated[DeliveryScope, Depends(delivery_scope)],
) -> DeliveryScope:
    return await service.get_key_scope(scope=scope)


@router.get("/environments")
async def environment_inventory(
    principal: PrincipalDependency, db: Database
) -> list[EnvironmentInventory]:
    return await service.environment_inventory(principal=principal, db=db)

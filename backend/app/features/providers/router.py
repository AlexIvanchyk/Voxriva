from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request

from backend.app.features.identity.dependencies import Database, PrincipalDependency
from backend.app.features.providers import service
from backend.app.features.providers.schemas import (
    BindingInput,
    BindingView,
    ConfigurationInput,
    ConfigurationView,
    RevisionInput,
    RevisionView,
    SendPushTestInput,
    SendTestInput,
    TestInput,
)
from backend.app.infrastructure.http import application_context
from backend.app.shared.provider_contract import ProviderResult

router = APIRouter(prefix="/api/v1/providers", tags=["Providers"])


@router.get("/types")
async def types(
    request: Request, principal: PrincipalDependency
) -> list[dict[str, Any]]:
    return await service.types(
        runtime=application_context(request), principal=principal
    )


@router.get("")
async def list_configurations(
    request: Request, db: Database, principal: PrincipalDependency
) -> list[ConfigurationView]:
    return await service.list_configurations(
        runtime=application_context(request), db=db, principal=principal
    )


@router.post("", status_code=201)
async def create_configuration(
    payload: ConfigurationInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> ConfigurationView:
    return await service.create_configuration(
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.get("/bindings")
async def binding_inventory(
    db: Database, principal: PrincipalDependency
) -> list[BindingView]:
    return await service.binding_inventory(db=db, principal=principal)


@router.get("/resolve")
async def resolved_provider(
    project_id: UUID,
    environment_id: UUID,
    channel: Literal["email", "push"],
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, Any]:
    return await service.resolved_provider(
        project_id=project_id,
        environment_id=environment_id,
        channel=channel,
        db=db,
        principal=principal,
    )


@router.put("/bindings")
async def bind(
    payload: BindingInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, int]:
    return await service.bind(
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.get("/{configuration_id}/revisions")
async def list_revisions(
    configuration_id: UUID,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> list[RevisionView]:
    return await service.list_revisions(
        configuration_id=configuration_id,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.post("/{configuration_id}/revisions", status_code=201)
async def create_revision(
    configuration_id: UUID,
    payload: RevisionInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> ConfigurationView:
    return await service.create_revision(
        configuration_id=configuration_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.post("/{configuration_id}/test-connection")
async def test_connection(
    configuration_id: UUID,
    payload: TestInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> ProviderResult:
    return await service.test_connection(
        configuration_id=configuration_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.post("/{configuration_id}/send-test")
async def send_test(
    configuration_id: UUID,
    payload: SendTestInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> ProviderResult:
    return await service.send_test(
        configuration_id=configuration_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.post("/{configuration_id}/send-test-push")
async def send_test_push(
    configuration_id: UUID,
    payload: SendPushTestInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> ProviderResult:
    return await service.send_test_push(
        configuration_id=configuration_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )

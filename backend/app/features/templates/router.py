from uuid import UUID

from fastapi import APIRouter, Request, Response

from backend.app.features.identity.dependencies import Database, PrincipalDependency
from backend.app.features.templates import service
from backend.app.features.templates.images import ImageContent
from backend.app.features.templates.rendering import RenderResult
from backend.app.features.templates.schemas import (
    DraftUpdate,
    PreviewInput,
    ProjectBindings,
    RenameInput,
    TemplateInput,
    TemplateView,
)
from backend.app.infrastructure.http import application_context

router = APIRouter(prefix="/api/v1/templates", tags=["Template library"])


@router.get("")
async def list_templates(
    db: Database, principal: PrincipalDependency, project_id: UUID | None = None
) -> list[TemplateView]:
    return await service.list_templates(
        db=db, principal=principal, project_id=project_id
    )


@router.post("", status_code=201)
async def create_template(
    payload: TemplateInput, db: Database, principal: PrincipalDependency
) -> TemplateView:
    return await service.create_template(payload=payload, db=db, principal=principal)


@router.get("/{template_id}")
async def get_template(
    template_id: UUID,
    db: Database,
    principal: PrincipalDependency,
    branch_id: UUID | None = None,
) -> TemplateView:
    return await service.get_template(
        template_id=template_id, db=db, principal=principal, branch_id=branch_id
    )


@router.put("/{template_id}/projects")
async def bind_projects(
    template_id: UUID,
    payload: ProjectBindings,
    db: Database,
    principal: PrincipalDependency,
) -> TemplateView:
    return await service.bind_projects(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.put("/{template_id}/draft")
async def save_draft(
    template_id: UUID,
    payload: DraftUpdate,
    db: Database,
    principal: PrincipalDependency,
) -> TemplateView:
    return await service.save_draft(
        template_id=template_id, payload=payload, db=db, principal=principal
    )


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: UUID, db: Database, principal: PrincipalDependency
) -> Response:
    await service.delete_template(template_id=template_id, db=db, principal=principal)
    return Response(status_code=204)


@router.post("/{template_id}/preview")
async def preview(
    template_id: UUID,
    payload: PreviewInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> RenderResult:
    return await service.preview(
        template_id=template_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.post("/{template_id}/variables/rename")
async def rename_variable(
    template_id: UUID,
    payload: RenameInput,
    request: Request,
    db: Database,
    principal: PrincipalDependency,
) -> dict[str, object]:
    return await service.rename_variable(
        template_id=template_id,
        payload=payload,
        runtime=application_context(request),
        db=db,
        principal=principal,
    )


@router.post("/{template_id}/images/validate")
async def validate_image(
    template_id: UUID,
    payload: ImageContent,
    db: Database,
    principal: PrincipalDependency,
) -> ImageContent:
    """Validate an upload for this template; saving the draft persists it atomically."""
    await service.lookup(db, principal, template_id, write=True)
    return payload

from fastapi import APIRouter

from backend.app.features.deployments import inventory_service as service
from backend.app.features.deployments.inventory_schemas import InventoryRow
from backend.app.features.identity.dependencies import Database, PrincipalDependency

router = APIRouter(prefix="/api/v1", tags=["Deployments"])


@router.get("/deployments")
async def inventory(db: Database, principal: PrincipalDependency) -> list[InventoryRow]:
    return await service.inventory(db=db, principal=principal)

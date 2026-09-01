from fastapi import APIRouter, Depends

from systems.generator.app.operational_assets.operational_asset_router import require_inventory_token
from .rebuild_schema import ExtractionRebuildRequest, ExtractionRebuildResponse
from .rebuild_service import RebuildService

router = APIRouter(prefix="/internal/rebuild", tags=["system-rebuild"])


@router.post("/extraction", response_model=ExtractionRebuildResponse, dependencies=[Depends(require_inventory_token)])
async def rebuild_extraction(request: ExtractionRebuildRequest):
    return await RebuildService().execute(request)

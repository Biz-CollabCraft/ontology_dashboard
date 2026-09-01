from fastapi import APIRouter, Depends, HTTPException

from .managed_contract_schema import ManagedContractPublishRequest, ManagedContractPublishResponse
from .managed_contract_service import ManagedContractError, ManagedContractService
from .operational_asset_router import require_inventory_token


router = APIRouter(
    prefix="/internal/operational-contracts",
    tags=["system-operations"],
    dependencies=[Depends(require_inventory_token)],
)


@router.get("/{asset_type}/{asset_id}/versions/{version}")
def read_managed_contract(asset_type: str, asset_id: str, version: str):
    try:
        return ManagedContractService().read(asset_type, asset_id, version)
    except ManagedContractError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/{asset_type}/{asset_id}/publish", response_model=ManagedContractPublishResponse)
def publish_managed_contract(asset_type: str, asset_id: str, request: ManagedContractPublishRequest):
    try:
        return ManagedContractService().publish(
            asset_type, asset_id, request.version, request.expected_sha256, request.payload
        )
    except ManagedContractError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc

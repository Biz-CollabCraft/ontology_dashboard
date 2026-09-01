from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status

from .operational_asset_schema import OperationalAssetInventory
from .operational_asset_service import OperationalAssetInventoryService
from .mapping_management_schema import MappingPublishRequest, MappingPublishResponse, MappingValidationRequest, MappingValidationResponse
from .mapping_management_service import MappingManagementError, MappingManagementService
from systems.generator.app.extraction.mapping_validator import compute_mapping_canonical_sha256


router = APIRouter(prefix="/internal/operational-assets", tags=["system-operations"])


def require_inventory_token(x_system_operations_token: str | None = Header(default=None)) -> None:
    expected = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="operational asset inventory is not configured")
    if x_system_operations_token is None or not hmac.compare_digest(x_system_operations_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid system operations credential")


@router.get("", response_model=OperationalAssetInventory, dependencies=[Depends(require_inventory_token)])
def inventory() -> OperationalAssetInventory:
    return OperationalAssetInventoryService().build_inventory()


@router.get("/mappings/{mapping_id}/versions/{mapping_version}", dependencies=[Depends(require_inventory_token)])
def read_mapping(mapping_id: str, mapping_version: str):
    try:
        return MappingManagementService().read(mapping_id, mapping_version)
    except MappingManagementError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/mappings/validate", response_model=MappingValidationResponse, dependencies=[Depends(require_inventory_token)])
def validate_mapping(request: MappingValidationRequest):
    try:
        normalized, checksum = MappingManagementService().validate(request.mapping_id, request.mapping_version, request.mapping)
        return {"status": "valid", "mapping_sha256": checksum, "normalized_mapping": normalized, "errors": []}
    except MappingManagementError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc
    except Exception as exc:
        return {"status": "invalid", "mapping_sha256": compute_mapping_canonical_sha256(request.mapping), "normalized_mapping": request.mapping, "errors": [{"code": type(exc).__name__, "message": str(exc)}]}


@router.post("/mappings/publish", response_model=MappingPublishResponse, dependencies=[Depends(require_inventory_token)])
def publish_mapping(request: MappingPublishRequest):
    try:
        return MappingManagementService().publish(request.mapping_id, request.mapping_version, request.mapping, request.expected_sha256)
    except MappingManagementError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)}) from exc

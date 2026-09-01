from collections.abc import Callable
import hmac
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from .system_operation_service import SystemOperationService

REGISTRY_STATUSES = {"verified", "discovered", "invalid", "conflicted", "drifted", "unavailable"}
VALIDATION_STATUSES = {"valid", "invalid", "not_validated"}


def build_system_operation_router(*, get_service: Callable[..., SystemOperationService], require_permission: Callable[[str], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/system/assets", tags=["system-operations"])

    @router.get("")
    def list_assets(
        asset_type: str | None = None,
        registry_status: str | None = None,
        validation_status: str | None = None,
        active: bool | None = None,
        search: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        _: Any = Depends(require_permission("system.assets.read")),
        service: SystemOperationService = Depends(get_service),
    ):
        if registry_status and registry_status not in REGISTRY_STATUSES:
            raise HTTPException(status_code=422, detail="unsupported registry_status")
        if validation_status and validation_status not in VALIDATION_STATUSES:
            raise HTTPException(status_code=422, detail="unsupported validation_status")
        return service.list_assets(
            asset_type=asset_type, registry_status=registry_status,
            validation_status=validation_status, active=active, search=search,
            limit=limit, offset=offset,
        )

    @router.get("/reconciliation/latest")
    def latest_reconciliation(
        _: Any = Depends(require_permission("system.assets.read")),
        service: SystemOperationService = Depends(get_service),
    ):
        return service.latest_reconciliation()

    @router.get("/{asset_id}/versions")
    def list_versions(
        asset_id: str,
        _: Any = Depends(require_permission("system.assets.read")),
        service: SystemOperationService = Depends(get_service),
    ):
        return {"items": service.list_versions(asset_id)}

    @router.get("/{asset_id}")
    def get_asset(
        asset_id: str,
        _: Any = Depends(require_permission("system.assets.read")),
        service: SystemOperationService = Depends(get_service),
    ):
        return service.get_asset(asset_id)

    return router


def build_system_operation_internal_router(*, get_service: Callable[..., SystemOperationService]) -> APIRouter:
    router = APIRouter(prefix="/internal/system/operational-assets", tags=["system-operations-internal"])

    def require_service_token(x_system_operations_token: str | None = Header(default=None)) -> None:
        expected = os.getenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "").strip()
        if not expected:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="operational asset reconciliation is not configured")
        if x_system_operations_token is None or not hmac.compare_digest(x_system_operations_token, expected):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid system operations credential")

    @router.post("/reconcile", dependencies=[Depends(require_service_token)])
    def reconcile(snapshot: dict[str, Any], service: SystemOperationService = Depends(get_service)):
        return service.reconcile(snapshot)

    @router.post("/refresh", dependencies=[Depends(require_service_token)])
    def refresh(service: SystemOperationService = Depends(get_service)):
        return service.refresh()

    return router

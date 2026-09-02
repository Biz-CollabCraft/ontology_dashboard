from collections.abc import Callable
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query


def build_e2e_router(*, get_service: Callable[..., Any], require_permission: Callable[[str], Any]) -> APIRouter:
    router = APIRouter(prefix="/api/system", tags=["system-e2e"])

    @router.get("/e2e-runs")
    def runs(limit: int = Query(100, ge=1, le=1000), principal: Any = Depends(require_permission("system.e2e.read")), service=Depends(get_service)):
        return service.list_runs(organization_id=principal.organization_id, limit=limit)

    @router.get("/e2e-runs/{run_id}")
    def run(run_id: str, principal: Any = Depends(require_permission("system.e2e.read")), service=Depends(get_service)):
        try: return service.get_run(run_id, organization_id=principal.organization_id)
        except KeyError: raise HTTPException(404, detail={"code": "SYSTEM_E2E_RUN_NOT_FOUND"})

    @router.get("/e2e-runs/{run_id}/timeline")
    def timeline(run_id: str, principal: Any = Depends(require_permission("system.e2e.read")), service=Depends(get_service)):
        return service.timeline(run_id, organization_id=principal.organization_id)

    @router.get("/e2e-events/{event_id}")
    def event(event_id: str, principal: Any = Depends(require_permission("system.e2e.read")), service=Depends(get_service)):
        try: return service.get_event(event_id, organization_id=principal.organization_id)
        except KeyError: raise HTTPException(404, detail={"code": "SYSTEM_E2E_EVENT_NOT_FOUND"})

    @router.get("/alerts")
    def alerts(limit: int = Query(100, ge=1, le=1000), principal: Any = Depends(require_permission("system.e2e.read")), service=Depends(get_service)):
        return service.list_alerts(organization_id=principal.organization_id, limit=limit)
    return router

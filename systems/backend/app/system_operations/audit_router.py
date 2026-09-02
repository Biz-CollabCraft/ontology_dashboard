from collections.abc import Callable
from typing import Any
from fastapi import APIRouter, Depends, Query, Request
from .audit_schema import LogExportRequest
from .recovery_guide import recovery_guide


def build_audit_router(*, get_service: Callable[..., Any], require_permission: Callable[[str], Any], require_csrf: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/system", tags=["system-audit"])

    @router.get("/audit")
    def audit(actor_id: str | None = None, action: str | None = None, resource_type: str | None = None,
              resource_id: str | None = None, outcome: str | None = None, request_id: str | None = None,
              run_id: str | None = None, job_id: str | None = None, event_id: str | None = None,
              occurred_from: str | None = None, occurred_to: str | None = None,
              limit: int = Query(100, ge=1, le=1000), _: Any = Depends(require_permission("system.audit.read")), service=Depends(get_service)):
        return service.list_audit(locals(), limit)

    @router.get("/audit/{audit_id}")
    def audit_detail(audit_id: str, _: Any = Depends(require_permission("system.audit.read")), service=Depends(get_service)):
        return service.get_audit(audit_id)

    @router.get("/logs")
    def logs(service_name: str | None = None, domain: str | None = None, severity: str | None = None,
             error_code: str | None = None, request_id: str | None = None, run_id: str | None = None,
             job_id: str | None = None, event_id: str | None = None, occurred_from: str | None = None,
             occurred_to: str | None = None, limit: int = Query(100, ge=1, le=1000),
             _: Any = Depends(require_permission("system.logs.read")), service=Depends(get_service)):
        filters = {"service": service_name, "domain": domain, "severity": severity, "error_code": error_code,
                   "request_id": request_id, "run_id": run_id, "job_id": job_id, "event_id": event_id,
                   "occurred_from": occurred_from, "occurred_to": occurred_to}
        return service.list_logs(filters, limit)

    @router.post("/log-exports", dependencies=[Depends(require_csrf)])
    def create_export(body: LogExportRequest, request: Request, principal=Depends(require_permission("system.logs.export")), service=Depends(get_service)):
        return service.export(body, principal.user_id, getattr(request.state, "request_id", "request"))

    @router.get("/log-exports/{export_id}")
    def export_detail(export_id: str, _: Any = Depends(require_permission("system.logs.export")), service=Depends(get_service)):
        return service.get_export(export_id)

    @router.get("/recovery-guides/{error_code}")
    def guide(error_code: str, _: Any = Depends(require_permission("system.recovery_guides.read"))):
        return recovery_guide(error_code)

    return router

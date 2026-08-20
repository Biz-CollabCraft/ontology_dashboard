"""FastAPI transport owned by the Maintenance application capability."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends

from .maintenance_schema import DecisionRequest, NoteRequest
from .maintenance_service import MaintenanceApplicationService


DependencyFactory = Callable[..., Any]
PermissionFactory = Callable[[str], Callable[..., Any]]


def build_maintenance_router(
    *,
    get_maintenance_service: DependencyFactory,
    require_permission: PermissionFactory,
    require_csrf: DependencyFactory,
) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["maintenance"])

    @router.post("/events/{event_id}/decision")
    def record_decision(
        event_id: str,
        request: DecisionRequest,
        principal: Any = Depends(require_permission("events.decision")),
        _: None = Depends(require_csrf),
        maintenance: MaintenanceApplicationService = Depends(get_maintenance_service),
    ):
        return maintenance.record_decision(
            event_id=event_id,
            request=request,
            principal=principal,
        )

    @router.post("/events/{event_id}/notes")
    def add_note(
        event_id: str,
        request: NoteRequest,
        principal: Any = Depends(require_permission("events.note")),
        _: None = Depends(require_csrf),
        maintenance: MaintenanceApplicationService = Depends(get_maintenance_service),
    ):
        return maintenance.add_note(event_id=event_id, request=request, principal=principal)

    @router.get("/events/{event_id}/activity")
    def event_activity(
        event_id: str,
        principal: Any = Depends(require_permission("events.read")),
        maintenance: MaintenanceApplicationService = Depends(get_maintenance_service),
    ):
        return maintenance.event_activity(event_id=event_id, principal=principal)

    return router


__all__ = ["build_maintenance_router"]

"""Manufacturing-compatible Event routes shared by Project showcase domain packs."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.equipment.equipment_router import register_equipment_routes

from ..contracts import FollowUpRequest, LayoutRequest, ReportRequest
from ..dependencies import (
    get_identity_service,
    get_service,
    require_csrf,
    require_manufacturing_scope,
    require_permission,
)
from app.identity import AuthError, IdentityService, Principal
from ..service import ManufacturingPredictiveMaintenanceService

router = APIRouter(prefix="/api", tags=["manufacturing-domain-pack"])
register_equipment_routes(
    router,
    service_dependency=get_service,
    authorization_dependency=require_manufacturing_scope,
)


def _require_active_event_project(
    principal: Principal,
    service: ManufacturingPredictiveMaintenanceService,
    event_id: str,
) -> str:
    project_id = service.project_id_for_event(event_id)
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 Event입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 Event가 속한 Project를 활성화해야 합니다.")
    return project_id




@router.get("/events")
def list_events(
    _: Principal = Depends(require_manufacturing_scope),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    return {"items": service.list_events()}


@router.get("/events/{event_id}")
def get_event(
    event_id: str,
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    _require_active_event_project(principal, service, event_id)
    return service.event(event_id)


@router.get("/events/{event_id}/evidence")
def get_evidence(
    event_id: str,
    view: Literal["legacy", "canonical"] = Query(default="legacy"),
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    _require_active_event_project(principal, service, event_id)
    return service.evidence(event_id, view=view)


@router.post("/events/{event_id}/report")
def create_report(
    event_id: str,
    request: ReportRequest,
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    identity: IdentityService = Depends(get_identity_service),
):
    _require_active_event_project(principal, service, event_id)
    role = identity.legacy_dashboard_role(principal, request.role)
    report, trace = service.report(
        event_id,
        ReportRequest(role=role, locale=request.locale, use_llm=request.use_llm),
    )
    return {"report": report.model_dump(mode="json"), "trace": trace}


@router.post("/events/{event_id}/layout")
def create_layout(
    event_id: str,
    request: LayoutRequest,
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    identity: IdentityService = Depends(get_identity_service),
):
    _require_active_event_project(principal, service, event_id)
    role = identity.legacy_dashboard_role(principal, request.role)
    layout, trace = service.layout(
        event_id,
        LayoutRequest(role=role, locale=request.locale, intent=request.intent, use_llm=request.use_llm),
    )
    return {"layout": layout.model_dump(mode="json"), "trace": trace}


@router.post("/events/{event_id}/follow-up")
def follow_up(
    event_id: str,
    request: FollowUpRequest,
    principal: Principal = Depends(require_permission("events.read")),
    _: None = Depends(require_csrf),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    identity: IdentityService = Depends(get_identity_service),
):
    _require_active_event_project(principal, service, event_id)
    role = identity.legacy_dashboard_role(principal, request.role)
    safe_request = FollowUpRequest(role=role, locale=request.locale, question=request.question)
    return service.follow_up(event_id, safe_request).model_dump(mode="json")

"""Manufacturing-compatible Event routes shared by Project showcase domain packs."""

from __future__ import annotations

import uuid

from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.common.rate_limit import RateLimitRule, RateLimiter
from app.equipment.equipment_router import register_equipment_routes

from app.dependencies import (
    MANUFACTURING_WORKSPACE,
    get_identity_service,
    get_ontology_service,
    get_rate_limiter,
    get_runtime_asset_detail_service,
    get_service,
    rate_limit_subject,
    require_csrf,
    require_manufacturing_scope,
    require_permission,
)
from app.identity import AuthError, IdentityService, Principal
from app.ontology.ontology_domain import ActionInvocation
from app.ontology.projection import inspection_object_id, risk_event_object_id
from app.ontology.ontology_service import OntologyService

from .asset_detail_view_model import AssetDetailViewModelService
from .contracts import DecisionRequest, FollowUpRequest, LayoutRequest, NoteRequest, ReportRequest
from .service import EventNotFound, ManufacturingPredictiveMaintenanceService

router = APIRouter(prefix="/api", tags=["manufacturing-domain-pack"])
AGENT_REVIEW_SUMMARY_MATERIALIZE_RATE = RateLimitRule(limit=12, window_seconds=60)
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


def _require_configured_action_project(project_id: str) -> None:
    if project_id != "manufacturing-demo-project":
        raise AuthError(
            422,
            "project_action_not_configured",
            "이 showcase Project는 현재 Evidence 조회 전용입니다. Action mapping을 먼저 게시해야 합니다.",
        )


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


@router.get("/objects/{asset_id}/detail-view")
def get_asset_detail_view(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    workspace_id: str = Query(default=MANUFACTURING_WORKSPACE, max_length=160),
    dataset_version_id: str | None = Query(default=None, max_length=160),
    event_id: str | None = Query(default=None, max_length=240),
    history_window: Literal["24h", "7d", "30d"] = Query(default="24h"),
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    runtime_detail: AssetDetailViewModelService | None = Depends(
        get_runtime_asset_detail_service
    ),
):
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 Object입니다.")
    if not principal.is_admin and workspace_id not in principal.workspace_scopes:
        raise AuthError(403, "workspace_scope_denied", "허용된 Workspace 범위를 벗어난 Object입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 Object가 속한 Project를 활성화해야 합니다.")
    if dataset_version_id and event_id and runtime_detail is not None:
        try:
            return runtime_detail.latest_detail_view(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                asset_id=asset_id,
                dataset_version_id=dataset_version_id,
                event_id=event_id,
                history_window=history_window,
            )
        except KeyError as exc:
            raise EventNotFound(event_id) from exc
    return service.asset_detail_view_model(
        asset_id,
        project_id,
        dataset_version_id=dataset_version_id,
        history_window=history_window,
    )


@router.get("/objects/{asset_id}/agent-review-packet")
def get_agent_review_packet(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    dataset_version_id: str | None = Query(default=None, max_length=160),
    history_window: Literal["24h", "7d", "30d"] = Query(default="24h"),
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Object 범위를 벗어난 Agent Review Packet입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 Object가 속한 Project를 활성화해야 합니다.")
    return service.agent_review_packet(
        asset_id,
        project_id,
        dataset_version_id=dataset_version_id,
        history_window=history_window,
    )


def _authorize_agent_review_summary(
    *,
    principal: Principal,
    project_id: str,
) -> None:
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Object 범위를 벗어난 Agent Review Summary입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 Object가 속한 Project를 활성화해야 합니다.")
    if not principal.is_admin and MANUFACTURING_WORKSPACE not in principal.workspace_scopes:
        raise AuthError(403, "workspace_scope_denied", "허용된 Workspace 범위를 벗어난 Agent Review Summary입니다.")


@router.get("/objects/{asset_id}/agent-review-summary")
def get_agent_review_summary(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    dataset_version_id: str | None = Query(default=None, max_length=160),
    history_window: Literal["24h", "7d", "30d"] = Query(default="24h"),
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    _authorize_agent_review_summary(principal=principal, project_id=project_id)
    summary, trace = service.cached_agent_review_summary(
        asset_id,
        project_id,
        organization_id=principal.organization_id,
        workspace_id=MANUFACTURING_WORKSPACE,
        dataset_version_id=dataset_version_id,
        history_window=history_window,
    )
    status_code = 200 if summary is not None else 202
    return JSONResponse(
        status_code=status_code,
        content={"summary": summary, "trace": trace},
    )


@router.post("/objects/{asset_id}/agent-review-summary")
def create_agent_review_summary(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    dataset_version_id: str | None = Query(default=None, max_length=160),
    history_window: Literal["24h", "7d", "30d"] = Query(default="24h"),
    trigger: Literal["manual_materialization", "ui_manual_regeneration"] = Query(
        default="manual_materialization"
    ),
    principal: Principal = Depends(require_permission("agent.review.materialize")),
    _: None = Depends(require_csrf),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
):
    _authorize_agent_review_summary(principal=principal, project_id=project_id)
    limiter.check(
        bucket="agent-review-summary.materialize",
        subject=rate_limit_subject(
            principal.user_id,
            project_id,
            asset_id,
            history_window,
            trigger,
        ),
        rule=AGENT_REVIEW_SUMMARY_MATERIALIZE_RATE,
    )
    summary, trace = service.agent_review_summary(
        asset_id,
        project_id,
        organization_id=principal.organization_id,
        workspace_id=MANUFACTURING_WORKSPACE,
        dataset_version_id=dataset_version_id,
        history_window=history_window,
        trigger=trigger,
    )
    return {"summary": summary, "trace": trace}


@router.get("/projects/{project_id}/agent-review-workflow-runs")
def list_agent_review_workflow_runs(
    project_id: str,
    asset_id: str | None = Query(default=None, max_length=160),
    event_id: str | None = Query(default=None, max_length=160),
    dataset_version_id: str | None = Query(default=None, max_length=160),
    status: Literal["running", "completed", "partial", "failed"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(require_permission("admin.audit.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    _authorize_agent_review_summary(principal=principal, project_id=project_id)
    return service.agent_review_workflow_runs(
        project_id,
        organization_id=principal.organization_id,
        workspace_id=MANUFACTURING_WORKSPACE,
        asset_id=asset_id,
        event_id=event_id,
        dataset_version_id=dataset_version_id,
        status=status,
        limit=limit,
    )


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


@router.post("/events/{event_id}/decision")
def record_decision(
    event_id: str,
    request: DecisionRequest,
    principal: Principal = Depends(require_permission("events.decision")),
    _: None = Depends(require_csrf),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    ontology: OntologyService = Depends(get_ontology_service),
):
    project_id = _require_active_event_project(principal, service, event_id)
    _require_configured_action_project(project_id)
    execution = ontology.invoke(
        ActionInvocation(
            action_type="record_operational_decision",
            object_id=risk_event_object_id(event_id),
            workspace_id=MANUFACTURING_WORKSPACE,
            parameters={"decision": request.decision, "note": request.note},
            idempotency_key=f"legacy-decision:{uuid.uuid4()}",
        ),
        principal,
    )
    return execution.result


@router.post("/events/{event_id}/notes")
def add_note(
    event_id: str,
    request: NoteRequest,
    principal: Principal = Depends(require_permission("events.note")),
    _: None = Depends(require_csrf),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    ontology: OntologyService = Depends(get_ontology_service),
):
    project_id = _require_active_event_project(principal, service, event_id)
    _require_configured_action_project(project_id)
    execution = ontology.invoke(
        ActionInvocation(
            action_type="record_inspection_note",
            object_id=inspection_object_id(event_id),
            workspace_id=MANUFACTURING_WORKSPACE,
            parameters={"body": request.body},
            idempotency_key=f"legacy-note:{uuid.uuid4()}",
        ),
        principal,
    )
    return execution.result


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


@router.get("/events/{event_id}/activity")
def event_activity(
    event_id: str,
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    _require_active_event_project(principal, service, event_id)
    service.event(event_id)
    return service.repository.event_activity(event_id)

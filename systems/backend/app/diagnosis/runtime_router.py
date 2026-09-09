"""V3.1 Result Artifact, canonical observation, and replay APIs."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from app.operations.contracts import AppLocale
from app.dependencies import (
    client_ip,
    get_identity_service,
    get_predictive_maintenance_runtime_service,
    require_csrf,
    require_permission,
)
from app.identity import CSRF_COOKIE, SESSION_COOKIE, AuthError, IdentityService, Principal
from app.diagnosis.runtime_schema import (
    DatasetVersionSelectionRequest,
    ReplayControlRequest,
    ReplayStartRequest,
)
from app.diagnosis.evidence_projection import (
    evidence_snapshot_basis_from_artifact,
    product_result_artifact_to_event_evidence_projection,
)
from app.diagnosis.runtime_service import PredictiveMaintenanceRuntimeService
from app.diagnosis.ports import ALLOWED_DERIVED_MEASURES
from app.diagnosis.contracts import (
    CompleteFileTickNotFound,
    filesystem_event_artifact as _contract_filesystem_event_artifact,
    latest_complete_file_tick as _contract_latest_complete_file_tick,
    measurement_factors as _contract_measurement_factors,
    risk_from_file_record as _contract_risk_from_file_record,
    risk_status as _contract_risk_status,
)

router = APIRouter(
    prefix="/api/projects/{project_id}/workspaces/{workspace_id}/predictive-maintenance",
    tags=["predictive-maintenance-runtime"],
)
internal_router = APIRouter(prefix="/internal", tags=["prediction-result-inbox"])
PREDICTION_RESULT_INGEST_TOKEN_ENV = "PREDICTION_RESULT_INGEST_TOKEN"
PREDICTION_RESULT_INGEST_ORG_ENV = "PREDICTION_RESULT_INGEST_ORGANIZATION_ID"


def _risk_from_file_record(record: dict[str, Any]) -> float:
    return _contract_risk_from_file_record(record)


def _risk_status(score: float) -> str:
    return _contract_risk_status(score)


def _measurement_factors(record: dict[str, Any]) -> list[dict[str, Any]]:
    return _contract_measurement_factors(record)


def _latest_complete_file_tick() -> tuple[Path, str, list[dict[str, Any]], list[tuple[str, dict[str, dict[str, Any]]]]]:
    try:
        return _contract_latest_complete_file_tick()
    except CompleteFileTickNotFound as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _filesystem_event_artifact(
    *, run_id: str, observed_at: str, record: dict[str, Any], event_id: str
) -> dict[str, Any]:
    return _contract_filesystem_event_artifact(
        run_id=run_id,
        observed_at=observed_at,
        record=record,
        event_id=event_id,
    )


def filesystem_event_evidence_projection(event_id: str) -> dict[str, Any] | None:
    if not event_id.startswith("FILE#"):
        return None
    stream, latest_observed_at, records, complete_ticks = _latest_complete_file_tick()
    run_id = stream.parents[1].name
    ticks = complete_ticks or [(latest_observed_at, {str(item["asset_id"]): item for item in records})]
    for observed_at, tick_records in reversed(ticks):
        for record in tick_records.values():
            candidate = f"FILE#{run_id}#{record.get('observation_id', record.get('asset_id'))}"
            if candidate != event_id:
                continue
            artifact = _filesystem_event_artifact(
                run_id=run_id, observed_at=observed_at, record=record, event_id=event_id
            )
            projection = product_result_artifact_to_event_evidence_projection(artifact)
            projection["event_id"] = event_id
            projection["evidence_id"] = f"EVD-{artifact['artifact_id']}"
            projection["artifact_reference"]["event_id"] = event_id
            return projection
    return None


def _filesystem_overview(project_id: str, workspace_id: str) -> dict[str, Any]:
    stream, observed_at, records, complete_ticks = _latest_complete_file_tick()
    run_id = stream.parents[1].name
    assets: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    line_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        asset_id = str(record["asset_id"])
        asset_type = str(record.get("asset_type") or "equipment")
        score = _risk_from_file_record(record)
        risk_status = _risk_status(score)
        cell = str(record.get("cell_id") or "미분류")
        site = str(record.get("site_id") or "미분류")
        line = cell.split("-")[0] if "-" in cell else cell
        display_type = "CNC 가공기" if asset_type == "cnc" else "공기압축기"
        display_name = f"{cell} · {display_type} {asset_id.rsplit('-', 1)[-1]}"
        event_id = f"FILE#{run_id}#{record.get('observation_id', asset_id)}"
        event_artifact = _filesystem_event_artifact(
            run_id=run_id, observed_at=observed_at, record=record, event_id=event_id
        )
        factor_definitions = {item["feature"]: item for item in _measurement_factors(record)}
        sensor_history = []
        for feature, factor in factor_definitions.items():
            points = []
            for tick_at, tick_records in complete_ticks:
                value = (tick_records.get(asset_id, {}).get("measurements") or {}).get(feature)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    points.append({"observedAt": tick_at, "value": float(value)})
            if points:
                sensor_history.append({
                    "feature": feature,
                    "label": factor["label"],
                    "unit": factor["unit"],
                    "points": points,
                })
        asset = {
            "assetId": asset_id,
            "displayName": display_name,
            "assetType": asset_type,
            "site": site,
            "line": line,
            "cell": cell,
            "status": risk_status,
            "failureProbability": score,
            "confidence": "unavailable",
            "confidenceScore": None,
            "criticality": None,
            "assignedEngineer": None,
            "estimatedDowntimeMinutes": None,
            "sparePartAvailable": None,
            "predictedFailureType": "실시간 센서 이상 징후" if risk_status != "normal" else "이상 징후 없음",
            "recommendedDecision": "request_inspection" if risk_status in {"critical", "warning"} else "continue_monitoring",
            "observedAt": observed_at,
            "eventId": event_id,
            "maintenanceSnapshotBasis": evidence_snapshot_basis_from_artifact(
                event_artifact, event_id=event_id
            ),
            "topFactors": _measurement_factors(record),
            "sensorHistory": sensor_history,
            "riskHistory": [{"observedAt": tick_at, "value": _risk_from_file_record(tick_records[asset_id])} for tick_at, tick_records in complete_ticks if asset_id in tick_records],
            "provenance": {
                "datasetId": None,
                "datasetVersionId": run_id,
                "datasetLabel": "gen_data 파일 관측",
                "sourceVersion": str(record.get("generator_version") or "gen_data"),
                "modelVersion": None,
                "policyVersion": None,
                "schemaVersion": str(record.get("schema_version") or ""),
                "promptVersion": None,
                "sourceRefs": [f"gen_data://runs/{run_id}/source/sensor_records.jsonl"],
            },
        }
        assets.append(asset)
        line_groups[line].append(asset)
        if risk_status != "normal":
            events.append({
                "eventId": event_id,
                "scenarioId": str(record.get("branch_kind") or "live-file"),
                "assetId": asset_id,
                "assetName": display_name,
                "line": line,
                "status": risk_status,
                "failureProbability": score,
                "confidence": "unavailable",
                "predictedFailureType": asset["predictedFailureType"],
                "recommendedDecision": asset["recommendedDecision"],
                "criticality": None,
                "assignedEngineer": None,
                "estimatedDowntimeMinutes": None,
                "sparePartAvailable": None,
                "observedAt": observed_at,
                "datasetVersionId": run_id,
                "ontologyObjectId": None,
            })
    counts = {key: sum(item["status"] == key for item in assets) for key in ("normal", "attention", "warning", "critical", "data_quality_hold")}
    line_risk = []
    for line, items in sorted(line_groups.items()):
        line_risk.append({
            "line": line,
            "total": len(items),
            "normal": sum(item["status"] == "normal" for item in items),
            "critical": sum(item["status"] == "critical" for item in items),
            "warning": sum(item["status"] == "warning" for item in items),
            "attention": sum(item["status"] == "attention" for item in items),
            "dataQualityHold": 0,
            "averageRisk": round(sum(item["failureProbability"] for item in items) / len(items), 4),
        })
    return {
        "context": {
            "projectId": project_id,
            "projectName": "Smart Factory A",
            "workspaceId": workspace_id,
            "workspaceName": "Production Reliability",
            "datasetVersionId": run_id,
            "datasetLabel": "gen_data 실시간 파일 관측",
            "sourceVersion": "filesystem",
            "modelVersion": None,
            "schemaVersion": str(records[0].get("schema_version") or ""),
            "sourceMode": "canonical-runtime",
            "sourceStatus": "파일 시스템 연결됨 · 마지막 완성 틱",
            "refreshedAt": datetime.now(timezone.utc).isoformat(),
            "observedAt": observed_at,
            "stale": False,
            "warnings": [],
        },
        "assets": assets,
        "events": sorted(events, key=lambda item: item["failureProbability"], reverse=True),
        "metrics": {
            "totalAssets": len(assets),
            "normal": counts["normal"],
            "attention": counts["attention"],
            "warning": counts["warning"],
            "critical": counts["critical"],
            "dataQualityHold": counts["data_quality_hold"],
            "averageRisk": round(sum(item["failureProbability"] for item in assets) / len(assets), 4) if assets else None,
            "estimatedDowntimeMinutes": None,
            "pendingDecisions": len(events),
        },
        "lineRisk": line_risk,
        "selectionRestoreError": None,
    }
def require_scope(
    *,
    principal: Principal,
    identity: IdentityService,
    project_id: str,
    workspace_id: str,
) -> None:
    identity.require_project(principal, project_id)
    identity.require_workspace(principal, workspace_id)


def selected_dataset_version(
    *,
    service: PredictiveMaintenanceRuntimeService,
    principal: Principal,
    project_id: str,
    workspace_id: str,
    requested: str | None,
) -> str | None:
    if requested:
        return requested
    return service.versions(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=principal.user_id,
    ).default_dataset_version_id


def _prediction_inbox_response(receipt):
    body = receipt.model_dump(mode="json")
    if receipt.validation_status == "conflict":
        return JSONResponse(status_code=status.HTTP_409_CONFLICT, content=body)
    if receipt.validation_status == "rejected":
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=body,
        )
    if receipt.validation_status == "duplicate":
        return JSONResponse(status_code=status.HTTP_200_OK, content=body)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _prediction_result_service_principal(*, project_id: str, workspace_id: str) -> Principal:
    return Principal(
        user_id="service:generator-runtime",
        organization_id=os.getenv(PREDICTION_RESULT_INGEST_ORG_ENV, "org-ontology-demo"),
        email="generator-runtime@service.local",
        display_name="Generator Runtime",
        status="active",
        roles=["service"],
        permissions=["predictions.ingest"],
        workspace_scopes=[workspace_id],
        project_scopes=[project_id],
        active_project_id=project_id,
        active_project_roles=["service"],
        is_admin=False,
        default_path="/internal/prediction-results",
        landing_key="internal",
    )


def internal_prediction_ingest_principal(
    request: Request,
    project_id: str = Query(max_length=160),
    workspace_id: str = Query(max_length=160),
    identity: IdentityService = Depends(get_identity_service),
) -> Principal:
    configured_token = os.getenv(PREDICTION_RESULT_INGEST_TOKEN_ENV, "").strip()
    supplied_token = _bearer_token(request.headers.get("Authorization"))
    if configured_token:
        if supplied_token and hmac.compare_digest(supplied_token, configured_token):
            return _prediction_result_service_principal(
                project_id=project_id,
                workspace_id=workspace_id,
            )
        if supplied_token:
            raise AuthError("authentication_required", "Prediction Result service token is invalid.")

    session_token = request.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise AuthError("authentication_required", "로그인이 필요합니다.")
    principal = identity.principal_for_token(
        session_token,
        user_agent=request.headers.get("User-Agent"),
        client_ip=client_ip(request),
    )
    identity.require_permission(principal, "predictions.ingest")
    identity.verify_csrf(request.cookies.get(CSRF_COOKIE), request.headers.get("X-CSRF-Token"))
    return principal


@router.get("/context")
def runtime_context(
    project_id: str,
    workspace_id: str,
    dataset_version_id: str | None = Query(default=None, max_length=160),
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    try:
        return service.context(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            dataset_version_id=selected_dataset_version(
                service=service,
                principal=principal,
                project_id=project_id,
                workspace_id=workspace_id,
                requested=dataset_version_id,
            ),
            user_id=principal.user_id,
        ).model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Dataset Version not found: {error.args[0]}") from error


@router.get("/versions")
def runtime_versions(
    project_id: str,
    workspace_id: str,
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    return service.versions(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=principal.user_id,
    ).model_dump(mode="json")


@router.put("/selection")
def select_runtime_version(
    project_id: str,
    workspace_id: str,
    payload: DatasetVersionSelectionRequest,
    principal: Principal = Depends(require_permission("events.read")),
    _: None = Depends(require_csrf),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    try:
        return service.select_version(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=principal.user_id,
            dataset_version_id=payload.dataset_version_id,
        ).model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Dataset Version not found in this Project and Workspace: {error.args[0]}",
        ) from error


@router.get("/dashboard")
def dashboard_source(
    project_id: str,
    workspace_id: str,
    dataset_version_id: str | None = Query(default=None, max_length=160),
    selected_event_id: str | None = Query(default=None, max_length=320),
    role: str = Query(default="manager", pattern="^(manager|engineer|executive)$"),
    report_type: str | None = Query(
        default=None,
        pattern="^(inspection-summary|operations-decision|executive-brief|maintenance-effect|weekly-risk)$",
    ),
    intent: str = Query(
        default="overview",
        pattern="^(overview|explain-risk|compare|summarize-manager|detail-engineer|recommend-check|show-model-details)$",
    ),
    locale: AppLocale = Query(default="ko-KR"),
    view: Literal["legacy", "canonical"] = Query(default="legacy"),
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    try:
        response = service.dashboard(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=principal.user_id,
            dataset_version_id=dataset_version_id,
            selected_event_id=selected_event_id,
            role=role,
            report_type=report_type,
            intent=intent,
            locale=locale,
            view=view,
        )
        if selected_event_id and response.selected_event_id != selected_event_id:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "selected_snapshot_not_found",
                    "message": "The explicitly selected Decision Case snapshot could not be restored.",
                    "selected_event_id": selected_event_id,
                },
            )
        return response.model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Dataset Version not found: {error.args[0]}") from error


@router.get("/release")
def release_overview(
    project_id: str,
    workspace_id: str,
    dataset_version_id: str | None = Query(default=None, max_length=160),
    principal: Principal = Depends(require_permission("governance.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    try:
        return service.release_overview(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            dataset_version_id=selected_dataset_version(
                service=service,
                principal=principal,
                project_id=project_id,
                workspace_id=workspace_id,
                requested=dataset_version_id,
            ),
            user_id=principal.user_id,
        ).model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"Dataset Version not found: {error.args[0]}") from error


@router.get("/results/latest")
def latest_product_results(
    project_id: str,
    workspace_id: str,
    dataset_version_id: str | None = Query(default=None, max_length=160),
    asset_id: str | None = Query(default=None, max_length=160),
    site_id: str | None = Query(default=None, max_length=160),
    cell_id: str | None = Query(default=None, max_length=160),
    asset_type: str | None = Query(default=None, pattern="^(compressor|cnc)$"),
    status_grade: str | None = Query(
        default=None, pattern="^(normal|attention|warning|critical)$"
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    return service.latest_results(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=selected_dataset_version(
            service=service,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            requested=dataset_version_id,
        ),
        asset_id=asset_id,
        site_id=site_id,
        cell_id=cell_id,
        asset_type=asset_type,
        status_grade=status_grade,
        offset=offset,
        limit=limit,
    ).model_dump(mode="json")


@router.get("/filesystem-overview")
def filesystem_overview(
    project_id: str,
    workspace_id: str,
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
):
    """Serve the engineer overview from the latest complete gen_data file tick."""
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    return _filesystem_overview(project_id, workspace_id)


@router.get("/results/post-maintenance")
def post_maintenance_product_result(
    project_id: str,
    workspace_id: str,
    asset_id: str = Query(min_length=1, max_length=160),
    maintenance_event_id: str = Query(min_length=1, max_length=240),
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    result = service.post_maintenance_result(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        asset_id=asset_id,
        maintenance_event_id=maintenance_event_id,
    )
    return None if result is None else result.model_dump(mode="json")


@router.get("/snapshots/{prediction_id}")
def snapshot_drilldown(
    project_id: str,
    workspace_id: str,
    prediction_id: str,
    dataset_version_id: str | None = Query(default=None, max_length=160),
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    try:
        return service.snapshot_drilldown(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            dataset_version_id=selected_dataset_version(
                service=service,
                principal=principal,
                project_id=project_id,
                workspace_id=workspace_id,
                requested=dataset_version_id,
            ),
            prediction_id=prediction_id,
        ).model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"prediction not found: {error.args[0]}") from error


@router.get("/timeline")
def prediction_timeline(
    project_id: str,
    workspace_id: str,
    dataset_version_id: str | None = Query(default=None, max_length=160),
    asset_id: str | None = Query(default=None, max_length=160),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=5000),
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    return service.timeline(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=selected_dataset_version(
            service=service,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            requested=dataset_version_id,
        ),
        asset_id=asset_id,
        start=start,
        end=end,
        offset=offset,
        limit=limit,
    )


@router.get("/observations")
def observation_window(
    project_id: str,
    workspace_id: str,
    start: datetime,
    end: datetime,
    dataset_version_id: str | None = Query(default=None, max_length=160),
    asset_id: str | None = Query(default=None, max_length=160),
    site_id: str | None = Query(default=None, max_length=160),
    cell_id: str | None = Query(default=None, max_length=160),
    asset_type: str | None = Query(default=None, pattern="^(compressor|cnc)$"),
    grain: str = Query(default="raw", pattern="^(raw|10m|1h)$"),
    derived_measure: list[str] = Query(default=[]),
    limit: int = Query(default=1000, ge=1, le=5000),
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    selected = set(derived_measure)
    invalid = selected - ALLOWED_DERIVED_MEASURES
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported derived measures: {sorted(invalid)}",
        )
    return service.observations(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=selected_dataset_version(
            service=service,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            requested=dataset_version_id,
        ),
        start=start,
        end=end,
        asset_id=asset_id,
        site_id=site_id,
        cell_id=cell_id,
        asset_type=asset_type,
        grain=grain,
        derived_measures=selected,
        limit=limit,
    ).model_dump(mode="json")


@router.post("/prediction-result-batches")
def receive_prediction_result_batch(
    project_id: str,
    workspace_id: str,
    payload: dict[str, Any] = Body(...),
    principal: Principal = Depends(require_permission("predictions.ingest")),
    _: None = Depends(require_csrf),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    receipt = service.receive_prediction_result_batch(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        payload=payload,
    )
    return _prediction_inbox_response(receipt)


@router.post("/prediction-result-batches/validate")
def validate_prediction_result_batch(
    project_id: str,
    workspace_id: str,
    payload: dict[str, Any] = Body(...),
    principal: Principal = Depends(require_permission("predictions.ingest")),
    _: None = Depends(require_csrf),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    return receive_prediction_result_batch(
        project_id=project_id,
        workspace_id=workspace_id,
        payload=payload,
        principal=principal,
        _=_,
        identity=identity,
        service=service,
    )


@router.post("/prediction-result-batches/{batch_id}/promote")
def promote_prediction_result_batch(
    project_id: str,
    workspace_id: str,
    batch_id: str,
    principal: Principal = Depends(require_permission("predictions.ingest")),
    _: None = Depends(require_csrf),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    try:
        return service.promote_prediction_result_batch(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            batch_id=batch_id,
        ).model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Prediction Result Batch is not accepted or does not exist.",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error


@router.post("/replay/sessions", status_code=status.HTTP_201_CREATED)
def start_replay(
    project_id: str,
    workspace_id: str,
    payload: ReplayStartRequest,
    principal: Principal = Depends(require_permission("events.read")),
    _: None = Depends(require_csrf),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    return service.create_replay(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        user_id=principal.user_id,
        dataset_version_id=selected_dataset_version(
            service=service,
            principal=principal,
            project_id=project_id,
            workspace_id=workspace_id,
            requested=payload.dataset_version_id,
        ),
        start_time=payload.start_time,
        speed=payload.speed_minutes_per_second,
    ).model_dump(mode="json")


@router.get("/replay/sessions/{session_id}")
def replay_snapshot(
    project_id: str,
    workspace_id: str,
    session_id: str,
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    try:
        return service.replay_snapshot(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            session_id=session_id,
        ).model_dump(mode="json")
    except KeyError as error:
        raise HTTPException(status_code=404, detail=f"replay session not found: {error.args[0]}") from error


@router.post("/replay/sessions/{session_id}/{action}")
def control_replay(
    project_id: str,
    workspace_id: str,
    session_id: str,
    action: str,
    payload: ReplayControlRequest,
    principal: Principal = Depends(require_permission("events.read")),
    _: None = Depends(require_csrf),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    if action not in {"pause", "resume", "reset", "seek", "speed"}:
        raise HTTPException(status_code=404, detail="unsupported replay action")
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    return service.control_replay(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        session_id=session_id,
        action=action,
        time_value=payload.time,
        speed=payload.speed_minutes_per_second,
    ).model_dump(mode="json")


@router.get("/replay/sessions/{session_id}/events")
async def replay_events(
    request: Request,
    project_id: str,
    workspace_id: str,
    session_id: str,
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )

    async def stream():
        last_sequence = -1
        heartbeat = 0
        while not await request.is_disconnected():
            try:
                snapshot = service.replay_snapshot(
                    organization_id=principal.organization_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    session_id=session_id,
                )
            except KeyError:
                yield "event: error\ndata: {\"code\":\"replay_session_not_found\"}\n\n"
                return
            if snapshot.cursor.sequence != last_sequence:
                last_sequence = snapshot.cursor.sequence
                payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False)
                yield f"id: {last_sequence}\nevent: replay\ndata: {payload}\n\n"
                heartbeat = 0
            else:
                heartbeat += 1
                if heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    heartbeat = 0
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@internal_router.post("/prediction-results")
def receive_internal_prediction_results(
    payload: dict[str, Any] = Body(...),
    project_id: str = Query(max_length=160),
    workspace_id: str = Query(max_length=160),
    principal: Principal = Depends(internal_prediction_ingest_principal),
    identity: IdentityService = Depends(get_identity_service),
    service: PredictiveMaintenanceRuntimeService = Depends(
        get_predictive_maintenance_runtime_service
    ),
):
    identity.require_permission(principal, "predictions.ingest")
    require_scope(
        principal=principal,
        identity=identity,
        project_id=project_id,
        workspace_id=workspace_id,
    )
    receipt = service.receive_prediction_result_batch(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        payload=payload,
    )
    if receipt.validation_status in {"accepted", "duplicate"}:
        try:
            promotion = service.promote_prediction_result_batch(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                batch_id=receipt.batch_id,
            )
        except KeyError:
            if receipt.validation_status == "duplicate":
                return _prediction_inbox_response(receipt)
            raise
        receipt = receipt.model_copy(
            update={
                "promotion_status": promotion.promotion_status,
                "product_result_created": promotion.product_result_created,
                "promoted_results": promotion.promoted_results,
                "already_promoted_results": promotion.already_promoted_results,
                "skipped_results": promotion.skipped_results,
                "product_result_ids": promotion.product_result_ids,
                "artifact_ids": promotion.artifact_ids,
            }
        )
    return _prediction_inbox_response(receipt)

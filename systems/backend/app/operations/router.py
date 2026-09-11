"""Manufacturing-compatible Event routes shared by Project showcase domain packs."""

from __future__ import annotations

import json
import uuid

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from app.common.rate_limit import RateLimitRule, RateLimiter
from app.common.runtime_settings import project_root
from app.equipment.equipment_router import register_equipment_routes

from .contracts import AgentQueryRequest, DecisionRequest, FollowUpRequest, LayoutRequest, NoteRequest, ReportRequest
from .agent_context_tool_pipeline import run_read_only_tool_pipeline
from .asset_detail_view_model import AssetDetailViewModelService, compose_asset_detail_view_model
from app.dependencies import (
    MANUFACTURING_WORKSPACE,
    get_identity_service,
    get_ontology_service,
    get_operational_decision_support_service,
    get_operational_context_repository,
    get_predictive_maintenance_runtime_service,
    get_rate_limiter,
    get_runtime_asset_detail_service,
    get_service,
    rate_limit_subject,
    require_csrf,
    require_manufacturing_scope,
    require_permission,
)
from app.diagnosis.runtime_service import PredictiveMaintenanceRuntimeService
from app.identity import AuthError, IdentityService, Principal
from app.ontology.ontology_domain import ActionInvocation
from app.ontology.projection import inspection_object_id, risk_event_object_id
from app.ontology.ontology_service import OntologyService
from .service import EventNotFound, ManufacturingPredictiveMaintenanceService
from .operational_context_contract import OperationalRequestIdentity
from .operational_planning_context import planning_context
from .operational_context_read import OperationalContextRead
from .operational_decision_brief import DecisionBriefRole
from .operational_decision_support_port import (
    DecisionSupportMaterializationInProgress,
    OperationalDecisionSupportService,
)
from .sop_retrieval import retrieve_inspection_sops

router = APIRouter(prefix="/api", tags=["manufacturing-domain-pack"])
AGENT_REVIEW_SUMMARY_MATERIALIZE_RATE = RateLimitRule(limit=12, window_seconds=60)
DECISION_SUPPORT_MATERIALIZE_RATE = RateLimitRule(limit=12, window_seconds=60)
register_equipment_routes(
    router,
    service_dependency=get_service,
    authorization_dependency=require_manufacturing_scope,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _runtime_line(asset_id: str) -> str:
    parts = asset_id.split("-")
    return "-".join(parts[1:3]) if len(parts) >= 4 else asset_id


def _runtime_operation_context(result: Any, event_id: str, *, principal: Principal, project_id: str, workspace_id: str, repository: Any = None) -> dict[str, Any]:
    identity = OperationalRequestIdentity(
        organization_id=principal.organization_id, project_id=project_id, workspace_id=workspace_id,
        asset_id=result.asset_id, evidence_snapshot_id=event_id, decision_as_of=result.observed_at,
    )
    return planning_context(repository if repository is not None else get_operational_context_repository(), identity)


def _runtime_sop_context(result: Any, operation_context: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    procedures = []
    for path in sorted((project_root() / "data" / "fixtures" / "inspection_sop").glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            procedures.append(json.load(handle))
    artifact = {
        "asset_type": result.asset_type,
        "predicted_failure_type": result.predicted_failure_type,
        "status_grade": result.status_grade,
        "top_factors": [{"feature": factor.feature} for factor in result.top_factors],
        "evidence_payload": {"component_hypotheses": []},
    }
    fixture = {
        "equipment": {
            "asset_type": result.asset_type,
            "criticality": "high" if result.status_grade in {"critical", "warning"} else "medium",
        },
        "expected": {"predicted_failure_type": result.predicted_failure_type},
        "operation_context": operation_context,
    }
    retrieval = retrieve_inspection_sops(
        fixture=fixture,
        artifact=artifact,
        procedures=procedures,
        top_k=3,
    )
    guidance = []
    for item in retrieval.get("results") or []:
        procedure = item.get("procedure") or {}
        procedure_guidance = procedure.get("guidance") or {}
        guidance.append({
            "source_type": procedure.get("source_kind"),
            "sop_id": procedure.get("sop_id"),
            "title": procedure.get("title"),
            "version": procedure.get("version"),
            "component_ids": [str(value) for value in procedure.get("component_ids") or []],
            "reference_location_label": procedure_guidance.get("reference_location_label"),
            "suggested_check_method": procedure_guidance.get("suggested_check_method"),
            "checklist_draft": procedure_guidance.get("checklist_draft") or [],
            "maintenance_review_prerequisites": procedure_guidance.get("maintenance_review_prerequisites") or {},
            "safety_level": procedure.get("safety_level"),
            "requires_human_approval": procedure.get("requires_human_approval", True),
            "source_ref": item.get("source_ref"),
            "retrieval_score": item.get("retrieval_score"),
            "matched_fields": item.get("matched_fields") or [],
            "disclaimer": procedure_guidance.get("disclaimer"),
        })
    return retrieval, guidance


def _runtime_inspection_targets(sop_guidance: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose retrieved SOP components as read-only inspection targets."""

    targets: list[dict[str, Any]] = []
    for guidance in sop_guidance:
        source_ref = str(guidance.get("source_ref") or guidance.get("sop_id") or "")
        component_ids = [str(value) for value in guidance.get("component_ids") or [] if value]
        for component_id in component_ids:
            targets.append({
                "target_id": f"runtime-sop:{component_id}",
                "component_id": component_id,
                "component_label": component_id.replace("_", " "),
                "association": "sop_retrieved_inspection_candidate",
                "location_label": guidance.get("reference_location_label"),
                "inspection_method": guidance.get("suggested_check_method"),
                "location_source_ref": source_ref or None,
                "basis_refs": [source_ref] if source_ref else [],
                "source_ref": source_ref or f"runtime-sop:{component_id}",
                "unavailable_reason": None,
            })
    return targets


def _packet_title(packet: dict[str, Any]) -> str:
    identity = packet.get("asset_identity") or {}
    return str(
        identity.get("asset_name")
        or identity.get("asset_id")
        or packet.get("asset_label")
        or packet.get("asset_id")
        or "selected asset"
    )


def _packet_asset_id(packet: dict[str, Any]) -> str | None:
    identity = packet.get("asset_identity") or {}
    value = identity.get("asset_id") or packet.get("asset_id")
    return str(value) if value else None


def _packet_dataset_version(packet: dict[str, Any]) -> str | None:
    basis = packet.get("snapshot_basis") or {}
    value = packet.get("dataset_version_id") or basis.get("dataset_version_id") or basis.get("dataset_version")
    return str(value) if value else None


def _packet_evidence(
    packet: dict[str, Any],
    *,
    service: ManufacturingPredictiveMaintenanceService,
    project_id: str,
    workspace_id: str,
    question: str = "",
    top_k: int,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    model_context = packet.get("model_expression_context") or {}
    for index, factor in enumerate((model_context.get("top_factors") or [])[:top_k], start=1):
        if not isinstance(factor, dict):
            continue
        feature = str(factor.get("display_name") or factor.get("feature") or f"factor {index}")
        raw_value = factor.get("value")
        unit = factor.get("unit")
        value = f"{raw_value}{(' ' + str(unit)) if unit else ''}" if raw_value is not None else "value unavailable"
        evidence.append({
            "evidence_id": f"packet-factor-{index}",
            "store": "postgresql",
            "reference": str(factor.get("feature") or feature),
            "project_id": project_id,
            "workspace_id": workspace_id,
            "dataset_version_id": _packet_dataset_version(packet),
            "object_id": _packet_asset_id(packet),
            "title": feature,
            "content": f"{feature}: {value}",
            "score": _coerce_float(factor.get("contribution") or factor.get("importance")),
            "metadata": {key: value for key, value in factor.items() if key not in {"display_name", "feature", "value", "unit"}},
        })

    sop_items = []
    sop_retrieval = packet.get("sop_retrieval") or {}
    for key in ("items", "results", "documents"):
        items = sop_retrieval.get(key)
        if isinstance(items, list):
            sop_items = items
            break
    if not sop_items and isinstance(packet.get("sop_guidance"), list):
        sop_items = packet.get("sop_guidance") or []
    for index, item in enumerate(sop_items[: max(0, top_k - len(evidence))], start=1):
        if not isinstance(item, dict):
            continue
        procedure = item.get("procedure") if isinstance(item.get("procedure"), dict) else {}
        guidance = procedure.get("guidance") if isinstance(procedure.get("guidance"), dict) else {}
        title = str(
            item.get("title")
            or procedure.get("title")
            or item.get("component")
            or f"SOP guidance {index}"
        )
        content = str(
            item.get("summary")
            or item.get("content")
            or item.get("guidance")
            or guidance.get("suggested_check_method")
            or title
        )
        evidence.append({
            "evidence_id": f"packet-sop-{index}",
            "store": "project3_rag",
            "reference": str(
                item.get("source_ref")
                or item.get("source")
                or procedure.get("source_uri")
                or item.get("id")
                or title
            ),
            "project_id": project_id,
            "workspace_id": workspace_id,
            "dataset_version_id": _packet_dataset_version(packet),
            "object_id": _packet_asset_id(packet),
            "title": title,
            "content": content,
            "score": _coerce_float(item.get("score") or item.get("retrieval_score")),
            "metadata": item,
        })
    asset_id = _packet_asset_id(packet)
    remaining = max(0, top_k - len(evidence))
    if remaining:
        for index, item in enumerate(
            service.company_context_documents(
                question,
                project_id=project_id,
                workspace_id=workspace_id,
                asset_id=asset_id,
                top_k=remaining,
            ),
            start=1,
        ):
            evidence.append({
                "evidence_id": f"company-context-{index}",
                "store": "company_context",
                "reference": str(item.get("source_ref") or item.get("id") or f"company-context-{index}"),
                "project_id": project_id,
                "workspace_id": workspace_id,
                "dataset_version_id": _packet_dataset_version(packet),
                "object_id": asset_id,
                "title": str(item.get("title") or "Company context"),
                "content": str(item.get("content") or item.get("title") or ""),
                "score": _coerce_float(item.get("retrieval_score")),
                "metadata": {
                    "document_type": item.get("document_type"),
                    "related_asset_ids": item.get("related_asset_ids") or [],
                    "context_kind": item.get("context_kind"),
                },
            })
    return evidence[:top_k]


def _summary_text(summary: dict[str, Any] | None, audience: str | None = None) -> str | None:
    if not isinstance(summary, dict):
        return None
    if audience == "executive" and summary.get("summary"):
        return str(summary["summary"])
    role_summaries = summary.get("role_summaries") or []
    if isinstance(role_summaries, list):
        target_role = (
            "process_manager"
            if audience == "operations"
            else "process_engineer"
            if audience == "engineering"
            else "maintenance_technician"
            if audience == "maintenance"
            else None
        )
        if target_role:
            for item in role_summaries:
                if (
                    isinstance(item, dict)
                    and item.get("role") == target_role
                    and item.get("quote")
                ):
                    return str(item["quote"])
        if summary.get("summary"):
            return str(summary["summary"])
        for item in role_summaries:
            if isinstance(item, dict) and item.get("quote"):
                return str(item["quote"])
    if summary.get("summary"):
        return str(summary["summary"])
    return None


def _answer_from_packet(
    question: str,
    packet: dict[str, Any],
    evidence: list[dict[str, Any]],
    summary: dict[str, Any] | None,
    audience: str | None = None,
) -> str:
    title = _packet_title(packet)
    risk_summary = packet.get("risk_summary") or {}
    probability = risk_summary.get("failure_probability") or risk_summary.get("probability")
    status = risk_summary.get("status_grade") or risk_summary.get("status")
    risk = f"{round(float(probability) * 100)}%" if isinstance(probability, (int, float)) else "위험도 미제공"
    reasons = (packet.get("review_priority") or {}).get("reasons") or []
    reason_text = " · ".join(str(item) for item in reasons[:4] if item)
    summary_text = _summary_text(summary, audience)
    evidence_text = " · ".join(item["content"] for item in evidence[:4])
    lower = question.lower()
    if summary_text:
        if audience == "executive":
            operation_context = packet.get("operation_context_summary") or {}
            downtime = operation_context.get("estimated_downtime_minutes")
            lost_units = operation_context.get("estimated_lost_units")
            production_impact = operation_context.get("production_impact")
            impact_parts = [
                f"생산 영향 {production_impact}" if production_impact else None,
                f"예상 정지 {int(downtime)}분" if isinstance(downtime, (int, float)) else None,
                f"계획 영향 약 {int(lost_units)}개" if isinstance(lost_units, (int, float)) else None,
            ]
            impact_text = " · ".join(item for item in impact_parts if item)
            return (
                f"{title}: {summary_text}"
                f"{f' 경영 영향: {impact_text}.' if impact_text else ''} "
                f"근거: {evidence_text or reason_text or '근거 미제공'}"
            )
        return f"{title}: {summary_text} 연결 근거: {evidence_text or reason_text or '근거 미제공'}"
    if any(token in lower for token in ("우선", "priority", "prioritized", "why")):
        return f"{title}는 현재 {status or '상태 미제공'} / {risk}로 검토 우선순위에 올라 있습니다. 핵심 근거는 {reason_text or evidence_text or '현재 연결된 정본 근거 없음'}입니다. 이는 고장 확정이 아니라 운영 검토 우선순위입니다."
    if any(token in lower for token in ("근거", "evidence", "factor", "요인")):
        return f"{title}의 현재 연결 근거는 {evidence_text or reason_text or '제공되지 않았습니다'}입니다."
    return f"{title}에 대한 답변입니다. 현재 상태는 {status or '미제공'}, 위험도는 {risk}이며, 연결 근거는 {evidence_text or reason_text or '제공되지 않았습니다'}입니다."


def _runtime_event_id(result: Any) -> str:
    return str(getattr(result, "artifact_id", None) or result.provenance.prediction_id)


def _runtime_factor_source_ref(event_id: str, feature: str, rank: int) -> str:
    safe_feature = feature or f"factor-{rank}"
    return f"result-artifact:{event_id}#factor:{safe_feature}"


_RUNTIME_HISTORY_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}


def _runtime_feature_and_risk_history(
    *,
    runtime_service: PredictiveMaintenanceRuntimeService,
    principal: Principal,
    project_id: str,
    workspace_id: str,
    dataset_version_id: str,
    asset_id: str,
    observed_at: datetime,
    history_window: str,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Read bounded runtime history through the Diagnosis service contracts."""

    hours = _RUNTIME_HISTORY_HOURS.get(history_window)
    if hours is None:
        raise ValueError(f"unsupported runtime history window: {history_window}")
    start = observed_at - timedelta(hours=hours)
    grain = "1h" if history_window == "30d" else "10m"
    observation_response = runtime_service.observations(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=dataset_version_id,
        start=start,
        end=observed_at,
        asset_id=asset_id,
        site_id=None,
        cell_id=None,
        asset_type=None,
        grain=grain,
        derived_measures=set(),
        limit=5000,
    )
    feature_series: dict[str, dict[str, Any]] = {}
    for observation in observation_response.observations:
        values = {**observation.measurements, **observation.derived_measures}
        for feature, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            series = feature_series.setdefault(
                str(feature),
                {
                    "source_ref": f"runtime-observation:{dataset_version_id}:{asset_id}:{feature}",
                    "points": [],
                },
            )
            series["points"].append(
                {
                    "observed_at": observation.observed_at.isoformat(),
                    "value": float(value),
                    "quality_status": "good",
                }
            )

    timeline_response = runtime_service.timeline(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=dataset_version_id,
        asset_id=asset_id,
        start=start,
        end=observed_at,
        offset=0,
        limit=5000,
    )
    risk_history = [
        {
            "observed_at": str(item["observed_at"]),
            "failure_probability": item["failure_probability"],
            "status_grade": item["status"],
            "prediction_id": item["prediction_id"],
            "source_kind": item["source_type"],
            "source_ref": f"result-artifact:{item['prediction_id']}",
        }
        for item in timeline_response.get("items", [])
    ]
    return feature_series, risk_history


def _runtime_agent_review_packet(
    *,
    asset_id: str,
    project_id: str,
    workspace_id: str,
    dataset_version_id: str | None,
    selected_event_id: str | None = None,
    principal: Principal,
    runtime_service: PredictiveMaintenanceRuntimeService,
    context_service: ManufacturingPredictiveMaintenanceService | None = None,
) -> dict[str, Any]:
    page = runtime_service.latest_results(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=dataset_version_id,
        asset_id=asset_id,
        limit=1,
    )
    if not page.items:
        raise EventNotFound(asset_id)

    result = page.items[0]
    event_id = _runtime_event_id(result)
    if selected_event_id and event_id != selected_event_id:
        raise EventNotFound(selected_event_id)
    from .agent_review_packet import compose_agent_review_packet
    view_model = _runtime_asset_detail_view_model(
        asset_id=asset_id, project_id=project_id, workspace_id=workspace_id,
        dataset_version_id=dataset_version_id, selected_event_id=event_id,
        history_window="24h", principal=principal, runtime_service=runtime_service,
        context_service=context_service,
    )
    from .factory_records import read_records
    records = read_records(
        (context_service or get_service()).operational_context_repository,
        identity=OperationalRequestIdentity(organization_id=principal.organization_id,
            project_id=project_id,workspace_id=workspace_id,asset_id=asset_id,
            evidence_snapshot_id=event_id,decision_as_of=result.observed_at),
        dataset_version_id=page.context.dataset_version_id,
        model_version=result.provenance.model_version,asset_ids=[asset_id])
    if records.get("status")=="available" and records.get("similar_events_30d") is not None:
        view_model["maintenance_context"]["similar_events_30d"]=records["similar_events_30d"]
        view_model["evidence"]["gaps"]=[g for g in view_model["evidence"]["gaps"] if g["field"]!="maintenance_context.similar_events_30d"]
    sop_retrieval, _ = _runtime_sop_context(result, view_model["operation_context"])
    packet = compose_agent_review_packet(
        project_id=project_id, view_model=view_model, sop_retrieval=sop_retrieval,
    )
    if records.get("status")=="available":
        ref=records["provenance"]["source_ref"]
        packet["source_refs"].append(ref)
        packet["maintenance_history_summary"]["source_refs"].append(ref)
        packet["limitations"].append(f"운영 조치 검토 기준 {records['policy']['action_threshold']:.2f}, 정책 {records['policy']['version']}. 기존 위험 등급과 작업 권한은 변경하지 않음. 출처 {ref}")
    # Use the same scoped read as the shared side view; absence is not readiness.
    context_read = (context_service or get_service()).operational_context_repository.read_view(
        identity=OperationalRequestIdentity(organization_id=principal.organization_id,
            project_id=project_id, workspace_id=workspace_id, asset_id=asset_id,
            evidence_snapshot_id=event_id, decision_as_of=result.observed_at),
        retrieved_at=datetime.now(timezone.utc), risk_status=result.status_grade)
    from .context_record_brief import record_limitations
    packet["limitations"].extend(record_limitations(context_read.model_dump(mode="json")))
    for item in context_read.domains.values():
        packet["source_refs"].extend(ref for ref in item.context.source_refs if ref not in packet["source_refs"])
    return packet


def _runtime_asset_detail_view_model(
    *,
    asset_id: str,
    project_id: str,
    workspace_id: str,
    dataset_version_id: str | None,
    selected_event_id: str | None = None,
    history_window: str,
    principal: Principal,
    runtime_service: PredictiveMaintenanceRuntimeService,
    context_service: ManufacturingPredictiveMaintenanceService | None = None,
) -> dict[str, Any]:
    page = runtime_service.latest_results(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=dataset_version_id,
        asset_id=asset_id,
        limit=1,
    )
    if not page.items:
        raise EventNotFound(asset_id)
    result = page.items[0]
    event_id = _runtime_event_id(result)
    if selected_event_id and event_id != selected_event_id:
        raise EventNotFound(selected_event_id)
    observed_at = result.observed_at.isoformat()
    artifact = result.producer_artifact
    if artifact is None:
        sensors = {
            factor.feature: {
                "display_name": factor.feature.replace("_", " "),
                "current": factor.feature_value,
                "unit": "model unit",
                "basis": {},
            }
            for factor in result.top_factors
        }
        artifact = {
            "artifact_id": event_id,
            "asset_id": result.asset_id,
            "asset_type": result.asset_type,
            "observed_at": observed_at,
            "prediction_horizon_hours": result.prediction_horizon_hours,
            "failure_probability": result.failure_probability,
            "predicted_failure_type": result.predicted_failure_type,
            "status_grade": result.status_grade,
            "confidence": result.confidence,
            "top_factors": [
                {
                    "rank": factor.rank,
                    "feature": factor.feature,
                    "feature_value": factor.feature_value,
                    "signed_contribution": factor.signed_contribution,
                    "direction": factor.direction,
                    "explanation_method": factor.explanation_method,
                }
                for factor in result.top_factors
            ],
            "ranked_factor_evidence": [
                {
                    "evidence_field_id": f"factor:{factor.feature}",
                    "feature": factor.feature,
                    "display_name": factor.feature.replace("_", " "),
                    "value": factor.feature_value,
                    "unit": "model unit",
                }
                for factor in result.top_factors
            ],
            "evidence_payload": {
                "sensor_evidence": {"sensors": sensors},
                "evidence_gaps": [],
            },
            "provenance": {
                "dataset_id": page.context.dataset_id,
                "dataset_version": page.context.dataset_version_id,
                "model_version": result.provenance.model_version,
                "result_schema": result.provenance.schema_version,
                "prediction_task": result.provenance.prediction_task,
                "prediction_id": result.provenance.prediction_id,
                "prediction_result_id": result.provenance.prediction_result_id,
                "source_sha256": result.provenance.result_artifact_source_sha256,
                "evidence_payload_reference": f"result-artifact:{event_id}#evidence_payload",
                "source_type": "product_runtime_inference",
                "artifact_id": event_id,
            },
        }
    criticality = "high" if result.status_grade in {"critical", "warning"} else "medium" if result.status_grade == "attention" else "low"
    context_repository = (context_service.operational_context_repository if context_service else get_operational_context_repository()).capture(
        OperationalRequestIdentity(organization_id=principal.organization_id, project_id=project_id,
            workspace_id=workspace_id, asset_id=asset_id, evidence_snapshot_id=event_id,
            decision_as_of=result.observed_at)
    )
    operation_context = _runtime_operation_context(result, event_id, principal=principal, project_id=project_id, workspace_id=workspace_id, repository=context_repository)
    _, sop_guidance = _runtime_sop_context(result, operation_context)
    inspection_guidance: dict[str, dict[str, Any]] = {}
    if sop_guidance:
        artifact = dict(artifact)
        evidence_payload = dict(artifact.get("evidence_payload") or {})
        component_hypotheses = list(evidence_payload.get("component_hypotheses") or [])
        if not component_hypotheses:
            for guidance in sop_guidance:
                component_ids = guidance.get("component_ids") or []
                if not component_ids:
                    continue
                component_id = str(component_ids[0])
                component_hypotheses.append({
                    "component_id": component_id,
                    "component_label": component_id.replace("_", " "),
                    "association": "sop_retrieved_inspection_candidate",
                    "basis": [str(guidance.get("source_ref") or guidance.get("sop_id") or "")],
                })
                inspection_guidance[component_id] = guidance
        else:
            for hypothesis in component_hypotheses:
                component_id = str(hypothesis.get("component_id") or "") if isinstance(hypothesis, dict) else ""
                if not component_id:
                    continue
                matching = next((item for item in sop_guidance if component_id in (item.get("component_ids") or [])), None)
                if matching:
                    inspection_guidance[component_id] = matching
        evidence_payload["component_hypotheses"] = component_hypotheses
        artifact["evidence_payload"] = evidence_payload
    asset = {
        "asset_id": result.asset_id,
        "asset_type": result.asset_type,
        "display_name": f"{result.asset_type.upper()} · {result.asset_id}",
        "site_id": result.site_id,
        "cell_id": result.cell_id,
        "observed_at": observed_at,
        "criticality": criticality,
        "criticality_basis": ["runtime result status grade"],
        "criticality_source": "project_context",
        "operation_context": operation_context,
        "maintenance_context": {
            "last_maintenance_days_ago": None,
            "similar_events_30d": None,
            "open_work_order_exists": None,
        },
    }
    maintenance_history = []
    maintenance_warnings = []
    try:
        from .runtime_maintenance_read import read_runtime_maintenance
        asset["maintenance_context"], maintenance_history = read_runtime_maintenance(
            (context_service or get_service()).operational_context_repository,
            organization_id=principal.organization_id, project_id=project_id,
            workspace_id=workspace_id, dataset_version_id=page.context.dataset_version_id,
            asset_id=asset_id, observed_at=result.observed_at,
        )
    except Exception:
        maintenance_warnings.append("정비 기록 조회 실패 · 정비 현황은 미확인으로 유지합니다.")
    feature_series, runtime_prediction_history = _runtime_feature_and_risk_history(
        runtime_service=runtime_service,
        principal=principal,
        project_id=project_id,
        workspace_id=workspace_id,
        dataset_version_id=page.context.dataset_version_id,
        asset_id=asset_id,
        observed_at=result.observed_at,
        history_window=history_window,
    )
    if not runtime_prediction_history:
        runtime_prediction_history = [
            {
                "observed_at": observed_at,
                "failure_probability": result.failure_probability,
                "status_grade": result.status_grade,
                "prediction_id": result.provenance.prediction_id,
                "source_kind": "runtime_inference",
                "source_ref": f"result-artifact:{event_id}",
            }
        ]
    view = compose_asset_detail_view_model(
        asset=asset,
        result_artifact=artifact,
        feature_series=feature_series,
        runtime_prediction_history=runtime_prediction_history,
        equipment_history=maintenance_history,
        operation_context=asset["operation_context"],
        evidence_context=(context_service or get_service()).evidence_context_for_snapshot(
            asset_id=asset_id,
            artifact={"artifact_id": event_id, "observed_at": observed_at},
            project_id=project_id,
            event_id=event_id,
            organization_id=principal.organization_id,
            workspace_id=workspace_id,
            context_repository=context_repository,
        ),
        inspection_guidance=inspection_guidance,
        data_status={
            "source": "canonical-runtime",
            "last_updated_at": observed_at,
            "is_stale": None,
            "warnings": maintenance_warnings,
        },
        history_window=history_window,
        event_id=event_id,
    )

    from .signal_unit_policy import apply_signal_units
    return apply_signal_units(view, organization_id=principal.organization_id,
                              project_id=project_id, workspace_id=workspace_id)


def _merge_runtime_detail_supplemental(
    canonical: dict[str, Any],
    supplemental: dict[str, Any],
) -> dict[str, Any]:
    """Add presentation context without replacing canonical evidence facts."""

    merged = dict(canonical)
    merged["operation_context"] = supplemental.get("operation_context")
    merged["evidence_context"] = supplemental.get("evidence_context")
    supplemental_features = {
        str(feature.get("key") or ""): feature
        for feature in supplemental.get("features") or []
        if isinstance(feature, dict) and feature.get("key")
    }
    if supplemental_features:
        merged_features: list[dict[str, Any]] = []
        seen_feature_keys: set[str] = set()
        for feature in merged.get("features") or []:
            if not isinstance(feature, dict):
                continue
            key = str(feature.get("key") or "")
            seen_feature_keys.add(key)
            supplemental_feature = supplemental_features.get(key)
            canonical_history = (feature.get("history") or {}) if isinstance(feature.get("history"), dict) else {}
            supplemental_history = (
                supplemental_feature.get("history") or {}
                if isinstance(supplemental_feature, dict) and isinstance(supplemental_feature.get("history"), dict)
                else {}
            )
            canonical_points = canonical_history.get("points") or []
            supplemental_points = supplemental_history.get("points") or []
            if len(supplemental_points) > len(canonical_points):
                merged_features.append({**feature, "history": supplemental_history})
            else:
                merged_features.append(feature)
        for key, supplemental_feature in supplemental_features.items():
            if key not in seen_feature_keys:
                merged_features.append(supplemental_feature)
        if merged_features:
            merged["features"] = merged_features
    supplemental_risk_series = supplemental.get("risk_series") or []
    canonical_risk_series = merged.get("risk_series") or []
    if len(supplemental_risk_series) > len(canonical_risk_series):
        merged["risk_series"] = supplemental_risk_series
    if not merged.get("inspection_targets") and supplemental.get("inspection_targets"):
        merged["inspection_targets"] = supplemental["inspection_targets"]
    if not merged.get("review_priority") and supplemental.get("review_priority"):
        merged["review_priority"] = supplemental["review_priority"]
    evidence = dict(merged.get("evidence") or {})
    gaps = [
        gap
        for gap in evidence.get("gaps") or []
        if not str((gap or {}).get("field") or "").startswith("operation_context")
        and str((gap or {}).get("field") or "") != "review_priority"
    ]
    gaps.extend(
        gap for gap in (supplemental.get("evidence") or {}).get("gaps", [])
        if str((gap or {}).get("field") or "").startswith("operation_context")
    )
    evidence["gaps"] = gaps
    merged["evidence"] = evidence
    return merged


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


@router.get("/projects/{project_id}/company-context")
def get_company_context(
    project_id: str,
    workspace_id: str = Query(default=MANUFACTURING_WORKSPACE, max_length=160),
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 회사 문맥입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 Project를 활성화해야 합니다.")
    if not principal.is_admin and workspace_id not in principal.workspace_scopes:
        raise AuthError(403, "workspace_scope_denied", "허용된 Workspace 범위를 벗어난 회사 문맥입니다.")
    return {
        "project_id": project_id,
        "workspace_id": workspace_id,
        **service.company_context(project_id=project_id, workspace_id=workspace_id),
    }


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
    runtime_detail: AssetDetailViewModelService | None = Depends(get_runtime_asset_detail_service),
):
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 Object입니다.")
    if not principal.is_admin and workspace_id not in principal.workspace_scopes:
        raise AuthError(403, "workspace_scope_denied", "허용된 Workspace 범위를 벗어난 Object입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 Object가 속한 Project를 활성화해야 합니다.")
    if dataset_version_id and event_id and runtime_detail is not None:
        try:
            canonical = runtime_detail.latest_detail_view(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                asset_id=asset_id,
                dataset_version_id=dataset_version_id,
                event_id=event_id,
                history_window=history_window,
            )
            try:
                supplemental = _runtime_asset_detail_view_model(
                    asset_id=asset_id,
                    project_id=project_id,
                    workspace_id=workspace_id,
                    dataset_version_id=dataset_version_id,
                    selected_event_id=event_id,
                    history_window=history_window,
                    principal=principal,
                    runtime_service=get_predictive_maintenance_runtime_service(),
                    context_service=service,
                )
                return _merge_runtime_detail_supplemental(canonical, supplemental)
            except Exception:
                return canonical
        except KeyError:
            # Canonical prediction-only rows use the normalized runtime path;
            # that path independently checks the exact selected event identity.
            pass
    if event_id:
        try:
            return _runtime_asset_detail_view_model(
                asset_id=asset_id,
                project_id=project_id,
                workspace_id=workspace_id,
                dataset_version_id=dataset_version_id,
                selected_event_id=event_id,
                history_window=history_window,
                principal=principal,
                runtime_service=get_predictive_maintenance_runtime_service(),
                context_service=service,
            )
        except EventNotFound:
            pass
    try:
        return service.asset_detail_view_model(
            asset_id,
            project_id,
            dataset_version_id=dataset_version_id,
            history_window=history_window,
        )
    except EventNotFound:
        return _runtime_asset_detail_view_model(
            asset_id=asset_id,
            project_id=project_id,
            workspace_id=workspace_id,
            dataset_version_id=dataset_version_id,
            selected_event_id=event_id,
            history_window=history_window,
            principal=principal,
            runtime_service=get_predictive_maintenance_runtime_service(),
            context_service=service,
        )


def _selected_agent_review_packet(
    *, service: ManufacturingPredictiveMaintenanceService, principal: Principal,
    asset_id: str, project_id: str, dataset_version_id: str | None,
    event_id: str, history_window: str,
) -> dict[str, Any]:
    if event_id.startswith("FILE#"):
        from .filesystem_briefing import BriefingHistoryUnavailable, filesystem_briefing_packet
        try:
            return filesystem_briefing_packet(asset_id=asset_id, event_id=event_id,
                dataset_version_id=dataset_version_id, project_id=project_id, history_window=history_window,
                service=service, organization_id=principal.organization_id, workspace_id=MANUFACTURING_WORKSPACE)
        except KeyError:
            raise EventNotFound(event_id)
        except BriefingHistoryUnavailable as exc:
            raise HTTPException(status_code=503, detail={
                "code": "briefing_history_unavailable",
                "message": str(exc),
            }) from exc
    try:
        return service.runtime_agent_review_packet(
            asset_id, project_id, organization_id=principal.organization_id,
            workspace_id=MANUFACTURING_WORKSPACE,
            dataset_version_id=dataset_version_id, event_id=event_id,
            history_window=history_window,
        )
    except (KeyError, RuntimeError):
        try:
            return _runtime_agent_review_packet(
                asset_id=asset_id, project_id=project_id,
                workspace_id=MANUFACTURING_WORKSPACE,
                dataset_version_id=dataset_version_id, selected_event_id=event_id,
                principal=principal, runtime_service=get_predictive_maintenance_runtime_service(),
                context_service=service,
            )
        except (KeyError, EventNotFound):
            packet = service.agent_review_packet(
                asset_id, project_id, dataset_version_id=dataset_version_id,
                history_window=history_window,
            )
            basis = packet.get("snapshot_basis") or {}
            if event_id not in (basis.get("event_id"), basis.get("artifact_id")):
                raise EventNotFound(event_id)
            return packet


@router.get("/objects/{asset_id}/agent-review-packet")
def get_agent_review_packet(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    dataset_version_id: str | None = Query(default=None, max_length=160),
    event_id: str | None = Query(default=None, max_length=240),
    history_window: Literal["24h", "7d", "30d"] = Query(default="24h"),
    expected_summary_key: str | None = Query(default=None, min_length=1, max_length=240),
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    _authorize_agent_review_summary(principal=principal, project_id=project_id)
    if event_id:
        packet = _selected_agent_review_packet(
            service=service, principal=principal, asset_id=asset_id,
            project_id=project_id, dataset_version_id=dataset_version_id,
            event_id=event_id, history_window=history_window,
        )
    else:
        try:
            packet = service.agent_review_packet(
                asset_id, project_id, dataset_version_id=dataset_version_id,
                history_window=history_window,
            )
        except EventNotFound:
            packet = _runtime_agent_review_packet(
                asset_id=asset_id, project_id=project_id,
                workspace_id=MANUFACTURING_WORKSPACE,
                dataset_version_id=dataset_version_id, principal=principal,
                runtime_service=get_predictive_maintenance_runtime_service(),
                context_service=service,
            )
    if expected_summary_key is not None:
        from .agent_review_summary_materialization import summary_key, summary_key_payload
        actual_key = summary_key(summary_key_payload(
            packet=packet, organization_id=principal.organization_id,
            project_id=project_id, workspace_id=MANUFACTURING_WORKSPACE,
            history_window=history_window, provider=service.agent_review_summary_provider,
        ))
        if actual_key != expected_summary_key:
            raise HTTPException(status_code=409, detail={
                "code": "briefing_evidence_changed",
                "message": "브리핑 작성 이후 근거가 변경되었습니다. 현재 브리핑을 다시 조회하세요.",
            })
    return packet


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
    event_id: str | None = Query(default=None, max_length=240),
    history_window: Literal["24h", "7d", "30d"] = Query(default="24h"),
    principal: Principal = Depends(require_permission("events.read")),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    _authorize_agent_review_summary(principal=principal, project_id=project_id)
    if event_id:
        try:
            packet = _selected_agent_review_packet(
                service=service, principal=principal, asset_id=asset_id,
                project_id=project_id, dataset_version_id=dataset_version_id,
                event_id=event_id, history_window=history_window,
            )
            summary, trace = service.cached_agent_review_summary_for_packet(
                packet=packet,
                project_id=project_id,
                organization_id=principal.organization_id,
                workspace_id=MANUFACTURING_WORKSPACE,
                history_window=history_window,
            )
            return JSONResponse(
                status_code=200 if summary is not None else 202,
                content={
                    "summary": summary,
                    "trace": trace,
                },
            )
        except EventNotFound:
            raise
    try:
        summary, trace = service.cached_agent_review_summary(
            asset_id,
            project_id,
            organization_id=principal.organization_id,
            workspace_id=MANUFACTURING_WORKSPACE,
            dataset_version_id=dataset_version_id,
            history_window=history_window,
        )
    except EventNotFound:
        packet = _runtime_agent_review_packet(
            asset_id=asset_id,
            project_id=project_id,
            workspace_id=MANUFACTURING_WORKSPACE,
            dataset_version_id=dataset_version_id,
            principal=principal,
            runtime_service=get_predictive_maintenance_runtime_service(),
            context_service=service,
        )
        summary, trace = service.cached_agent_review_summary_for_packet(
            packet=packet, project_id=project_id,
            organization_id=principal.organization_id,
            workspace_id=MANUFACTURING_WORKSPACE, history_window=history_window,
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
    event_id: str | None = Query(default=None, max_length=240),
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
            event_id or "no-event",
            history_window,
            trigger,
        ),
        rule=AGENT_REVIEW_SUMMARY_MATERIALIZE_RATE,
    )
    if event_id:
        try:
            packet = _selected_agent_review_packet(
                service=service, principal=principal, asset_id=asset_id,
                project_id=project_id, dataset_version_id=dataset_version_id,
                event_id=event_id, history_window=history_window,
            )
            summary, trace = service._materialize_agent_review_packet(
                packet=packet, project_id=project_id,
                organization_id=principal.organization_id,
                workspace_id=MANUFACTURING_WORKSPACE,
                history_window=history_window, trigger=trigger, engine="simple",
            )
            return {"summary": summary, "trace": trace}
        except EventNotFound:
            raise
    try:
        summary, trace = service.agent_review_summary(
            asset_id,
            project_id,
            organization_id=principal.organization_id,
            workspace_id=MANUFACTURING_WORKSPACE,
            dataset_version_id=dataset_version_id,
            history_window=history_window,
            trigger=trigger,
        )
    except EventNotFound:
        packet = _runtime_agent_review_packet(
            asset_id=asset_id,
            project_id=project_id,
            workspace_id=MANUFACTURING_WORKSPACE,
            dataset_version_id=dataset_version_id,
            principal=principal,
            runtime_service=get_predictive_maintenance_runtime_service(),
            context_service=service,
        )
        summary, trace = service._materialize_agent_review_packet(
            packet=packet, project_id=project_id,
            organization_id=principal.organization_id,
            workspace_id=MANUFACTURING_WORKSPACE,
            history_window=history_window, trigger=trigger, engine="simple",
        )
    return {"summary": summary, "trace": trace}


def _decision_support_identity(
    *,
    principal: Principal,
    project_id: str,
    workspace_id: str,
    asset_id: str,
    evidence_snapshot_id: str,
    decision_as_of: datetime,
) -> OperationalRequestIdentity:
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 판단 지원 요청입니다.")
    if not principal.is_admin and workspace_id not in principal.workspace_scopes:
        raise AuthError(403, "workspace_scope_denied", "허용된 Workspace 범위를 벗어난 판단 지원 요청입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 요청 Project를 활성화해야 합니다.")
    if decision_as_of.tzinfo is None or decision_as_of.utcoffset() is None:
        raise HTTPException(status_code=422, detail="decision_as_of must include timezone")
    if decision_as_of > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="decision_as_of cannot be in the future")
    return OperationalRequestIdentity(
        organization_id=principal.organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        asset_id=asset_id,
        evidence_snapshot_id=evidence_snapshot_id,
        decision_as_of=decision_as_of,
    )


def _trusted_decision_support_risk(
    identity: OperationalRequestIdentity,
    service: ManufacturingPredictiveMaintenanceService,
) -> str:
    """Resolve the actual packet before accepting a brief identity or risk."""
    try:
        packet = service.runtime_agent_review_packet(
            identity.asset_id, identity.project_id,
            organization_id=identity.organization_id,
            workspace_id=identity.workspace_id,
            dataset_version_id=None,
            event_id=identity.evidence_snapshot_id,
        )
    except (KeyError, RuntimeError):
        # Canonical prediction-contract rows use the same runtime index as detail-view.
        # They are not producer Artifacts and must not be coerced into that contract.
        try:
            page = get_predictive_maintenance_runtime_service().latest_results(
                organization_id=identity.organization_id, project_id=identity.project_id,
                workspace_id=identity.workspace_id, asset_id=identity.asset_id, dataset_version_id=None, limit=1,
            )
        except (KeyError, RuntimeError):
            page = None
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            page = None  # Exact fixture identity validation below remains mandatory.
        if page is not None and page.items:
            result = page.items[0]
            if _runtime_event_id(result) != identity.evidence_snapshot_id or result.asset_id != identity.asset_id:
                raise HTTPException(status_code=409, detail="evidence_snapshot_mismatch")
            if result.observed_at > identity.decision_as_of:
                raise HTTPException(status_code=409, detail="evidence_snapshot_as_of_mismatch")
            return str(result.status_grade)
        # Fixture fallback is usable only for its exact immutable identity and workspace.
        if identity.workspace_id != MANUFACTURING_WORKSPACE:
            raise HTTPException(status_code=409, detail="evidence_snapshot_unavailable")
        packet = service.agent_review_packet(identity.asset_id, identity.project_id)
    basis = packet.get('snapshot_basis') or {}
    if packet.get('asset_id') != identity.asset_id or basis.get('artifact_id') != identity.evidence_snapshot_id:
        raise HTTPException(status_code=409, detail="evidence_snapshot_mismatch")
    observed_at = datetime.fromisoformat(str(basis.get('observed_at')))
    if observed_at.tzinfo is None or observed_at > identity.decision_as_of:
        raise HTTPException(status_code=409, detail="evidence_snapshot_as_of_mismatch")
    return str((packet.get('risk_summary') or {}).get('status_grade') or 'data_quality_hold')


@router.get("/objects/{asset_id}/operational-context")
def get_operational_context(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    workspace_id: str = Query(default=MANUFACTURING_WORKSPACE, max_length=160),
    evidence_snapshot_id: str = Query(min_length=1, max_length=240),
    decision_as_of: datetime = Query(),
    principal: Principal = Depends(require_permission("events.read")),
    repository: Any = Depends(get_operational_context_repository),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
) -> OperationalContextRead:
    identity = _decision_support_identity(
        principal=principal, project_id=project_id, workspace_id=workspace_id,
        asset_id=asset_id, evidence_snapshot_id=evidence_snapshot_id, decision_as_of=decision_as_of,
    )
    risk = _trusted_decision_support_risk(identity, service)
    return repository.read_view(identity=identity, retrieved_at=datetime.now(timezone.utc), risk_status=risk)


@router.get("/objects/{asset_id}/decision-support-brief")
def get_decision_support_brief(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    workspace_id: str = Query(default=MANUFACTURING_WORKSPACE, max_length=160),
    evidence_snapshot_id: str = Query(min_length=1, max_length=240),
    decision_as_of: datetime = Query(),
    role: DecisionBriefRole = Query(default=DecisionBriefRole.PROCESS_ENGINEER),
    principal: Principal = Depends(require_permission("events.read")),
    decision_support: OperationalDecisionSupportService = Depends(get_operational_decision_support_service),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    identity = _decision_support_identity(
        principal=principal, project_id=project_id, workspace_id=workspace_id,
        asset_id=asset_id, evidence_snapshot_id=evidence_snapshot_id, decision_as_of=decision_as_of,
    )
    _trusted_decision_support_risk(identity, service)
    brief, trace = decision_support.cached_brief(identity=identity, actor_role=role)
    return JSONResponse(
        status_code=200 if brief is not None else 202,
        content={"brief": brief.model_dump(mode="json") if brief is not None else None, "trace": asdict(trace)},
    )


@router.post("/objects/{asset_id}/decision-support-brief")
def create_decision_support_brief(
    asset_id: str,
    project_id: str = Query(default="manufacturing-demo-project"),
    workspace_id: str = Query(default=MANUFACTURING_WORKSPACE, max_length=160),
    evidence_snapshot_id: str = Query(min_length=1, max_length=240),
    decision_as_of: datetime = Query(),
    role: DecisionBriefRole = Query(default=DecisionBriefRole.PROCESS_MANAGER),
    risk_status: str | None = Query(default=None, min_length=1, max_length=80),
    trigger: Literal["manual_materialization", "ui_manual_regeneration"] = Query(default="manual_materialization"),
    principal: Principal = Depends(require_permission("agent.review.materialize")),
    _: None = Depends(require_csrf),
    decision_support: OperationalDecisionSupportService = Depends(get_operational_decision_support_service),
    limiter: RateLimiter = Depends(get_rate_limiter),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    identity = _decision_support_identity(
        principal=principal, project_id=project_id, workspace_id=workspace_id,
        asset_id=asset_id, evidence_snapshot_id=evidence_snapshot_id, decision_as_of=decision_as_of,
    )
    trusted_risk = _trusted_decision_support_risk(identity, service)
    if risk_status is not None and risk_status != trusted_risk:
        raise HTTPException(status_code=409, detail="evidence_risk_mismatch")
    limiter.check(
        bucket="decision-support-brief.materialize",
        subject=rate_limit_subject(
            principal.user_id, project_id, workspace_id, asset_id,
            evidence_snapshot_id, role.value, trigger,
        ),
        rule=DECISION_SUPPORT_MATERIALIZE_RATE,
    )
    try:
        brief, trace = decision_support.materialize(
            identity=identity, actor_role=role, risk_status=trusted_risk, trigger=trigger,
        )
    except (ValueError, DecisionSupportMaterializationInProgress) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"brief": brief.model_dump(mode="json"), "trace": asdict(trace)}


@router.get("/projects/{project_id}/decision-support-workflow-runs")
def list_decision_support_workflow_runs(
    project_id: str,
    asset_id: str | None = Query(default=None, max_length=160),
    status: Literal["running", "completed", "partial", "failed"] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(require_permission("admin.audit.read")),
    decision_support: OperationalDecisionSupportService = Depends(get_operational_decision_support_service),
):
    if not principal.is_admin and project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 평가 이력입니다.")
    if principal.active_project_id != project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 요청 Project를 활성화해야 합니다.")
    return {"items": decision_support.workflow_runs(
        organization_id=principal.organization_id, project_id=project_id,
        asset_id=asset_id, status=status, limit=limit,
    )}


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


@router.post("/agent/query")
def run_agent_query(
    request: AgentQueryRequest,
    principal: Principal = Depends(require_permission("events.read")),
    _: None = Depends(require_csrf),
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
):
    """Read-only grounded Operations assistant query."""

    if not principal.is_admin and request.project_id not in principal.project_scopes:
        raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 Agent Query입니다.")
    if principal.active_project_id != request.project_id:
        raise AuthError(409, "active_project_mismatch", "먼저 Project를 활성화해야 합니다.")
    if not principal.is_admin and request.workspace_id not in principal.workspace_scopes:
        raise AuthError(403, "workspace_scope_denied", "허용된 Workspace 범위를 벗어난 Agent Query입니다.")

    now = _utc_now()
    run_id = f"agent-{uuid.uuid4()}"
    route = "hybrid" if request.route == "auto" else request.route

    if not request.object_id:
        state = {
            "run_id": run_id,
            "organization_id": principal.organization_id,
            "project_id": request.project_id,
            "workspace_id": request.workspace_id,
            "user_id": principal.user_id,
            "question": request.question,
            "route": "relational" if request.route == "auto" else request.route,
            "status": "failed",
            "object_type": request.object_type,
            "object_id": None,
            "evidence": [],
            "claims": [],
            "steps": [{
                "name": "select_object",
                "store": None,
                "status": "failed",
                "latency_ms": None,
                "detail": "object_id is required for grounded Operations assistant answers",
            }],
            "answer": "먼저 설비나 이벤트를 선택해야 정본 근거 기반 답변을 만들 수 있습니다.",
            "caveats": ["No object was selected."],
            "error": "object_id_required",
            "checkpoint_sequence": 1,
        }
        return {"state": state, "traces": [{
            "id": f"trace-{uuid.uuid4()}",
            "run_id": run_id,
            "step_name": "select_object",
            "store_kind": None,
            "status": "failed",
            "input": request.model_dump(mode="json"),
            "output": {"error": "object_id_required"},
            "latency_ms": None,
            "created_at": now,
        }]}

    packet = None
    packet_source = "fixture-agent-review"
    if request.event_id:
        try:
            packet = _runtime_agent_review_packet(
                asset_id=request.object_id,
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                dataset_version_id=None,
                selected_event_id=request.event_id,
                principal=principal,
                runtime_service=get_predictive_maintenance_runtime_service(),
                context_service=service,
            )
            packet_source = "runtime-product-result"
        except EventNotFound:
            packet = None
    if packet is None:
        try:
            packet = service.agent_review_packet(
                request.object_id,
                request.project_id,
                history_window="24h",
            )
            packet_source = "fixture-agent-review"
        except EventNotFound:
            packet = _runtime_agent_review_packet(
                asset_id=request.object_id,
                project_id=request.project_id,
                workspace_id=request.workspace_id,
                dataset_version_id=None,
                selected_event_id=request.event_id,
                principal=principal,
                runtime_service=get_predictive_maintenance_runtime_service(),
                context_service=service,
            )
            packet_source = "runtime-product-result"
    evidence = _packet_evidence(
        packet,
        service=service,
        project_id=request.project_id,
        workspace_id=request.workspace_id,
        question=request.question,
        top_k=request.top_k,
    )
    try:
        tool_result = run_read_only_tool_pipeline(packet)
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        tool_result = {"terminal_status": "failed", "error": f"{type(exc).__name__}: {exc}", "steps": []}

    summary: dict[str, Any] | None = None
    summary_trace: dict[str, Any] = {}
    if principal.is_admin or "agent.review.materialize" in principal.permissions:
        try:
            if packet_source == "runtime-product-result":
                summary, summary_trace = service._materialize_agent_review_packet(
                    packet=packet, project_id=request.project_id,
                    organization_id=principal.organization_id,
                    workspace_id=request.workspace_id, history_window="24h",
                    trigger="manual_materialization", engine="simple",
                )
            else:
                summary, summary_trace = service.agent_review_summary(
                    request.object_id,
                    request.project_id,
                    organization_id=principal.organization_id,
                    workspace_id=request.workspace_id,
                    history_window="24h",
                    trigger="manual_materialization",
                )
        except Exception as exc:  # keep the assistant read path available
            summary_trace = {
                "fallback": "summary_materialization_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }

    baseline_answer = _answer_from_packet(request.question, packet, evidence, summary, request.audience)
    answer = baseline_answer
    answer_citations: list[str] = []
    answer_caveats: list[str] = []
    answer_trace = {
        "mode": "deterministic_fallback",
        "provider": "none",
        "reason": "provider_unavailable",
    }
    if service.agent_answer_provider is not None:
        answer, answer_citations, answer_caveats, answer_trace = service.agent_answer_provider.generate(
            question=request.question,
            audience=request.audience,
            packet=packet,
            evidence=evidence,
            baseline_answer=baseline_answer,
            summary=summary,
        )
    claim_ids = answer_citations or [item["evidence_id"] for item in evidence[:4]]
    steps = [
        {
            "name": "agent_review_packet",
            "store": "postgresql",
            "status": "succeeded",
            "latency_ms": None,
            "detail": f"Composed live Agent Review Packet for the selected Operations object via {packet_source}.",
        },
        {
            "name": "read_only_tool_pipeline",
            "store": "postgresql",
            "status": "succeeded" if not (tool_result.get("validation_errors") or tool_result.get("error")) else "failed",
            "latency_ms": None,
            "detail": str(tool_result.get("terminal_status") or "completed"),
        },
        {
            "name": "agent_review_summary",
            "store": "postgresql",
            "status": "succeeded" if summary else "skipped",
            "latency_ms": None,
            "detail": str((summary_trace.get("materialization") or {}).get("status") or summary_trace.get("fallback") or "packet answer"),
        },
        {
            "name": "grounded_answer",
            "store": "company_context+postgresql",
            "status": "succeeded",
            "latency_ms": None,
            "detail": f"{answer_trace.get('mode')} via {answer_trace.get('provider')}",
        },
    ]
    state = {
        "run_id": run_id,
        "organization_id": principal.organization_id,
        "project_id": request.project_id,
        "workspace_id": request.workspace_id,
        "user_id": principal.user_id,
        "question": request.question,
        "route": route,
        "status": "succeeded",
        "object_type": request.object_type or "asset",
        "object_id": request.object_id,
        "evidence": evidence,
        "claims": [{
            "claim_id": "claim-grounded-answer",
            "text": answer,
            "evidence_ids": claim_ids,
            "confidence": "high" if claim_ids else "medium",
            "validated": True,
        }],
        "steps": steps,
        "answer": answer,
        "caveats": [
            "Read-only Operations assistant: no workflow approval, execution, or state mutation was performed.",
            *answer_caveats,
        ],
        "error": None,
        "checkpoint_sequence": 1,
    }
    traces = [
        {
            "id": f"trace-{uuid.uuid4()}",
            "run_id": run_id,
            "step_name": step["name"],
            "store_kind": step["store"],
            "status": step["status"],
            "input": {"question": request.question, "object_id": request.object_id} if step["name"] == "agent_review_packet" else {},
            "output": {"detail": step["detail"]},
            "latency_ms": step["latency_ms"],
            "created_at": now,
        }
        for step in steps
    ]
    return {"state": state, "traces": traces}


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
    role = identity.report_role(principal, request.role)
    report, trace = service.report(
        event_id,
        ReportRequest(role=role, report_type=request.report_type, locale=request.locale, use_llm=request.use_llm),
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


@router.get("/objects/{asset_id}/factory-records")
def get_factory_records(
    asset_id: str,
    project_id: str = Query(), workspace_id: str = Query(),
    evidence_snapshot_id: str = Query(min_length=1, max_length=240),
    decision_as_of: datetime = Query(),
    principal: Principal = Depends(require_permission("events.read")),
    repository: Any = Depends(get_operational_context_repository),
):
    from .factory_records import read_records
    identity = _decision_support_identity(principal=principal, project_id=project_id,
        workspace_id=workspace_id, asset_id=asset_id,
        evidence_snapshot_id=evidence_snapshot_id, decision_as_of=decision_as_of)
    page = get_predictive_maintenance_runtime_service().latest_results(
        organization_id=principal.organization_id, project_id=project_id,
        workspace_id=workspace_id, dataset_version_id=None, asset_id=asset_id, limit=1)
    result = next((r for r in page.items if r.asset_id==asset_id), None)
    if result is None or _runtime_event_id(result)!=evidence_snapshot_id or result.observed_at!=decision_as_of:
        raise HTTPException(status_code=409, detail="factory_record_snapshot_mismatch")
    with repository.connection(principal.organization_id, project_id) as connection:
        asset_rows = repository.execute(connection,
            "SELECT asset_id FROM pm_assets WHERE organization_id=? AND project_id=? AND workspace_id=? AND dataset_version_id=?",
            (principal.organization_id, project_id, workspace_id, page.context.dataset_version_id)).fetchall()
    return read_records(repository, identity=identity,
        dataset_version_id=page.context.dataset_version_id,
        model_version=result.provenance.model_version,
        asset_ids=[r['asset_id'] for r in asset_rows])

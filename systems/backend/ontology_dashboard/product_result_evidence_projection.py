"""Artifact-derived Event Evidence projection helpers.

This module belongs to the dashboard projection layer. It consumes Product
Result Artifacts produced by ``systems/backend/app/diagnosis`` and derives
dashboard/report-facing evidence without becoming the runtime producer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import AppLocale, GroundedReport, ReportAction, ReportSection, Role

HIDDEN_KEYS = {"evaluation_truth", "hidden_truth"}
EVENT_EVIDENCE_SCHEMA_VERSION = "event-evidence-projection-v1"
EVENT_EVIDENCE_CONTRACT_TYPE = "event_evidence_projection"

DECISION_BY_ACTION = {
    "continue_monitoring": "continue_monitoring",
    "request_inspection": "request_inspection",
    "inspect_within_current_shift": "request_inspection",
    "immediate_inspection_and_stop_review": "review_shutdown",
    "hold_for_data_check": "hold_for_data_check",
}


def product_result_artifact_to_event_evidence_projection(artifact: dict[str, Any]) -> dict[str, Any]:
    """Derive canonical Event Evidence projection from a producer-enriched artifact."""

    clean_artifact = _strip_hidden(artifact)
    _ensure_unmutated_source(clean_artifact)
    payload = clean_artifact.get("evidence_payload")
    if not isinstance(payload, dict):
        raise ValueError("Product Result Artifact evidence_payload is required for Event Evidence projection")
    provenance = clean_artifact.get("provenance", {})
    event_id = f"EVT-{clean_artifact['artifact_id']}"
    threshold = clean_artifact.get("threshold")
    recommended_decision = _recommended_decision(clean_artifact)
    projection = {
        "schema_version": EVENT_EVIDENCE_SCHEMA_VERSION,
        "contract_type": EVENT_EVIDENCE_CONTRACT_TYPE,
        "event_id": event_id,
        "scenario_id": None,
        "subject": _subject(clean_artifact),
        "artifact_reference": {
            "artifact_id": clean_artifact.get("artifact_id"),
            "artifact_type": clean_artifact.get("artifact_type"),
            "artifact_schema_version": clean_artifact.get("schema_version"),
            "asset_id": clean_artifact.get("asset_id"),
            "asset_type": clean_artifact.get("asset_type"),
            "observed_at": clean_artifact.get("observed_at"),
            "prediction_id": provenance.get("prediction_id"),
            "top_factor_count": len(clean_artifact.get("top_factors", [])),
            "evidence_payload_reference": provenance.get("evidence_payload_reference"),
        },
        "assessment": {
            "status": clean_artifact.get("status_grade"),
            "recommended_decision": recommended_decision,
            "confidence": _confidence_label(clean_artifact.get("confidence_label") or clean_artifact.get("confidence")),
            "confidence_value": clean_artifact.get("confidence"),
            "failure_probability": clean_artifact.get("failure_probability"),
            "threshold": threshold,
            "predicted_failure_type": clean_artifact.get("predicted_failure_type"),
            "top_factors": clean_artifact.get("top_factors", []),
            "data_quality_warnings": clean_artifact.get("data_quality_warnings", []),
        },
        "report_projection": {
            "display_labels": {
                "status_label": _status_label(clean_artifact.get("status_grade")),
                "confidence_label": _confidence_label(clean_artifact.get("confidence_label") or clean_artifact.get("confidence")),
                "probability_label": _probability_label(clean_artifact.get("failure_probability")),
            },
            "sensor_cards": _sensor_cards(payload.get("sensor_evidence", {})),
            "inspection_targets": payload.get("component_hypotheses", []),
            "recommended_actions": payload.get("recommended_actions", []),
            "evidence_trace": payload.get("source_fields", []),
            "maintenance_context": payload.get("maintenance_context", {}),
            "status_flags": payload.get("status_flags", {}),
        },
        "provenance": {
            "dataset_version": provenance.get("dataset_version"),
            "model_version": provenance.get("model_version"),
            "prediction_id": provenance.get("prediction_id"),
            "source_type": provenance.get("source_type"),
            "model_artifact": provenance.get("model_artifact"),
            "lineage": {
                **(clean_artifact.get("lineage", {}) or {}),
                "observation": clean_artifact.get("observation", {}),
                "history": clean_artifact.get("history", []),
                "detected_interval": clean_artifact.get("detected_interval"),
                "policy_version": clean_artifact.get("policy_version"),
                "model_mode": clean_artifact.get("model_mode"),
            },
        },
        "limitations": _limitations(clean_artifact, payload),
        "generated_at": clean_artifact.get("generated_at") or clean_artifact.get("observed_at"),
    }
    return _strip_hidden(projection)


def event_evidence_projection_to_legacy_evidence(
    evidence: dict[str, Any],
    *,
    ranked_factor_evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build legacy evidence-package-compatible shape from canonical projection."""

    projection = _strip_hidden(evidence)
    assessment = projection["assessment"]
    report_projection = projection["report_projection"]
    artifact_reference = projection["artifact_reference"]
    provenance = projection["provenance"]
    lineage = dict(provenance.get("lineage") or {})
    threshold = assessment.get("threshold")
    if threshold is None:
        raise ValueError("legacy evidence projection requires an explicit threshold")

    maintenance_context = report_projection.get("maintenance_context") or {}
    legacy_factor_source = ranked_factor_evidence or assessment.get("top_factors", [])
    top_factors = [_legacy_top_factor(factor) for factor in legacy_factor_source]
    if any(not isinstance(factor, dict) or "evidence_field_id" not in factor for factor in top_factors):
        raise ValueError("legacy evidence projection requires producer-normalized top_factors")

    legacy = {
        "schema_version": "1.0",
        "evidence_id": f"EVD-{projection['event_id']}",
        "event_id": projection["event_id"],
        "scenario_id": projection.get("scenario_id") or lineage.get("fixture_id") or "unknown",
        "equipment": projection.get("subject", {}),
        "model": {
            "model_version": provenance.get("model_version") or "unknown",
            "policy_version": lineage.get("policy_version") or "unknown",
            "mode": lineage.get("model_mode") or "deterministic_fallback",
            "artifact": provenance.get("model_artifact"),
        },
        "status": assessment.get("status"),
        "recommended_decision": assessment.get("recommended_decision"),
        "confidence": assessment.get("confidence"),
        "failure_probability": assessment.get("failure_probability"),
        "threshold": float(threshold),
        "predicted_failure_type": assessment.get("predicted_failure_type") or "uncertain",
        "observation": lineage.get("observation", {}),
        "history": lineage.get("history", []),
        "detected_interval": lineage.get("detected_interval")
        or {"start": artifact_reference.get("observed_at"), "end": artifact_reference.get("observed_at")},
        "top_factors": top_factors,
        "maintenance_context": maintenance_context,
        "data_quality_warnings": assessment.get("data_quality_warnings", []),
        "lineage": {
            "fixture_id": lineage.get("fixture_id") or projection.get("scenario_id") or "unknown",
            "fixture_schema_version": lineage.get("fixture_schema_version") or "derived",
            "sensor_source": lineage.get("sensor_source") or "artifact-derived projection",
            "context_source": lineage.get("context_source")
            or (
                f"{maintenance_context.get('provider')}:{maintenance_context.get('version')}"
                if maintenance_context.get("provider") and maintenance_context.get("version")
                else "unavailable"
            ),
            "product_result_artifact": artifact_reference,
        },
        "generated_at": projection.get("generated_at") or artifact_reference.get("observed_at"),
    }
    return _strip_hidden(legacy)


def event_evidence_projection_to_grounded_report(
    evidence: dict[str, Any],
    role: Role,
    *,
    locale: AppLocale = "ko-KR",
    mode: str = "deterministic",
) -> GroundedReport:
    """Render the current report contract from canonical Event Evidence only.

    This is deliberately a projection mapper: it neither reads Product Result
    Artifact payloads nor computes risk, aggregate, or operations values.
    """

    projection = _strip_hidden(evidence)
    if role not in {"manager", "engineer"}:
        raise ValueError(f"unsupported report role: {role}")
    if locale not in {"ko-KR", "en-US"}:
        raise ValueError(f"unsupported report locale: {locale}")
    if mode not in {"deterministic", "llm", "deterministic_fallback"}:
        raise ValueError(f"unsupported report mode: {mode}")

    assessment = projection["assessment"]
    report_projection = projection["report_projection"]
    source_fields = _source_field_map(report_projection)
    factor_refs = _factor_source_refs(assessment.get("top_factors"), source_fields)
    action_refs = _action_source_refs(report_projection, source_fields)
    evidence_refs = action_refs or factor_refs
    status = str(assessment.get("status") or "unavailable")
    decision = str(assessment.get("recommended_decision") or "continue_monitoring")
    subject = projection.get("subject") or {}
    equipment_name = str(subject.get("display_name") or subject.get("equipment_id") or "Unknown asset")
    status_label = _localized_status_label(status, locale)
    decision_label = _localized_decision_label(decision, locale)
    evidence_text = _grounded_evidence_text(source_fields, evidence_refs, locale)

    if role == "manager":
        headline = (
            f"{equipment_name} · {status_label} · {decision_label}"
            if locale == "ko-KR"
            else f"{equipment_name} · {status_label} · {decision_label}"
        )
        summary = (
            f"저장된 producer Artifact에서 파생된 Event Evidence는 {status_label} 상태와 "
            f"'{decision_label}' 결정을 나타냅니다."
            if locale == "ko-KR"
            else f"Event Evidence derived from the stored producer Artifact indicates {status_label.lower()} status and the '{decision_label}' decision."
        )
        sections = [
            ReportSection(
                section_id="manager-status",
                title="현재 판단" if locale == "ko-KR" else "Current assessment",
                body=summary,
                evidence_field_ids=evidence_refs,
            ),
            ReportSection(
                section_id="manager-evidence",
                title="핵심 근거" if locale == "ko-KR" else "Key evidence",
                body=evidence_text,
                evidence_field_ids=evidence_refs,
            ),
        ]
    else:
        inspection_text = _inspection_targets_text(
            report_projection.get("inspection_targets"), source_fields, locale
        )
        headline = (
            f"{equipment_name} 근거 분석 · {status_label}"
            if locale == "ko-KR"
            else f"{equipment_name} evidence analysis · {status_label}"
        )
        summary = (
            f"{status_label} 상태의 근거를 확인하고 현장 점검으로 원인을 검토해야 합니다."
            if locale == "ko-KR"
            else f"Review the evidence for {status_label.lower()} status and confirm the cause through a field inspection."
        )
        sections = [
            ReportSection(
                section_id="engineer-factors",
                title="센서·요인 근거" if locale == "ko-KR" else "Sensor and factor evidence",
                body=evidence_text,
                evidence_field_ids=evidence_refs,
            ),
            ReportSection(
                section_id="engineer-checklist",
                title="점검 후보" if locale == "ko-KR" else "Inspection candidates",
                body=inspection_text,
                evidence_field_ids=action_refs,
            ),
            ReportSection(
                section_id="engineer-manager-summary",
                title="매니저 보고용 요약" if locale == "ko-KR" else "Manager briefing",
                body=summary,
                evidence_field_ids=evidence_refs,
            ),
        ]

    actions = [
        ReportAction(
            action_id=f"decision.{decision}",
            label=decision_label,
            kind=_report_action_kind(decision),
            requires_human_approval=True,
            source_refs=action_refs,
        )
    ]
    maintenance_note = add_maintenance_note_descriptor(projection, locale=locale)
    if maintenance_note is not None:
        actions.append(maintenance_note)

    report = GroundedReport(
        report_id=f"RPT-{projection['event_id']}-{role}-{locale}",
        event_id=projection["event_id"],
        role=role,
        locale=locale,
        mode=mode,  # type: ignore[arg-type]
        headline=headline,
        summary=summary,
        status=status,
        confidence=str(assessment.get("confidence") or "unavailable"),
        recommended_decision=decision,
        sections=sections,
        actions=actions,
        citations=sorted({reference for section in sections for reference in section.evidence_field_ids}),
        limitations=_report_limitations(projection, locale),
        generated_at=projection["generated_at"],
    )
    validate_grounded_report_source_refs(projection, report)
    return report


def add_maintenance_note_descriptor(
    evidence: dict[str, Any],
    *,
    locale: AppLocale = "ko-KR",
) -> ReportAction | None:
    """Return the bounded Event-note descriptor when the evidence is grounded.

    The descriptor intentionally does not create a Work Order, confirm a
    Maintenance Record, or execute an operational action.
    """

    report_projection = evidence.get("report_projection") or {}
    source_fields = _source_field_map(report_projection)
    source_refs = _action_source_refs(report_projection, source_fields)
    if not source_refs:
        return None
    return ReportAction(
        action_id="add_maintenance_note",
        label="정비이력 추가" if locale == "ko-KR" else "Add maintenance note",
        kind="maintenance_note",
        requires_human_approval=True,
        source_refs=source_refs,
    )


def validate_grounded_report_source_refs(evidence: dict[str, Any], report: GroundedReport) -> None:
    """Reject reports that cite anything outside Event Evidence source fields."""

    source_field_ids = set(_source_field_map(evidence.get("report_projection") or {}))
    references = set(report.citations)
    for section in report.sections:
        references.update(section.evidence_field_ids)
    for action in report.actions:
        references.update(action.source_refs)
    unknown = sorted(references - source_field_ids)
    if unknown:
        raise ValueError(f"report references unknown Event Evidence source fields: {unknown}")


def _source_field_map(report_projection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    source_fields = report_projection.get("evidence_trace") or []
    mapped: dict[str, dict[str, Any]] = {}
    for field in source_fields:
        if not isinstance(field, dict) or not isinstance(field.get("field_id"), str):
            raise ValueError("Event Evidence evidence_trace must contain source_fields[].field_id")
        mapped[field["field_id"]] = field
    return mapped


def _factor_source_refs(factors: Any, source_fields: dict[str, dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for factor in factors or []:
        if not isinstance(factor, dict):
            continue
        rank = factor.get("rank")
        feature = factor.get("feature")
        if isinstance(rank, int) and isinstance(feature, str):
            field_id = f"factor.{rank}.{feature}"
            if field_id in source_fields:
                refs.append(field_id)
    return _unique_refs(refs)


def _action_source_refs(report_projection: dict[str, Any], source_fields: dict[str, dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for action in report_projection.get("recommended_actions") or []:
        if isinstance(action, dict):
            refs.extend(action.get("basis") or [])
    for target in report_projection.get("inspection_targets") or []:
        if isinstance(target, dict):
            refs.extend(target.get("basis") or [])
    return _unique_refs(reference for reference in refs if isinstance(reference, str) and reference in source_fields)


def _unique_refs(references: Any) -> list[str]:
    return list(dict.fromkeys(references))


def _grounded_evidence_text(
    source_fields: dict[str, dict[str, Any]],
    source_refs: list[str],
    locale: AppLocale,
) -> str:
    if not source_refs:
        return "근거 필드가 제공되지 않았습니다." if locale == "ko-KR" else "No grounded evidence field was provided."
    labels = [str(source_fields[reference].get("label") or reference) for reference in source_refs]
    if locale == "ko-KR":
        return "확인할 근거: " + ", ".join(labels)
    return "Evidence to review: " + ", ".join(labels)


def _inspection_targets_text(
    targets: Any,
    source_fields: dict[str, dict[str, Any]],
    locale: AppLocale,
) -> str:
    labels = []
    for target in targets or []:
        if not isinstance(target, dict):
            continue
        basis = _unique_refs(
            reference for reference in target.get("basis") or [] if isinstance(reference, str) and reference in source_fields
        )
        if basis:
            labels.append(str(target.get("component_label") or target.get("component_id") or "inspection candidate"))
    if not labels:
        return "근거가 연결된 점검 후보가 없습니다." if locale == "ko-KR" else "No grounded inspection candidate is available."
    if locale == "ko-KR":
        return "점검 후보: " + ", ".join(labels)
    return "Inspection candidates: " + ", ".join(labels)


def _localized_status_label(status: str, locale: AppLocale) -> str:
    labels = {
        "ko-KR": {"normal": "정상", "attention": "주의", "warning": "경고", "critical": "긴급", "data_quality_hold": "데이터 확인 필요"},
        "en-US": {"normal": "Normal", "attention": "Attention", "warning": "Warning", "critical": "Critical", "data_quality_hold": "Data quality review required"},
    }
    return labels[locale].get(status, status)


def _localized_decision_label(decision: str, locale: AppLocale) -> str:
    labels = {
        "ko-KR": {
            "continue_monitoring": "계속 모니터링",
            "request_inspection": "현장 점검 요청",
            "review_shutdown": "권한자의 정지 검토 요청",
            "hold_for_data_check": "데이터 확인 전 판단 보류",
        },
        "en-US": {
            "continue_monitoring": "Continue monitoring",
            "request_inspection": "Request a field inspection",
            "review_shutdown": "Request an authorized shutdown review",
            "hold_for_data_check": "Hold pending data verification",
        },
    }
    return labels[locale].get(decision, decision)


def _report_action_kind(decision: str) -> str:
    return {
        "continue_monitoring": "monitor",
        "request_inspection": "inspect",
        "review_shutdown": "review_shutdown",
        "hold_for_data_check": "verify_data",
    }.get(decision, "report")


def _report_limitations(evidence: dict[str, Any], locale: AppLocale) -> list[str]:
    limitations = [str(item) for item in evidence.get("limitations") or []]
    note_boundary = (
        "정비이력 추가는 Event 메모 기록 제안이며 Work Order 생성이나 정비 확정이 아닙니다."
        if locale == "ko-KR"
        else "Adding a maintenance note is an Event-note proposal, not Work Order creation or maintenance confirmation."
    )
    return _unique_refs([*limitations, note_boundary])


def _strip_hidden(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_hidden(item) for key, item in deepcopy(value).items() if key not in HIDDEN_KEYS}
    if isinstance(value, list):
        return [_strip_hidden(item) for item in value]
    return deepcopy(value)


def _legacy_top_factor(factor: Any) -> dict[str, Any]:
    if not isinstance(factor, dict) or "evidence_field_id" not in factor:
        return {}
    return {
        "evidence_field_id": factor.get("evidence_field_id"),
        "feature": factor.get("feature"),
        "display_name": factor.get("display_name") or factor.get("feature"),
        "value": factor.get("value") if factor.get("value") is not None else factor.get("feature_value"),
        "unit": factor.get("unit", ""),
        "normal_range": factor.get("normal_range", "근거 부족"),
        "direction": factor.get("direction"),
        "contribution": factor.get("contribution"),
        "source_type": factor.get("source_type", "observed"),
    }


def _ensure_unmutated_source(artifact: dict[str, Any]) -> None:
    provenance = artifact.get("provenance") or {}
    if provenance.get("canonical_source_mutated") is not False:
        raise ValueError("Product Result Artifact provenance.canonical_source_mutated must be false")


def _sensor_cards(sensor_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    cards = []
    for sensor_key, sensor in (sensor_evidence.get("sensors") or {}).items():
        cards.append(
            {
                "sensor_id": sensor_key,
                "label": sensor.get("display_name") or sensor_key,
                "current": sensor.get("current"),
                "window_mean": sensor.get("window_mean"),
                "unit": sensor.get("unit", ""),
                "z_score": sensor.get("z_score"),
                "basis": sensor.get("basis", {}),
                "source_field_id": f"sensor_evidence.sensors.{sensor_key}",
            }
        )
    return cards


def _recommended_decision(artifact: dict[str, Any]) -> str:
    action = (artifact.get("recommended_action") or {}).get("action")
    if action in DECISION_BY_ACTION:
        return DECISION_BY_ACTION[action]
    status = artifact.get("status_grade")
    if status == "critical":
        return "review_shutdown"
    if status in {"warning", "attention"}:
        return "request_inspection"
    if status == "data_quality_hold":
        return "hold_for_data_check"
    return "continue_monitoring"


def _confidence_label(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, str):
        return value if value in {"high", "medium", "low", "unavailable"} else "unavailable"
    numeric = float(value)
    if numeric >= 0.7:
        return "high"
    if numeric >= 0.4:
        return "medium"
    return "low"


def _status_label(value: Any) -> str:
    return {
        "normal": "정상",
        "attention": "주의",
        "warning": "경고",
        "critical": "긴급",
        "data_quality_hold": "데이터 확인 필요",
    }.get(str(value), str(value))


def _probability_label(value: Any) -> str:
    if value is None:
        return "근거 부족"
    return f"{float(value) * 100:.1f}%"


def _subject(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        "equipment_id": artifact.get("asset_id"),
        "display_name": artifact.get("asset_id"),
        "asset_type": artifact.get("asset_type"),
    }


def _limitations(artifact: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    limitations = [
        "예측 결과는 고장 확정이 아니라 점검 우선순위 근거다.",
        "권장 조치는 자동 제어가 아니라 사람의 검토를 요구한다.",
    ]
    if artifact.get("data_quality_warnings"):
        limitations.append("데이터 품질 경고가 있어 해석에 제한이 있다.")
    if artifact.get("status_grade") == "data_quality_hold":
        limitations.append("센서 데이터 확인 전까지 위험 판단을 보류한다.")
    if payload.get("evidence_gaps"):
        limitations.append("일부 근거 필드는 evidence_gaps에 따라 산출 불가능 또는 보류 상태다.")
    return limitations

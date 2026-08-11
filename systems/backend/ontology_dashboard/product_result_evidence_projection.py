"""Artifact-derived Event Evidence projection helpers.

This module belongs to the dashboard projection layer. It consumes Product
Result Artifacts produced by ``systems/backend/app/diagnosis`` and derives
dashboard/report-facing evidence without becoming the runtime producer.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

HIDDEN_KEYS = {"evaluation_truth", "hidden_truth"}
EVENT_EVIDENCE_SCHEMA_VERSION = "event-evidence-projection-v1"
EVENT_EVIDENCE_CONTRACT_TYPE = "event_evidence_projection"

SENSOR_DISPLAY = {
    "air_temperature_k": ("공기 온도", "K"),
    "process_temperature_k": ("공정 온도", "K"),
    "rotational_speed_rpm": ("회전 속도", "rpm"),
    "torque_nm": ("토크", "N.m"),
    "tool_wear_min": ("공구 마모", "min"),
    "temperature_difference_k": ("공정·공기 온도 차이", "K"),
    "mechanical_power_w": ("기계 동력", "W"),
    "overstrain_index": ("과부하 지표", "N.m.min"),
    "rotation_raw": ("회전 상태", "rpm"),
    "pressure_raw": ("압력", "bar"),
    "vibration_raw": ("진동", "mm/s"),
    "voltage_raw": ("전압", "V"),
}

COMPONENT_HINTS = {
    "tool_wear_min": ("cutting_tool", "공구/절삭부"),
    "temperature_difference_k": ("thermal_path", "냉각/열 방출 계통"),
    "process_temperature_k": ("thermal_path", "냉각/열 방출 계통"),
    "mechanical_power_w": ("drive_load_path", "구동/부하 계통"),
    "overstrain_index": ("drive_load_path", "구동/부하 계통"),
    "torque_nm": ("drive_load_path", "구동/부하 계통"),
    "rotational_speed_rpm": ("spindle_drive", "회전 구동부"),
    "vibration_raw": ("rotating_assembly", "회전/진동 계통"),
    "rotation_raw": ("rotating_assembly", "회전/진동 계통"),
    "pressure_raw": ("pressure_path", "압력 계통"),
    "voltage_raw": ("power_supply", "전원 계통"),
}

DECISION_BY_ACTION = {
    "continue_monitoring": "continue_monitoring",
    "request_inspection": "request_inspection",
    "inspect_within_current_shift": "request_inspection",
    "immediate_inspection_and_stop_review": "review_shutdown",
    "hold_for_data_check": "hold_for_data_check",
}


def reference_pdm_evidence_to_artifact_extension(package: dict[str, Any]) -> dict[str, Any]:
    """Convert a reference evidence package into an optional artifact extension."""

    sanitized = _strip_hidden(package)
    top_factors = _normalise_top_factors(sanitized.get("top_factors", []))
    sensor_evidence = _normalise_sensor_evidence(sanitized)
    source_fields = _build_source_fields(top_factors, sensor_evidence)
    extension = {
        "event_id": sanitized.get("event_id"),
        "scenario_id": sanitized.get("scenario_id"),
        "equipment": sanitized.get("equipment"),
        "observation": sanitized.get("observation", {}),
        "history": sanitized.get("history", []),
        "detected_interval": sanitized.get("detected_interval"),
        "generated_at": sanitized.get("generated_at") or sanitized.get("observed_at"),
        "threshold": sanitized.get("threshold"),
        "model": sanitized.get("model", {}),
        "sensor_evidence": sensor_evidence,
        "top_factors": top_factors,
        "component_hypotheses": _normalise_component_hypotheses(sanitized, top_factors),
        "status_flags": _normalise_status_flags(sanitized),
        "maintenance_context": sanitized.get("maintenance_context") or _empty_maintenance_context(),
        "recommended_actions": _normalise_recommended_actions(sanitized),
        "source_fields": source_fields,
        "failure_type_candidates": sanitized.get("failure_type_candidates", []),
        "data_quality_warnings": sanitized.get("data_quality_warnings", []),
        "lineage": sanitized.get("lineage", {}),
    }
    return _strip_none(extension)


def extend_product_result_artifact(
    result: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an artifact copy with a dashboard evidence extension envelope."""

    artifact = _strip_hidden(result)
    _ensure_unmutated_source(artifact)
    payload_context = context or {}
    reference_package = (
        payload_context.get("pdm_reference_package")
        or payload_context.get("reference_evidence_package")
        or payload_context.get("evidence_package")
        or {}
    )
    extension = reference_pdm_evidence_to_artifact_extension(reference_package) if reference_package else {}

    for key in ("event_id", "scenario_id", "equipment", "observation", "history", "detected_interval", "generated_at", "threshold"):
        if key in payload_context and payload_context[key] is not None:
            extension[key] = _strip_hidden(payload_context[key])

    extension["top_factors"] = _normalise_top_factors(artifact.get("top_factors", []))
    extension.setdefault("sensor_evidence", _normalise_sensor_evidence(extension))
    extension["source_fields"] = _build_source_fields(extension["top_factors"], extension["sensor_evidence"])
    extension["component_hypotheses"] = _normalise_component_hypotheses({}, extension["top_factors"])
    extension.setdefault("status_flags", {})
    extension.setdefault("maintenance_context", _empty_maintenance_context())
    extension.setdefault("recommended_actions", _normalise_recommended_actions(extension, artifact))
    extension.setdefault("data_quality_warnings", [])
    extension.setdefault("lineage", {})

    artifact["evidence_payload"] = _strip_hidden(extension)
    provenance = artifact.setdefault("provenance", {})
    provenance["evidence_extension_reference"] = {
        "source": "artifact_derived_projection",
        "reference": payload_context.get("reference")
        or extension.get("lineage", {}).get("fixture_id")
        or extension.get("lineage", {}).get("reference_fixture")
        or "dashboard-fixture",
        "generated_by": "ontology_dashboard.product_result_evidence_projection",
    }
    return artifact


def extended_artifact_to_event_evidence_projection(artifact: dict[str, Any]) -> dict[str, Any]:
    """Derive canonical Event Evidence projection from an extended artifact."""

    clean_artifact = _strip_hidden(artifact)
    payload = clean_artifact.get("evidence_payload", {})
    provenance = clean_artifact.get("provenance", {})
    event_id = payload.get("event_id") or f"EVT-{clean_artifact['artifact_id']}"
    threshold = payload.get("threshold")
    recommended_decision = _recommended_decision(clean_artifact)
    projection = {
        "schema_version": EVENT_EVIDENCE_SCHEMA_VERSION,
        "contract_type": EVENT_EVIDENCE_CONTRACT_TYPE,
        "event_id": event_id,
        "scenario_id": payload.get("scenario_id"),
        "subject": _subject(clean_artifact, payload),
        "artifact_reference": {
            "artifact_id": clean_artifact.get("artifact_id"),
            "artifact_type": clean_artifact.get("artifact_type"),
            "artifact_schema_version": clean_artifact.get("schema_version"),
            "asset_id": clean_artifact.get("asset_id"),
            "asset_type": clean_artifact.get("asset_type"),
            "observed_at": clean_artifact.get("observed_at"),
            "prediction_id": provenance.get("prediction_id"),
            "top_factor_count": len(clean_artifact.get("top_factors", [])),
            "evidence_extension_reference": provenance.get("evidence_extension_reference"),
        },
        "assessment": {
            "status": clean_artifact.get("status_grade"),
            "recommended_decision": recommended_decision,
            "confidence": _confidence_label(clean_artifact.get("confidence")),
            "confidence_value": clean_artifact.get("confidence"),
            "failure_probability": clean_artifact.get("failure_probability"),
            "threshold": threshold,
            "predicted_failure_type": clean_artifact.get("predicted_failure_type"),
            "top_factors": payload.get("top_factors", _normalise_top_factors(clean_artifact.get("top_factors", []))),
            "data_quality_warnings": payload.get("data_quality_warnings", []),
        },
        "report_projection": {
            "display_labels": {
                "status_label": _status_label(clean_artifact.get("status_grade")),
                "confidence_label": _confidence_label(clean_artifact.get("confidence")),
                "probability_label": _probability_label(clean_artifact.get("failure_probability")),
            },
            "sensor_cards": _sensor_cards(payload.get("sensor_evidence", {})),
            "inspection_targets": payload.get("component_hypotheses", []),
            "recommended_actions": payload.get("recommended_actions", []),
            "evidence_trace": payload.get("source_fields", []),
            "maintenance_context": payload.get("maintenance_context", _empty_maintenance_context()),
            "status_flags": payload.get("status_flags", {}),
        },
        "provenance": {
            "dataset_version": provenance.get("dataset_version"),
            "model_version": provenance.get("model_version"),
            "prediction_id": provenance.get("prediction_id"),
            "source_type": provenance.get("source_type"),
            "model_artifact": provenance.get("model_artifact"),
            "lineage": {
                **(payload.get("lineage", {}) or {}),
                "observation": payload.get("observation", {}),
                "history": payload.get("history", []),
                "detected_interval": payload.get("detected_interval"),
                "policy_version": (payload.get("model") or {}).get("policy_version"),
                "model_mode": (payload.get("model") or {}).get("mode"),
            },
        },
        "limitations": _limitations(clean_artifact, payload),
        "generated_at": payload.get("generated_at") or clean_artifact.get("observed_at"),
    }
    return _strip_hidden(projection)


def event_evidence_projection_to_legacy_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
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

    maintenance_context = report_projection.get("maintenance_context") or _empty_maintenance_context()
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
        "top_factors": assessment.get("top_factors", []),
        "maintenance_context": maintenance_context,
        "data_quality_warnings": assessment.get("data_quality_warnings", []),
        "lineage": {
            "fixture_id": lineage.get("fixture_id") or projection.get("scenario_id") or "unknown",
            "fixture_schema_version": lineage.get("fixture_schema_version") or "derived",
            "sensor_source": lineage.get("sensor_source") or "artifact-derived projection",
            "context_source": lineage.get("context_source") or f"{maintenance_context['provider']}:{maintenance_context['version']}",
            "product_result_artifact": artifact_reference,
        },
        "generated_at": projection.get("generated_at") or artifact_reference.get("observed_at"),
    }
    return _strip_hidden(legacy)


def _strip_hidden(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_hidden(item) for key, item in deepcopy(value).items() if key not in HIDDEN_KEYS}
    if isinstance(value, list):
        return [_strip_hidden(item) for item in value]
    return deepcopy(value)


def _strip_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _ensure_unmutated_source(artifact: dict[str, Any]) -> None:
    provenance = artifact.get("provenance") or {}
    if provenance.get("canonical_source_mutated") is not False:
        raise ValueError("Product Result Artifact provenance.canonical_source_mutated must be false")


def _is_numeric_sensor_value(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _normalise_top_factors(raw_factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    factors = []
    total_score = sum(abs(float(item.get("signed_contribution", item.get("contribution", 0.0)) or 0.0)) for item in raw_factors)
    total_score = total_score or 1.0
    for index, item in enumerate(raw_factors, start=1):
        feature = str(item.get("feature") or item.get("name") or f"factor_{index}")
        display_name, unit = SENSOR_DISPLAY.get(feature, (feature, ""))
        raw_contribution = item.get("contribution")
        if raw_contribution is None:
            raw_contribution = abs(float(item.get("signed_contribution", 0.0) or 0.0)) / total_score
        value = item.get("value", item.get("feature_value", 0.0))
        factors.append(
            {
                "evidence_field_id": item.get("evidence_field_id") or f"factor.{index}.{feature}",
                "feature": feature,
                "display_name": item.get("display_name") or display_name,
                "value": float(value or 0.0),
                "unit": item.get("unit") or unit,
                "normal_range": item.get("normal_range") or "unavailable",
                "direction": item.get("direction") or ("risk_up" if float(raw_contribution or 0.0) >= 0 else "risk_down"),
                "contribution": round(abs(float(raw_contribution or 0.0)), 6),
                "source_type": item.get("source_type") or "derived",
            }
        )
    return factors


def _normalise_sensor_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("sensor_evidence"), dict):
        return _strip_hidden(payload["sensor_evidence"])

    observation = payload.get("observation") or {}
    history = payload.get("history") or []
    detected = payload.get("detected_interval") or {}
    sensors = {}
    for feature, value in observation.items():
        if feature in {"timestamp", "product_type"} or not _is_numeric_sensor_value(value):
            continue
        values = [row.get(feature) for row in history if _is_numeric_sensor_value(row.get(feature))]
        values.append(value)
        display_name, unit = SENSOR_DISPLAY.get(feature, (feature, ""))
        sensors[feature] = {
            "display_name": display_name,
            "unit": unit,
            "current": value,
            "window_mean": round(sum(float(item) for item in values) / len(values), 6) if values else None,
            "z_score": None,
            "basis": {
                "baseline_mean": None,
                "baseline_std": None,
                "baseline_n": 0,
                "baseline_reference": "unavailable",
            },
        }
    return {
        "window": {
            "start": detected.get("start") or (history[0]["timestamp"] if history else observation.get("timestamp")),
            "end": detected.get("end") or observation.get("timestamp"),
        },
        "window_rows": len(history) if history else (1 if observation else 0),
        "sensors": sensors,
    }


def _normalise_component_hypotheses(payload: dict[str, Any], top_factors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(payload.get("component_hypotheses"), list):
        return _strip_hidden(payload["component_hypotheses"])
    hypotheses = []
    seen = set()
    for factor in top_factors[:3]:
        component_id, label = COMPONENT_HINTS.get(factor["feature"], ("unknown_component", "확인 필요 구성요소"))
        if component_id in seen:
            continue
        seen.add(component_id)
        hypotheses.append(
            {
                "component_id": component_id,
                "component_label": label,
                "association": "inspection_candidate",
                "basis": [factor["evidence_field_id"]],
            }
        )
    return hypotheses


def _normalise_status_flags(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("status_flags")
    if isinstance(raw, dict):
        return _strip_hidden(raw)
    return {
        "multiple_risk_factors": len(payload.get("top_factors", [])) > 1,
        "insufficient_data": bool(payload.get("data_quality_warnings")),
    }


def _normalise_recommended_actions(
    payload: dict[str, Any],
    artifact: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw = payload.get("recommended_actions")
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return _strip_hidden(raw)
    if isinstance(raw, list) and raw:
        return [
            {
                "action_id": f"recommended_action.{index}",
                "label": str(label),
                "kind": "inspect",
                "requires_human_approval": True,
                "basis": ["maintenance_context.recommended_actions"],
            }
            for index, label in enumerate(raw, start=1)
        ]

    context_actions = (payload.get("maintenance_context") or {}).get("recommended_actions", [])
    if context_actions:
        return _normalise_recommended_actions({"recommended_actions": context_actions})

    action = (artifact or {}).get("recommended_action", {})
    if action:
        return [
            {
                "action_id": action.get("action", "recommended_action"),
                "label": action.get("action", "recommended_action"),
                "kind": "review_shutdown" if action.get("action") == "immediate_inspection_and_stop_review" else "inspect",
                "requires_human_approval": True,
                "basis": ["recommended_action"],
            }
        ]
    return []


def _build_source_fields(top_factors: list[dict[str, Any]], sensor_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [
        {
            "field_id": factor["evidence_field_id"],
            "source_path": f"top_factors[{index}]",
            "label": factor["display_name"],
            "description": "위험 판단에 사용된 상위 요인",
        }
        for index, factor in enumerate(top_factors)
    ]
    for sensor_key, sensor in (sensor_evidence.get("sensors") or {}).items():
        fields.append(
            {
                "field_id": f"sensor_evidence.sensors.{sensor_key}",
                "source_path": f"evidence_payload.sensor_evidence.sensors.{sensor_key}",
                "label": sensor.get("display_name") or sensor_key,
                "description": "센서 관측 및 baseline 근거",
            }
        )
    return fields


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


def _subject(artifact: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    equipment = payload.get("equipment") or {}
    if equipment:
        return equipment
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
    if payload.get("data_quality_warnings"):
        limitations.append("데이터 품질 경고가 있어 해석에 제한이 있다.")
    if artifact.get("status_grade") == "data_quality_hold":
        limitations.append("센서 데이터 확인 전까지 위험 판단을 보류한다.")
    return limitations


def _empty_maintenance_context() -> dict[str, Any]:
    return {
        "provider": "unavailable",
        "version": "unavailable",
        "source_type": "unavailable",
        "source_refs": [],
        "checklist": [],
        "recommended_actions": [],
    }

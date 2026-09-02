from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from typing import Protocol

DEFAULT_HISTORY_WINDOW = "24h"
HISTORY_WINDOW_HOURS = {
    "24h": 24,
    "7d": 24 * 7,
    "30d": 24 * 30,
}

FORBIDDEN_FEATURE_SOURCE_MARKERS = (
    "gen_data/",
    "_log.jsonl",
    "canonical/model_outputs",
    "precomputed_prediction_timeline",
)
FORBIDDEN_RISK_SOURCE_MARKERS = (
    "pm_prediction_timeline",
    "precomputed_prediction_timeline",
    "gen_data/canonical/model_outputs",
    "/timeline",
)


class AssetDetailReadPort(Protocol):
    """Read boundary for the candidate AssetDetailViewModel.

    Implementations may use repositories or external services, but they must
    provide already-contracted data. They must not expose raw gen_data paths,
    canonical CSV rows, or legacy timeline fixtures to this composer.
    """

    def asset_summary(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        asset_id: str,
    ) -> dict[str, Any] | None: ...

    def latest_result_artifact(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        asset_id: str,
        dataset_version_id: str | None,
    ) -> dict[str, Any] | None: ...

    def feature_series(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        asset_id: str,
        start: datetime,
        end: datetime,
        dataset_version_id: str | None,
        grain: str,
    ) -> dict[str, dict[str, Any]]: ...

    def runtime_prediction_history(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        asset_id: str,
        start: datetime,
        end: datetime,
        dataset_version_id: str | None,
    ) -> list[dict[str, Any]]: ...

    def equipment_history(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        asset_id: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]: ...

    def data_status(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        asset_id: str,
        dataset_version_id: str | None,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class AssetDetailRequest:
    organization_id: str
    project_id: str
    workspace_id: str
    asset_id: str
    start: datetime
    end: datetime
    dataset_version_id: str | None = None
    grain: str = "raw"
    history_window: str = DEFAULT_HISTORY_WINDOW


class AssetDetailViewModelService:
    def __init__(self, read_port: AssetDetailReadPort) -> None:
        self.read_port = read_port

    def detail_view(self, request: AssetDetailRequest) -> dict[str, Any]:
        asset = self.read_port.asset_summary(
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            asset_id=request.asset_id,
        )
        artifact = self.read_port.latest_result_artifact(
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            asset_id=request.asset_id,
            dataset_version_id=request.dataset_version_id,
        )
        if artifact is None:
            raise KeyError(f"result artifact not found for asset_id={request.asset_id}")
        if str(artifact.get("asset_id")) != request.asset_id:
            raise ValueError("result artifact asset_id does not match request asset_id")
        feature_series = self.read_port.feature_series(
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            asset_id=request.asset_id,
            start=request.start,
            end=request.end,
            dataset_version_id=request.dataset_version_id,
            grain=request.grain,
        )
        risk_history = self.read_port.runtime_prediction_history(
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            asset_id=request.asset_id,
            start=request.start,
            end=request.end,
            dataset_version_id=request.dataset_version_id,
        )
        history = self.read_port.equipment_history(
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            asset_id=request.asset_id,
            start=request.start,
            end=request.end,
        )
        data_status = self.read_port.data_status(
            organization_id=request.organization_id,
            project_id=request.project_id,
            workspace_id=request.workspace_id,
            asset_id=request.asset_id,
            dataset_version_id=request.dataset_version_id,
        )
        return compose_asset_detail_view_model(
            asset=asset or {
                "asset_id": request.asset_id,
                "asset_type": artifact["asset_type"],
                "observed_at": artifact["observed_at"],
            },
            result_artifact=artifact,
            feature_series=feature_series,
            runtime_prediction_history=risk_history,
            equipment_history=history,
            data_status=data_status,
            history_window=request.history_window,
        )


def compose_asset_detail_view_model(
    *,
    asset: dict[str, Any],
    result_artifact: dict[str, Any],
    feature_series: dict[str, dict[str, Any]] | None = None,
    runtime_prediction_history: list[dict[str, Any]] | None = None,
    equipment_history: list[dict[str, Any]] | None = None,
    operation_context: dict[str, Any] | None = None,
    closed_loop: dict[str, Any] | None = None,
    inspection_guidance: dict[str, dict[str, Any]] | None = None,
    inspection_locations: dict[str, dict[str, Any]] | None = None,
    data_status: dict[str, Any] | None = None,
    history_window: str = DEFAULT_HISTORY_WINDOW,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Compose the candidate AssetDetailViewModel from canonical contracts.

    The composer accepts Backend Observation/Feature Executor series and
    Diagnosis Runtime Prediction History Query results. It intentionally never
    reads raw gen_data files, canonical CSVs, or legacy timeline fixtures.
    """

    feature_series = feature_series or {}
    normalized_history_window = _normalize_history_window(history_window)
    runtime_prediction_history = runtime_prediction_history or []
    equipment_history = equipment_history or []
    evidence_payload = result_artifact.get("evidence_payload") or {}
    provenance = result_artifact.get("provenance") or {}
    gaps = [_view_model_gap(gap) for gap in evidence_payload.get("evidence_gaps") or []]
    if "recommended_actions" in evidence_payload and not evidence_payload.get("recommended_actions"):
        gaps.append(
            {
                "field": "evidence_payload.recommended_actions",
                "reason": "Diagnosis recommendation policy did not produce a recommendation",
                "owner_domain": "diagnosis",
            }
        )

    features, feature_gaps = _features_from_artifact(
        result_artifact,
        feature_series,
        history_window=normalized_history_window,
    )
    gaps.extend(feature_gaps)
    if not any(feature["history"]["points"] for feature in features):
        gaps.append(
            {
                "field": "features[].history.points",
                "reason": "Backend Observation/Feature Executor series is not connected yet",
                "owner_domain": "dataset",
            }
        )
    risk_series = [_risk_point(point) for point in runtime_prediction_history]
    if not risk_series:
        gaps.append(
            {
                "field": "risk_series",
                "reason": "Backend Diagnosis Runtime Prediction History Query is not materialized yet",
                "owner_domain": "diagnosis",
            }
        )
    if not equipment_history:
        gaps.append(
            {
                "field": "equipment_history",
                "reason": "Activity/Decision/Maintenance source is not connected to this composition endpoint yet",
                "owner_domain": "maintenance",
            }
        )
    asset_summary, asset_gaps = _asset_summary(asset, result_artifact)
    gaps.extend(asset_gaps)
    maintenance_context, maintenance_gaps = _maintenance_context(asset)
    operation_context_source = (
        {**asset, "operation_context": operation_context}
        if operation_context is not None
        else asset
    )
    operation_context, operation_gaps = _operation_context(operation_context_source)
    gaps.extend(maintenance_gaps)
    gaps.extend(operation_gaps)
    risk = {
        "current": result_artifact.get("failure_probability"),
        "threshold": result_artifact.get("threshold"),
        "status_grade": _status_grade(result_artifact),
        "prediction_horizon_hours": result_artifact.get("prediction_horizon_hours"),
    }
    review_priority, priority_gap = _review_priority(
        risk=risk,
        asset=asset_summary,
        maintenance_context=maintenance_context,
        operation_context=operation_context,
    )
    if priority_gap is not None:
        gaps.append(priority_gap)
    inspection_targets = _inspection_targets(
        result_artifact,
        provenance,
        inspection_guidance or {},
        inspection_locations or {},
    )

    return {
        "snapshot_basis": _evidence_snapshot_basis_from_artifact(
            result_artifact,
            event_id=event_id,
        ),
        "asset": asset_summary,
        "risk": risk,
        "risk_series": risk_series,
        "features": features,
        "equipment_history": equipment_history,
        "maintenance_context": maintenance_context,
        "inspection_targets": inspection_targets,
        "operation_context": operation_context,
        "review_priority": review_priority,
        **({"closed_loop": closed_loop} if closed_loop is not None else {}),
        "evidence": {
            "artifact_id": result_artifact.get("artifact_id"),
            "evidence_payload_reference": _evidence_payload_reference(provenance),
            "model_version": provenance.get("model_version"),
            "dataset_version": provenance.get("dataset_version"),
            "source_kind": "runtime_inference"
            if provenance.get("source_type") == "product_runtime_inference"
            else "compatibility_fallback",
            "gaps": _dedupe_gaps(gaps),
        },
        "data_status": _data_status(result_artifact, provenance, data_status),
    }


def _features_from_artifact(
    result_artifact: dict[str, Any],
    feature_series: dict[str, dict[str, Any]],
    *,
    history_window: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    evidence_payload = result_artifact.get("evidence_payload") or {}
    sensors = (evidence_payload.get("sensor_evidence") or {}).get("sensors") or {}
    top_factors = {
        str(factor.get("feature")): factor for factor in result_artifact.get("top_factors") or []
    }
    factor_evidence = {
        str(item.get("feature")): item for item in result_artifact.get("ranked_factor_evidence") or []
    }
    feature_keys = list(dict.fromkeys([*sensors.keys(), *top_factors.keys(), *feature_series.keys()]))
    features = []
    gaps = []
    current_observed_at = str(result_artifact["observed_at"])
    for index, key in enumerate(feature_keys):
        feature, gap = _feature(
            key,
            index=index,
            current_observed_at=current_observed_at,
            is_data_quality_hold=_is_data_quality_hold(result_artifact),
            sensor=sensors.get(key) or {},
            top_factor=top_factors.get(key),
            factor_evidence=factor_evidence.get(key),
            history=feature_series.get(key) or {},
            history_window=history_window,
        )
        features.append(feature)
        if gap is not None:
            gaps.append(gap)
    return features, gaps


def _asset_summary(
    asset: dict[str, Any],
    result_artifact: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    criticality = _criticality(asset.get("criticality"))
    basis = [str(item) for item in asset.get("criticality_basis") or []]
    source = str(asset.get("criticality_source") or "")
    if source not in {
        "manual_initial_assessment",
        "equipment_master",
        "project_context",
        "unknown",
    }:
        source = "equipment_master" if criticality is not None else "unknown"
    gaps = []
    if criticality is None:
        source = "unknown"
        basis = []
        gaps.append(
            {
                "field": "asset.criticality",
                "reason": "criticality_missing_or_unresolved",
                "owner_domain": _owner_domain(asset.get("criticality_owner_domain"), default="equipment"),
            }
        )
    elif not basis:
        gaps.append(
            {
                "field": "asset.criticality_basis",
                "reason": "criticality_basis_missing_or_unresolved",
                "owner_domain": _owner_domain(asset.get("criticality_owner_domain"), default="equipment"),
            }
        )
    return (
        {
            "asset_id": str(asset.get("asset_id") or result_artifact["asset_id"]),
            "asset_type": str(asset.get("asset_type") or result_artifact["asset_type"]),
            **_optional(asset, "display_name", "site_id", "cell_id"),
            "observed_at": str(asset.get("observed_at") or result_artifact["observed_at"]),
            "criticality": criticality,
            "criticality_basis": basis,
            "criticality_source": source,
        },
        gaps,
    )


def _feature(
    key: str,
    *,
    index: int,
    current_observed_at: str,
    is_data_quality_hold: bool,
    sensor: dict[str, Any],
    top_factor: dict[str, Any] | None,
    factor_evidence: dict[str, Any] | None,
    history: dict[str, Any],
    history_window: str,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    checked_history = _feature_history(
        history,
        current_observed_at=current_observed_at,
        history_window=history_window,
    )
    basis = sensor.get("basis") or {}
    baseline = None
    gap = None
    if basis:
        mean = basis.get("baseline_mean")
        std = basis.get("baseline_std")
        if _is_number(mean) and _is_number(std):
            baseline = {
                "mean": mean,
                "std": std,
                "lower": mean - (2 * std),
                "upper": mean + (2 * std),
                "reference": str(basis.get("baseline_reference") or ""),
            }
        else:
            gap = {
                "field": f"features[{index}].baseline",
                "reason": (
                    "baseline basis is incomplete; both baseline_mean and baseline_std "
                    "are required to compute range"
                ),
                "owner_domain": "diagnosis",
            }
    top_factor_summary = None
    if top_factor is not None:
        top_factor_summary = {
            "rank": top_factor["rank"],
            "contribution": top_factor.get("signed_contribution", top_factor.get("contribution")),
            "direction": top_factor["direction"],
            "explanation_method": top_factor["explanation_method"],
            **_optional(factor_evidence or {}, "evidence_field_id"),
        }
    current_value = sensor.get("current") if "current" in sensor else (factor_evidence or {}).get("value")
    current_quality = (
        "unknown" if is_data_quality_hold or current_value is None else "good"
    )
    return (
        {
            "key": key,
            "label": str(sensor.get("display_name") or (factor_evidence or {}).get("display_name") or key),
            "unit": str(sensor.get("unit") or (factor_evidence or {}).get("unit") or ""),
            "current": {
                "observed_at": current_observed_at,
                "value": current_value,
                "quality_status": current_quality,
            },
            "baseline": baseline,
            "history": checked_history,
            "top_factor": top_factor_summary,
        },
        gap,
    )


def _feature_history(
    history: dict[str, Any],
    *,
    current_observed_at: str,
    history_window: str,
) -> dict[str, Any]:
    source_ref = str(history.get("source_ref") or "")
    _reject_source_ref(source_ref, forbidden=FORBIDDEN_FEATURE_SOURCE_MARKERS)
    current_instant = _timestamp_instant(current_observed_at)
    requested_window = _normalize_history_window(history_window)
    requested_start = current_instant - timedelta(hours=HISTORY_WINDOW_HOURS[requested_window])
    by_instant: dict[datetime, dict[str, Any]] = {}
    for point in history.get("points") or []:
        observed_at = str(point["observed_at"])
        instant = _timestamp_instant(observed_at)
        if instant < requested_start or instant >= current_instant:
            continue
        checked = {
            "observed_at": observed_at,
            "value": point.get("value"),
            "quality_status": str(point.get("quality_status") or "unknown"),
        }
        if instant in by_instant and by_instant[instant] != checked:
            raise ValueError(f"conflicting feature history points at instant={instant.isoformat()}")
        by_instant[instant] = checked
    instants = sorted(by_instant)
    return {
        **({"source_ref": source_ref} if source_ref else {}),
        "window": _feature_history_window(
            requested_window=requested_window,
            requested_start=requested_start,
            requested_end=current_instant,
            instants=instants,
        ),
        "points": [by_instant[instant] for instant in instants],
    }


def _normalize_history_window(value: str) -> str:
    if value not in HISTORY_WINDOW_HOURS:
        raise ValueError(f"unsupported AssetDetailViewModel history_window: {value}")
    return value


def _feature_history_window(
    *,
    requested_window: str,
    requested_start: datetime,
    requested_end: datetime,
    instants: list[datetime],
) -> dict[str, Any]:
    actual_start = instants[0] if instants else None
    actual_end = instants[-1] if instants else None
    if not instants:
        coverage_status = "empty"
    elif actual_start and actual_start <= requested_start and actual_end and actual_end >= requested_end:
        coverage_status = "complete"
    else:
        coverage_status = "partial"
    return {
        "requested": requested_window,
        "anchor_observed_at": _format_utc_instant(requested_end),
        "requested_start": _format_utc_instant(requested_start),
        "requested_end": _format_utc_instant(requested_end),
        "actual_start": _format_utc_instant(actual_start) if actual_start else None,
        "actual_end": _format_utc_instant(actual_end) if actual_end else None,
        "point_count": len(instants),
        "coverage_status": coverage_status,
    }


def _format_utc_instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("AssetDetailViewModel timestamps must include a timezone offset")
    return parsed.astimezone(timezone.utc)


def _risk_point(point: dict[str, Any]) -> dict[str, Any]:
    source_ref = str(point.get("source_ref") or "")
    _reject_source_ref(source_ref, forbidden=FORBIDDEN_RISK_SOURCE_MARKERS)
    return {
        "observed_at": str(point["observed_at"]),
        "failure_probability": point["failure_probability"],
        "status_grade": _status_grade(point),
        "prediction_id": str(point["prediction_id"]),
        "source_kind": str(point.get("source_kind") or "runtime_inference"),
        "source_ref": source_ref,
    }


def _status_grade(source: dict[str, Any]) -> str | None:
    status = str(source.get("status_grade") or source.get("status") or "")
    if status == "data_quality_hold":
        return None
    return status


def _is_data_quality_hold(source: dict[str, Any]) -> bool:
    return str(source.get("status_grade") or source.get("status") or "") == "data_quality_hold"


def _view_model_gap(gap: dict[str, Any]) -> dict[str, str]:
    owner_domain = str(gap.get("owner_domain") or "report")
    if owner_domain in {"dashboard", "aggregate", "unknown"}:
        owner_domain = "report"
    return {
        "field": str(gap.get("field") or "unknown"),
        "reason": _gap_reason(gap),
        "owner_domain": _owner_domain(owner_domain),
    }


def _gap_reason(gap: dict[str, Any]) -> str:
    reason = str(gap.get("reason") or "unavailable")
    required_source = gap.get("required_source")
    display_policy = gap.get("display_policy")
    details = []
    if required_source:
        details.append(f"required_source={required_source}")
    if display_policy:
        details.append(f"display_policy={display_policy}")
    if details:
        return f"{reason} ({', '.join(details)})"
    return reason


def _data_status(
    result_artifact: dict[str, Any],
    provenance: dict[str, Any],
    data_status: dict[str, Any] | None,
) -> dict[str, Any]:
    explicit = data_status or result_artifact.get("data_status") or {}
    source = explicit.get("source")
    if source not in {"canonical", "fallback"}:
        source = (
            "canonical"
            if provenance.get("source_type") == "product_runtime_inference"
            else "fallback"
        )
    warnings = [
        str(warning)
        for warning in [
            *list(result_artifact.get("data_quality_warnings") or []),
            *list(explicit.get("warnings") or []),
        ]
    ]
    if "is_stale" in explicit:
        is_stale = bool(explicit["is_stale"])
    elif "is_stale" in result_artifact:
        is_stale = bool(result_artifact["is_stale"])
    else:
        is_stale = None
        warnings.append("data_status freshness fact unavailable")
    return {
        "source": source,
        "is_stale": is_stale,
        "is_data_quality_hold": _is_data_quality_hold(result_artifact)
        or bool(result_artifact.get("data_quality_warnings"))
        or bool(explicit.get("is_data_quality_hold")),
        "last_updated_at": explicit.get("last_updated_at") or result_artifact.get("observed_at"),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _criticality(value: Any) -> str | None:
    normalized = str(value or "").lower()
    if normalized in {"low", "medium", "high"}:
        return normalized
    return None


def _maintenance_context(asset: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    context = asset.get("maintenance_context") or {}
    last_maintenance_days_ago = context.get("last_maintenance_days_ago")
    similar_events_30d = context.get("similar_events_30d")
    open_work_order_exists = context.get("open_work_order_exists")
    result = {
        "last_maintenance_days_ago": int(last_maintenance_days_ago)
        if isinstance(last_maintenance_days_ago, int) and not isinstance(last_maintenance_days_ago, bool)
        else None,
        "similar_events_30d": int(similar_events_30d)
        if isinstance(similar_events_30d, int) and not isinstance(similar_events_30d, bool)
        else None,
        "open_work_order_exists": open_work_order_exists
        if isinstance(open_work_order_exists, bool)
        else None,
    }
    gaps = []
    for key, value in result.items():
        if value is None:
            gaps.append(
                {
                    "field": f"maintenance_context.{key}",
                    "reason": "maintenance_context_missing_or_unresolved",
                    "owner_domain": "maintenance",
                }
            )
    return result, gaps


def _inspection_targets(
    result_artifact: dict[str, Any],
    provenance: dict[str, Any],
    inspection_guidance: dict[str, dict[str, Any]],
    inspection_locations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    evidence_payload = result_artifact.get("evidence_payload") or {}
    component_hypotheses = evidence_payload.get("component_hypotheses") or []
    evidence_ref = _evidence_payload_reference(provenance)
    artifact_id = str(result_artifact.get("artifact_id") or result_artifact.get("asset_id") or "unknown")
    targets: list[dict[str, Any]] = []
    for index, item in enumerate(component_hypotheses):
        if not isinstance(item, dict):
            continue
        component_id = str(item.get("component_id") or "")
        if not component_id:
            continue
        basis = item.get("basis") if isinstance(item.get("basis"), list) else []
        location = inspection_locations.get(component_id) or {}
        target = {
            "target_id": f"inspection-target:{artifact_id}:{index + 1}",
            "component_id": component_id,
            "component_label": str(item.get("component_label") or component_id),
            "association": str(item.get("association") or "inspection_candidate"),
            "location_label": str(location.get("location_label") or "") or None,
            "inspection_method": str(location.get("inspection_method") or "") or None,
            "location_contract_id": str(location.get("contract_id") or "") or None,
            "location_source_ref": str(location.get("source_ref") or "") or None,
            "location_maturity": str(location.get("maturity") or "") or None,
            "basis_refs": [str(value) for value in basis],
            "source_ref": f"{evidence_ref}#component_hypotheses[{index}]"
            if evidence_ref
            else f"product-result-artifact://{artifact_id}#evidence_payload.component_hypotheses[{index}]",
            "unavailable_reason": None
            if location
            else "field_inspection_location_reference_unavailable",
        }
        guidance = inspection_guidance.get(component_id)
        if guidance:
            target["inspection_guidance"] = _inspection_guidance(guidance)
        targets.append(target)
    return targets


def _inspection_guidance(guidance: dict[str, Any]) -> dict[str, Any]:
    source_type = str(guidance.get("source_type") or "")
    if source_type not in {"demo_sop_fixture", "site_sop"}:
        raise ValueError(f"unsupported inspection guidance source_type: {source_type}")
    safety_level = str(guidance.get("safety_level") or "")
    if safety_level not in {"none", "caution", "permit_required", "shutdown_controlled"}:
        raise ValueError(f"unsupported inspection guidance safety_level: {safety_level}")
    return {
        "source_type": source_type,
        "sop_id": str(guidance.get("sop_id") or ""),
        "title": str(guidance.get("title") or ""),
        "version": str(guidance.get("version") or ""),
        "reference_location_label": str(guidance.get("reference_location_label") or ""),
        "suggested_check_method": str(guidance.get("suggested_check_method") or ""),
        "checklist_draft": [str(item) for item in guidance.get("checklist_draft") or []],
        "maintenance_review_prerequisites": _maintenance_review_prerequisites(
            guidance.get("maintenance_review_prerequisites") or {}
        ),
        "safety_level": safety_level,
        "requires_human_approval": bool(guidance.get("requires_human_approval")),
        "source_ref": str(guidance.get("source_ref") or ""),
        "disclaimer": str(guidance.get("disclaimer") or ""),
    }


def _maintenance_review_prerequisites(guidance: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": str(guidance.get("label") or ""),
        "review_conditions": [
            str(item) for item in guidance.get("review_conditions") or []
        ],
        "required_measurements": [
            str(item) for item in guidance.get("required_measurements") or []
        ],
        "human_review_questions": [
            str(item) for item in guidance.get("human_review_questions") or []
        ],
        "decision_boundary": str(guidance.get("decision_boundary") or ""),
    }


def _operation_context(asset: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    context = asset.get("operation_context") or {}
    result = dict(context) if isinstance(context, dict) else {}
    load_level = str(context.get("load_level") or "")
    if load_level not in {"low", "normal", "high"}:
        load_level = None
    runtime_hours_7d = context.get("runtime_hours_7d")
    production_impact = str(context.get("production_impact") or "")
    if production_impact not in {"none", "low", "medium", "high"}:
        production_impact = None
    result["load_level"] = load_level
    result["runtime_hours_7d"] = runtime_hours_7d if _is_number(runtime_hours_7d) else None
    result["production_impact"] = production_impact
    gaps = []
    for key in ("load_level", "runtime_hours_7d", "production_impact"):
        if result.get(key) is None:
            gaps.append(
                {
                    "field": f"operation_context.{key}",
                    "reason": "operation_context_missing_or_unresolved",
                    "owner_domain": "operations",
                }
            )
    return result, gaps


def _review_priority(
    *,
    risk: dict[str, Any],
    asset: dict[str, Any],
    maintenance_context: dict[str, Any],
    operation_context: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    status = risk.get("status_grade")
    criticality = asset.get("criticality")
    production_impact = operation_context.get("production_impact")
    if status is None or criticality is None or production_impact is None:
        return None, {
            "field": "review_priority",
            "reason": "review_priority_inputs_missing_or_unresolved",
            "owner_domain": "report",
        }
    reasons = [
        f"risk.status_grade={status}",
        f"asset.criticality={criticality}",
    ]
    source_fields = ["risk.status_grade", "asset.criticality"]
    open_work_order_exists = maintenance_context.get("open_work_order_exists")
    if open_work_order_exists is not None:
        reasons.append(f"maintenance_context.open_work_order_exists={open_work_order_exists}")
        source_fields.append("maintenance_context.open_work_order_exists")
    reasons.append(f"operation_context.production_impact={production_impact}")
    source_fields.append("operation_context.production_impact")

    if status == "critical" and criticality == "high":
        level = "immediate"
    elif status in {"critical", "warning"}:
        level = "high"
    elif status == "attention" or criticality == "high":
        level = "medium"
    else:
        level = "low"
    return {"level": level, "reasons": reasons, "source_fields": source_fields}, None


def _owner_domain(value: Any, *, default: str = "report") -> str:
    normalized = str(value or default)
    if normalized in {
        "diagnosis",
        "generator",
        "dataset",
        "equipment",
        "project",
        "operations",
        "maintenance",
        "report",
        "frontend",
        "unresolved",
    }:
        return normalized
    return default


def _reject_source_ref(source_ref: str, *, forbidden: tuple[str, ...]) -> None:
    if any(marker in source_ref for marker in forbidden):
        raise ValueError(f"unsupported AssetDetailViewModel source_ref: {source_ref}")


def _evidence_payload_reference(provenance: dict[str, Any]) -> str:
    reference = provenance.get("evidence_payload_reference")
    if isinstance(reference, dict):
        return str(reference.get("reference") or "")
    return str(reference or "")


def _evidence_snapshot_basis_from_artifact(
    artifact: dict[str, Any],
    *,
    event_id: str | None = None,
) -> dict[str, Any]:
    provenance = artifact.get("provenance") or {}
    lineage = artifact.get("lineage") or {}
    evidence_reference = provenance.get("evidence_payload_reference")
    if isinstance(evidence_reference, dict):
        evidence_reference = evidence_reference.get("reference")
    return {
        "artifact_id": artifact.get("artifact_id"),
        "evidence_payload_reference": str(evidence_reference or ""),
        "asset_id": artifact.get("asset_id"),
        "event_id": event_id or artifact.get("event_id"),
        "observed_at": artifact.get("observed_at"),
        "model_version": provenance.get("model_version"),
        "dataset_version": provenance.get("dataset_version"),
        "source_sha256": (
            artifact.get("source_sha256")
            or provenance.get("source_sha256")
            or lineage.get("source_sha256")
        ),
    }


def _optional(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source and source[key] is not None}


def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for gap in gaps:
        by_key.setdefault((str(gap.get("field")), str(gap.get("reason"))), gap)
    return list(by_key.values())

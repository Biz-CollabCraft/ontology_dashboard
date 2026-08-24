from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from typing import Protocol


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
        )


def compose_asset_detail_view_model(
    *,
    asset: dict[str, Any],
    result_artifact: dict[str, Any],
    feature_series: dict[str, dict[str, Any]] | None = None,
    runtime_prediction_history: list[dict[str, Any]] | None = None,
    equipment_history: list[dict[str, Any]] | None = None,
    data_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose the candidate AssetDetailViewModel from canonical contracts.

    The composer accepts Backend Observation/Feature Executor series and
    Diagnosis Runtime Prediction History Query results. It intentionally never
    reads raw gen_data files, canonical CSVs, or legacy timeline fixtures.
    """

    feature_series = feature_series or {}
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

    features, feature_gaps = _features_from_artifact(result_artifact, feature_series)
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

    return {
        "asset": {
            "asset_id": str(asset.get("asset_id") or result_artifact["asset_id"]),
            "asset_type": str(asset.get("asset_type") or result_artifact["asset_type"]),
            **_optional(asset, "display_name", "site_id", "cell_id"),
            "observed_at": str(asset.get("observed_at") or result_artifact["observed_at"]),
        },
        "risk": {
            "current": result_artifact.get("failure_probability"),
            "threshold": result_artifact.get("threshold"),
            "status_grade": _status_grade(result_artifact),
            "prediction_horizon_hours": result_artifact.get("prediction_horizon_hours"),
        },
        "risk_series": risk_series,
        "features": features,
        "equipment_history": equipment_history,
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
        )
        features.append(feature)
        if gap is not None:
            gaps.append(gap)
    return features, gaps


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
) -> tuple[dict[str, Any], dict[str, str] | None]:
    checked_history = _feature_history(history, current_observed_at=current_observed_at)
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
) -> dict[str, Any]:
    source_ref = str(history.get("source_ref") or "")
    _reject_source_ref(source_ref, forbidden=FORBIDDEN_FEATURE_SOURCE_MARKERS)
    current_instant = _timestamp_instant(current_observed_at)
    by_instant: dict[datetime, dict[str, Any]] = {}
    for point in history.get("points") or []:
        observed_at = str(point["observed_at"])
        instant = _timestamp_instant(observed_at)
        if instant >= current_instant:
            continue
        checked = {
            "observed_at": observed_at,
            "value": point.get("value"),
            "quality_status": str(point.get("quality_status") or "unknown"),
        }
        if instant in by_instant and by_instant[instant] != checked:
            raise ValueError(f"conflicting feature history points at instant={instant.isoformat()}")
        by_instant[instant] = checked
    return {
        **({"source_ref": source_ref} if source_ref else {}),
        "points": [by_instant[instant] for instant in sorted(by_instant)],
    }


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
    if owner_domain in {"dashboard", "operations", "aggregate", "unknown"}:
        owner_domain = "report"
    return {
        "field": str(gap.get("field") or "unknown"),
        "reason": _gap_reason(gap),
        "owner_domain": owner_domain,
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


def _reject_source_ref(source_ref: str, *, forbidden: tuple[str, ...]) -> None:
    if any(marker in source_ref for marker in forbidden):
        raise ValueError(f"unsupported AssetDetailViewModel source_ref: {source_ref}")


def _evidence_payload_reference(provenance: dict[str, Any]) -> str:
    reference = provenance.get("evidence_payload_reference")
    if isinstance(reference, dict):
        return str(reference.get("reference") or "")
    return str(reference or "")


def _optional(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source and source[key] is not None}


def _dedupe_gaps(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for gap in gaps:
        by_key.setdefault((str(gap.get("field")), str(gap.get("reason"))), gap)
    return list(by_key.values())

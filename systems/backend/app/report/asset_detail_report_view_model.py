from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


class AssetDetailReportReadPort(Protocol):
    """Read boundary for the candidate AssetDetailReportViewModel.

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
    ) -> dict[str, list[dict[str, Any]]]: ...

    def risk_prediction_results(
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


@dataclass(frozen=True)
class AssetDetailReportRequest:
    organization_id: str
    project_id: str
    workspace_id: str
    asset_id: str
    start: datetime
    end: datetime
    dataset_version_id: str | None = None
    grain: str = "raw"


class AssetDetailReportViewModelService:
    def __init__(self, read_port: AssetDetailReportReadPort) -> None:
        self.read_port = read_port

    def report_detail(self, request: AssetDetailReportRequest) -> dict[str, Any]:
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
        risk_history = self.read_port.risk_prediction_results(
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
        return compose_asset_detail_report_view_model(
            asset=asset or {
                "asset_id": request.asset_id,
                "asset_type": artifact["asset_type"],
                "observed_at": artifact["observed_at"],
            },
            result_artifact=artifact,
            feature_series=feature_series,
            risk_prediction_results=risk_history,
            equipment_history=history,
        )


def compose_asset_detail_report_view_model(
    *,
    asset: dict[str, Any],
    result_artifact: dict[str, Any],
    feature_series: dict[str, list[dict[str, Any]]] | None = None,
    risk_prediction_results: list[dict[str, Any]] | None = None,
    equipment_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose the candidate AssetDetailReportViewModel from canonical contracts.

    The composer accepts Generator-produced Observation/Feature series and
    Diagnosis-produced prediction_results history. It intentionally never reads
    raw gen_data files, canonical CSVs, or legacy timeline fixtures.
    """

    feature_series = feature_series or {}
    risk_prediction_results = risk_prediction_results or []
    equipment_history = equipment_history or []
    evidence_payload = result_artifact.get("evidence_payload") or {}
    provenance = result_artifact.get("provenance") or {}
    gaps = list(evidence_payload.get("evidence_gaps") or [])
    if "recommended_actions" in evidence_payload and not evidence_payload.get("recommended_actions"):
        gaps.append(
            {
                "field": "evidence_payload.recommended_actions",
                "reason": "Diagnosis recommendation policy did not produce a recommendation",
                "owner_domain": "diagnosis",
            }
        )

    features = _features_from_artifact(result_artifact, feature_series)
    if not any(feature["series"] for feature in features):
        gaps.append(
            {
                "field": "features[].series",
                "reason": "Generator Observation/Feature series is not connected yet",
                "owner_domain": "dataset",
            }
        )
    risk_series = [_risk_point(point) for point in risk_prediction_results]
    if not risk_series:
        gaps.append(
            {
                "field": "risk_series",
                "reason": "Backend Diagnosis prediction_results runtime history is not materialized yet",
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
        "data_status": {
            "source": "canonical",
            "is_stale": False,
            "is_data_quality_hold": result_artifact.get("status_grade") == "data_quality_hold"
            or bool(result_artifact.get("data_quality_warnings")),
            "last_updated_at": result_artifact.get("observed_at"),
            "warnings": list(result_artifact.get("data_quality_warnings") or []),
        },
    }


def _features_from_artifact(
    result_artifact: dict[str, Any],
    feature_series: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    evidence_payload = result_artifact.get("evidence_payload") or {}
    sensors = (evidence_payload.get("sensor_evidence") or {}).get("sensors") or {}
    top_factors = {
        str(factor.get("feature")): factor for factor in result_artifact.get("top_factors") or []
    }
    factor_evidence = {
        str(item.get("feature")): item for item in result_artifact.get("ranked_factor_evidence") or []
    }
    feature_keys = list(dict.fromkeys([*sensors.keys(), *top_factors.keys(), *feature_series.keys()]))
    return [
        _feature(
            key,
            sensor=sensors.get(key) or {},
            top_factor=top_factors.get(key),
            factor_evidence=factor_evidence.get(key),
            series=feature_series.get(key) or [],
        )
        for key in feature_keys
    ]


def _feature(
    key: str,
    *,
    sensor: dict[str, Any],
    top_factor: dict[str, Any] | None,
    factor_evidence: dict[str, Any] | None,
    series: list[dict[str, Any]],
) -> dict[str, Any]:
    checked_series = [_feature_series_point(point) for point in series]
    basis = sensor.get("basis") or {}
    baseline = None
    if basis:
        mean = basis.get("baseline_mean")
        std = basis.get("baseline_std")
        baseline = {
            "mean": mean,
            "std": std,
            "lower": mean - (2 * std),
            "upper": mean + (2 * std),
            "reference": str(basis.get("baseline_reference") or ""),
        }
    return {
        "key": key,
        "label": str(sensor.get("display_name") or (factor_evidence or {}).get("display_name") or key),
        "unit": str(sensor.get("unit") or (factor_evidence or {}).get("unit") or ""),
        "current": sensor.get("current") if "current" in sensor else (factor_evidence or {}).get("value"),
        "baseline": baseline,
        "series": checked_series,
        "top_factor": None
        if top_factor is None
        else {
            "rank": top_factor["rank"],
            "contribution": top_factor.get("signed_contribution", top_factor.get("contribution")),
            "direction": top_factor["direction"],
            "explanation_method": top_factor["explanation_method"],
            "evidence_field_id": (factor_evidence or {}).get("evidence_field_id"),
        },
    }


def _feature_series_point(point: dict[str, Any]) -> dict[str, Any]:
    source_ref = str(point.get("source_ref") or "")
    _reject_source_ref(source_ref, forbidden=FORBIDDEN_FEATURE_SOURCE_MARKERS)
    return {
        "observed_at": str(point["observed_at"]),
        "value": point.get("value"),
        **_optional(point, "quality_status", "source_ref"),
    }


def _risk_point(point: dict[str, Any]) -> dict[str, Any]:
    source_ref = str(point.get("source_ref") or "")
    if not source_ref.startswith("prediction-results://prediction_results/"):
        raise ValueError("risk_series source_ref must use prediction_results")
    _reject_source_ref(source_ref, forbidden=FORBIDDEN_RISK_SOURCE_MARKERS)
    return {
        "observed_at": str(point["observed_at"]),
        "failure_probability": point["failure_probability"],
        "status_grade": _status_grade(point),
        "prediction_id": str(point["prediction_id"]),
        "source_kind": str(point.get("source_kind") or "runtime_inference"),
        "source_ref": source_ref,
    }


def _status_grade(source: dict[str, Any]) -> str:
    status = str(source.get("status_grade") or source.get("status") or "")
    if status == "data_quality_hold":
        return "critical"
    return status


def _reject_source_ref(source_ref: str, *, forbidden: tuple[str, ...]) -> None:
    if any(marker in source_ref for marker in forbidden):
        raise ValueError(f"unsupported AssetDetailReportViewModel source_ref: {source_ref}")


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

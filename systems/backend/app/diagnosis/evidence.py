from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from .contracts import DISPLAY_NAMES, UNITS, derive_features, project_root
from .predictor import Prediction, Predictor, configured_predictor

NORMAL_RANGES = {
    "tool_wear_min": "0–180",
    "temperature_difference_k": "8.6–12.0",
    "mechanical_power_w": "3,500–9,000",
    "overstrain_index": "0–11,000",
    "torque_nm": "10–60",
}


class ContextProvider(Protocol):
    provider_name: str

    def get_context(self, equipment_id: str, failure_type: str) -> dict[str, Any]: ...


class FixtureContextProvider:
    provider_name = "fixture"

    def __init__(self, path: str | Path | None = None) -> None:
        source = Path(path) if path else project_root() / "data" / "fixtures" / "maintenance_context.json"
        self.payload = json.loads(source.read_text(encoding="utf-8"))

    def get_context(self, equipment_id: str, failure_type: str) -> dict[str, Any]:
        context = self.payload["contexts"].get(failure_type) or self.payload["contexts"]["uncertain"]
        return {
            "provider": self.provider_name,
            "version": self.payload["version"],
            "source_type": self.payload["source_type"],
            "source_refs": list(context["source_refs"]),
            "checklist": list(context["checklist"]),
            "recommended_actions": list(context["recommended_actions"]),
        }


def _factor_value(feature: str, observation: dict[str, Any], derived: dict[str, float]) -> float:
    if feature in derived:
        return float(derived[feature])
    return float(observation[feature])


def _source_type(feature: str) -> str:
    return "derived" if feature in {"temperature_difference_k", "mechanical_power_w", "overstrain_index"} else "observed"


def build_evidence_package(
    fixture: dict[str, Any],
    *,
    predictor: Predictor | None = None,
    context_provider: ContextProvider | None = None,
) -> dict[str, Any]:
    model = predictor or configured_predictor()
    prediction: Prediction = model.predict(fixture)
    provider = context_provider or FixtureContextProvider()
    observation = fixture["observation"]
    derived = {} if prediction.quality_issues else derive_features(observation)

    scored = prediction.factors[:5]
    total_score = sum(item.score for item in scored) or 1.0
    factors = [
        {
            "evidence_field_id": f"factor.{index + 1}.{item.feature}",
            "feature": item.feature,
            "display_name": DISPLAY_NAMES[item.feature],
            "value": round(_factor_value(item.feature, observation, derived), 4),
            "unit": UNITS[item.feature],
            "normal_range": NORMAL_RANGES[item.feature],
            "direction": item.direction,
            "contribution": round(item.score / total_score, 6),
            "source_type": _source_type(item.feature),
        }
        for index, item in enumerate(scored)
    ]

    history = fixture["history"]
    start = history[0]["timestamp"] if history else observation["timestamp"]
    context = provider.get_context(fixture["equipment"]["equipment_id"], prediction.predicted_failure_type)
    package = {
        "schema_version": "1.0",
        "evidence_id": f"EVD-{fixture['event_id']}",
        "event_id": fixture["event_id"],
        "scenario_id": fixture["scenario_id"],
        "equipment": fixture["equipment"],
        "model": {
            "model_version": prediction.model_version,
            "policy_version": model.policy["policy_version"],
            "mode": "trained" if prediction.model_artifact else "deterministic_fallback",
            "artifact": prediction.model_artifact,
        },
        "status": prediction.risk_band,
        "recommended_decision": prediction.recommended_decision,
        "confidence": prediction.confidence,
        "failure_probability": prediction.probability,
        "threshold": float(model.policy["decision_threshold"]),
        "predicted_failure_type": prediction.predicted_failure_type,
        "observation": {**observation, **derived},
        "history": history,
        "detected_interval": {"start": start, "end": observation["timestamp"]},
        "top_factors": factors,
        "maintenance_context": context,
        "data_quality_warnings": prediction.quality_issues,
        "lineage": {
            "fixture_id": fixture["scenario_id"],
            "fixture_schema_version": fixture["schema_version"],
            "sensor_source": "observed-compatible fixture",
            "context_source": f"{context['provider']}:{context['version']}",
        },
        "generated_at": observation["timestamp"],
    }
    validate_evidence_package(package)
    return package


def build_product_result_artifact(fixture: dict[str, Any], *, predictor: Predictor | None = None) -> dict[str, Any]:
    """Create the product runtime Result Artifact owned by backend/diagnosis.

    The shape intentionally remains semantically compatible with the Canonical
    V3.1 ``result-artifact-v1.0`` regression fixture in gen_data, but this value
    is generated from the current observation at product runtime.
    """

    model = predictor or configured_predictor()
    prediction = model.predict(fixture)
    observed_at = fixture["observation"]["timestamp"]
    asset_id = fixture["equipment"]["equipment_id"]
    prediction_id = f"{asset_id}#{observed_at}"
    status = prediction.risk_band
    action = {
        "critical": {"action": "immediate_inspection_and_stop_review", "priority": "urgent"},
        "warning": {"action": "inspect_within_current_shift", "priority": "high"},
        "attention": {"action": "request_inspection", "priority": "medium"},
        "normal": {"action": "continue_monitoring", "priority": "normal"},
        "data_quality_hold": {"action": "hold_for_data_check", "priority": "high"},
    }[status]
    factors = [
        {
            "rank": rank,
            "feature": item.feature,
            "feature_value": item.raw_value,
            "signed_contribution": item.score if item.direction == "risk_up" else -item.score,
            "direction": item.direction,
            "explanation_method": "deterministic_component_score",
        }
        for rank, item in enumerate(prediction.factors[:3], start=1)
    ]
    dataset_version = (
        str(prediction.model_artifact["dataset_version"])
        if prediction.model_artifact
        else str(fixture.get("dataset_version") or "fixture-compatibility")
    )
    artifact = {
        "artifact_id": f"RESULT#{prediction_id}",
        "artifact_type": "predictive_maintenance_result",
        "schema_version": "result-artifact-v1.0",
        "asset_id": asset_id,
        "asset_type": str(fixture.get("asset_type") or "cnc"),
        "observed_at": observed_at,
        "prediction_horizon_hours": 24,
        "prediction_task": "binary_failure_within_horizon",
        "failure_probability": prediction.probability,
        "predicted_failure_type": prediction.predicted_failure_type,
        "status_grade": status,
        "confidence": None if prediction.probability is None else round(abs(prediction.probability - 0.5) * 2.0, 6),
        "top_factors": factors,
        "recommended_action": action,
        "provenance": {
            "dataset_version": dataset_version,
            "model_version": prediction.model_version,
            "prediction_id": prediction_id,
            "source_type": "product_runtime_inference",
            "canonical_source_mutated": False,
            "model_artifact": prediction.model_artifact,
        },
    }
    validate_product_result_artifact(artifact)
    return artifact


def validate_product_result_artifact(artifact: dict[str, Any]) -> None:
    schema = json.loads(
        (project_root() / "contracts" / "schemas" / "product-result-artifact.schema.json").read_text(encoding="utf-8")
    )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(artifact),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors
        )
        raise ValueError(f"Product Result Artifact schema validation failed: {rendered}")


def validate_evidence_package(package: dict[str, Any]) -> None:
    schema = json.loads((project_root() / "contracts" / "schemas" / "evidence-package.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(package), key=lambda item: list(item.absolute_path))
    if errors:
        rendered = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors
        )
        raise ValueError(f"evidence schema validation failed: {rendered}")

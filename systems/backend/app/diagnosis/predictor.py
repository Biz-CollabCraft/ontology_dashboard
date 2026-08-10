from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from .artifact_provider import LocalModelArtifactProvider
from .contracts import audit_fixture, derive_features


DEFAULT_POLICY_PATH = Path(__file__).with_name("threshold_policy.json")
_TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
_HEURISTIC_DEFAULT_ENVIRONMENTS = {"local", "demo", "test"}


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


@dataclass(frozen=True)
class FactorScore:
    feature: str
    raw_value: float
    score: float
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature": self.feature,
            "raw_value": self.raw_value,
            "score": self.score,
            "direction": self.direction,
        }


@dataclass(frozen=True)
class Prediction:
    model_version: str
    probability: float | None
    risk_band: str
    recommended_decision: str
    confidence: str
    predicted_failure_type: str
    factors: list[FactorScore]
    quality_issues: list[dict[str, str]]
    model_artifact: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "probability": self.probability,
            "risk_band": self.risk_band,
            "recommended_decision": self.recommended_decision,
            "confidence": self.confidence,
            "predicted_failure_type": self.predicted_failure_type,
            "factors": [factor.to_dict() for factor in self.factors],
            "quality_issues": self.quality_issues,
            "model_artifact": self.model_artifact,
        }


class Predictor(Protocol):
    model_version: str
    policy: dict[str, Any]

    def predict(self, fixture: dict[str, Any]) -> Prediction: ...


class HeuristicPredictor:
    """Deterministic fixture predictor and offline fallback.

    It is intentionally separate from the trained benchmark model. The trained model
    demonstrates reproducible model development; this predictor guarantees that Gold
    product scenarios remain available without a binary artifact or external service.
    """

    model_version = "fixture-heuristic-v1"

    def __init__(self, policy_path: str | Path | None = None) -> None:
        path = Path(policy_path) if policy_path else DEFAULT_POLICY_PATH
        self.policy = json.loads(path.read_text(encoding="utf-8"))

    def predict(self, fixture: dict[str, Any]) -> Prediction:
        quality_issues = [issue.to_dict() for issue in audit_fixture(fixture)]
        if quality_issues:
            return Prediction(
                model_version=self.model_version,
                probability=None,
                risk_band="data_quality_hold",
                recommended_decision="hold_for_data_check",
                confidence="unavailable",
                predicted_failure_type="unavailable",
                factors=[],
                quality_issues=quality_issues,
                model_artifact=None,
            )

        observation = fixture["observation"]
        derived = derive_features(observation)
        wear = float(observation["tool_wear_min"])
        torque = float(observation["torque_nm"])
        speed = float(observation["rotational_speed_rpm"])
        temp_gap = derived["temperature_difference_k"]
        power = derived["mechanical_power_w"]
        overstrain = derived["overstrain_index"]

        components = {
            "tool_wear_min": _sigmoid((wear - 185.0) / 18.0),
            "temperature_difference_k": _sigmoid((8.5 - temp_gap) / 0.5) * _sigmoid((1400.0 - speed) / 80.0),
            "mechanical_power_w": _sigmoid((power - 9500.0) / 1200.0),
            "overstrain_index": _sigmoid((overstrain - 12000.0) / 1500.0),
            "torque_nm": _sigmoid((torque - 62.0) / 8.0),
        }
        ordered = sorted(components.items(), key=lambda item: item[1], reverse=True)
        primary = ordered[0][1]
        secondary = ordered[1][1]
        probability = min(0.99, max(0.01, 0.05 + 0.72 * primary + 0.18 * secondary))

        criticality = fixture["equipment"]["criticality"]
        adjustment = float(self.policy["criticality_adjustments"][criticality])
        attention = float(self.policy["severity_rules"]["attention"]) + adjustment
        warning = float(self.policy["severity_rules"]["warning"]) + adjustment
        # Equipment criticality can surface an event earlier, but it must not
        # silently lower the critical/shutdown-review boundary.
        critical = float(self.policy["severity_rules"]["critical"])

        if probability >= critical:
            risk_band = "critical"
        elif probability >= warning:
            risk_band = "warning"
        elif probability >= attention:
            risk_band = "attention"
        else:
            risk_band = "normal"

        if risk_band == "normal":
            failure_type = "none"
        elif risk_band == "critical" and (components["mechanical_power_w"] > 0.75 or components["overstrain_index"] > 0.75):
            failure_type = "power_or_overstrain_failure"
        elif primary > 0.55 and secondary > 0.55 and primary - secondary < 0.25:
            failure_type = "multi_factor_risk"
        else:
            top_feature = ordered[0][0]
            failure_type = {
                "tool_wear_min": "tool_wear_failure",
                "temperature_difference_k": "heat_dissipation_failure",
                "mechanical_power_w": "power_or_overstrain_failure",
                "overstrain_index": "power_or_overstrain_failure",
                "torque_nm": "power_or_overstrain_failure",
            }[top_feature]

        if risk_band == "normal":
            confidence = "high"
        elif risk_band == "critical":
            confidence = "high"
        elif risk_band == "attention":
            confidence = "low"
            failure_type = "uncertain"
        elif primary - secondary < 0.25:
            confidence = "medium"
        else:
            confidence = "high"

        raw_values = {
            "tool_wear_min": wear,
            "temperature_difference_k": temp_gap,
            "mechanical_power_w": power,
            "overstrain_index": overstrain,
            "torque_nm": torque,
        }
        factors = [
            FactorScore(
                feature=name,
                raw_value=raw_values[name],
                score=float(round(score, 6)),
                direction="risk_up" if score >= 0.5 else "risk_down",
            )
            for name, score in ordered
        ]
        decision = self.policy["decision_mapping"][risk_band]
        return Prediction(
            model_version=self.model_version,
            probability=float(round(probability, 6)),
            risk_band=risk_band,
            recommended_decision=decision,
            confidence=confidence,
            predicted_failure_type=failure_type,
            factors=factors,
            quality_issues=[],
            model_artifact=None,
        )


class ArtifactPredictor:
    """Runtime inference against a versioned Model Artifact provided by URI."""

    def __init__(self, artifact_uri: str | Path, policy_path: str | Path | None = None) -> None:
        loaded = LocalModelArtifactProvider(artifact_uri).load()
        self.loaded = loaded
        self.model = loaded.model
        self.manifest = loaded.manifest
        self.feature_schema = loaded.feature_schema
        self.model_version = str(self.manifest["model_version"])
        policy = Path(policy_path) if policy_path else DEFAULT_POLICY_PATH
        self.policy = json.loads(policy.read_text(encoding="utf-8"))

    def predict(self, fixture: dict[str, Any]) -> Prediction:
        quality_issues = [issue.to_dict() for issue in audit_fixture(fixture)]
        if quality_issues:
            return Prediction(
                model_version=self.model_version,
                probability=None,
                risk_band="data_quality_hold",
                recommended_decision="hold_for_data_check",
                confidence="unavailable",
                predicted_failure_type="unavailable",
                factors=[],
                quality_issues=quality_issues,
                model_artifact=self._artifact_reference(),
            )

        observation = fixture["observation"]
        derived = derive_features(observation)
        feature_names = list(self.feature_schema.get("features") or [])
        if not feature_names:
            raise ValueError("Model Artifact feature schema has no features")
        values = {**observation, **derived}
        missing = [feature for feature in feature_names if feature not in values]
        if missing:
            raise ValueError(f"runtime observation is incompatible with Model Artifact features: {missing}")
        frame = pd.DataFrame([{feature: values[feature] for feature in feature_names}])
        probability = float(self.model.predict_proba(frame)[:, 1][0])

        criticality = fixture["equipment"]["criticality"]
        adjustment = float(self.policy["criticality_adjustments"][criticality])
        attention = float(self.policy["severity_rules"]["attention"]) + adjustment
        warning = float(self.policy["severity_rules"]["warning"]) + adjustment
        critical = float(self.policy["severity_rules"]["critical"])
        if probability >= critical:
            risk_band = "critical"
        elif probability >= warning:
            risk_band = "warning"
        elif probability >= attention:
            risk_band = "attention"
        else:
            risk_band = "normal"

        distance = abs(probability - 0.5) * 2.0
        confidence = "high" if distance >= 0.6 else "medium" if distance >= 0.3 else "low"
        return Prediction(
            model_version=self.model_version,
            probability=float(round(probability, 6)),
            risk_band=risk_band,
            recommended_decision=self.policy["decision_mapping"][risk_band],
            confidence=confidence,
            predicted_failure_type="failure_risk" if probability >= 0.5 else "none",
            factors=[],
            quality_issues=[],
            model_artifact=self._artifact_reference(),
        )

    def _artifact_reference(self) -> dict[str, Any]:
        return {
            "artifact_type": self.manifest["artifact_type"],
            "artifact_schema_version": self.manifest["artifact_schema_version"],
            "model_id": self.manifest["model_id"],
            "model_version": self.manifest["model_version"],
            "dataset_version": self.manifest["dataset_version"],
            "feature_schema_version": self.manifest["feature_schema_version"],
            "checksum": self.manifest["checksum"],
        }


def configured_predictor() -> Predictor:
    """Resolve runtime inference from injected artifact or explicit MVP fallback."""

    artifact_uri = os.getenv("MODEL_ARTIFACT_URI", "").strip()
    if artifact_uri:
        return ArtifactPredictor(artifact_uri)

    configured_fallback = os.getenv("ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK", "").strip().lower()
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    fallback_enabled = (
        configured_fallback in _TRUTHY_ENV_VALUES
        if configured_fallback
        else app_env in _HEURISTIC_DEFAULT_ENVIRONMENTS
    )
    if not fallback_enabled:
        raise RuntimeError(
            "MODEL_ARTIFACT_URI is required because heuristic fallback is disabled "
            f"for APP_ENV={app_env!r}; set "
            "ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK=1 only when an explicit fallback is intended"
        )
    return HeuristicPredictor()

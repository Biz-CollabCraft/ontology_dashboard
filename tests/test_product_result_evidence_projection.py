from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.diagnosis.contracts import load_fixture
from app.diagnosis.evidence import (
    build_evidence_package,
    build_product_result_artifact,
    validate_product_result_artifact,
)
from app.diagnosis.predictor import HeuristicPredictor
from ontology_dashboard.product_result_evidence_projection import (
    EVENT_EVIDENCE_CONTRACT_TYPE,
    EVENT_EVIDENCE_SCHEMA_VERSION,
    event_evidence_projection_to_legacy_evidence,
    extend_product_result_artifact,
    extended_artifact_to_event_evidence_projection,
    reference_pdm_evidence_to_artifact_extension,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "product_result_evidence_projection"


def load_projection_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def assert_absent_hidden_truth(payload: object) -> None:
    if isinstance(payload, dict):
        assert "evaluation_truth" not in payload
        assert "hidden_truth" not in payload
        for value in payload.values():
            assert_absent_hidden_truth(value)
    elif isinstance(payload, list):
        for value in payload:
            assert_absent_hidden_truth(value)


def test_reference_pdm_evidence_preserves_sensor_basis_and_strips_hidden_truth() -> None:
    package = load_projection_fixture("pdm-reference-evidence-critical.json")

    extension = reference_pdm_evidence_to_artifact_extension(package)

    rotation = extension["sensor_evidence"]["sensors"]["rotation_raw"]
    assert rotation["z_score"] == -2.9
    assert rotation["basis"]["baseline_mean"] == 1600.0
    assert rotation["basis"]["baseline_std"] == 67.327
    assert rotation["basis"]["baseline_n"] == 240
    assert "canonical-ai4i-physics-v3.1" in rotation["basis"]["baseline_reference"]
    assert extension["component_hypotheses"][0]["component_id"] == "rotating_assembly"
    assert extension["recommended_actions"][0]["requires_human_approval"] is True
    assert_absent_hidden_truth(extension)


def test_extend_product_result_artifact_adds_optional_extension_without_mutating_source() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-004-power-overstrain-critical.json")
    predictor = HeuristicPredictor()
    result = build_product_result_artifact(fixture, predictor=predictor)
    result_before = json.loads(json.dumps(result))
    evidence = build_evidence_package(fixture, predictor=predictor)

    extended = extend_product_result_artifact(result, {"evidence_package": evidence, "reference": "GS-004"})

    assert result == result_before
    validate_product_result_artifact(extended)
    assert extended["schema_version"] == "result-artifact-v1.0"
    assert extended["provenance"]["canonical_source_mutated"] is False
    assert extended["provenance"]["evidence_extension_reference"]["reference"] == "GS-004"
    payload = extended["evidence_payload"]
    assert payload["event_id"] == "EVT-GS-004"
    assert payload["threshold"] == evidence["threshold"]
    assert payload["top_factors"][0]["evidence_field_id"].startswith("factor.1.")
    assert payload["sensor_evidence"]["sensors"]["torque_nm"]["z_score"] is None
    assert payload["sensor_evidence"]["sensors"]["torque_nm"]["basis"]["baseline_n"] == 0
    assert any(item["field_id"].startswith("sensor_evidence.sensors.") for item in payload["source_fields"])


def test_extend_product_result_artifact_rejects_mutated_or_missing_source_flag() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-004-power-overstrain-critical.json")
    predictor = HeuristicPredictor()
    result = build_product_result_artifact(fixture, predictor=predictor)

    mutated = json.loads(json.dumps(result))
    mutated["provenance"]["canonical_source_mutated"] = True
    with pytest.raises(ValueError, match="canonical_source_mutated must be false"):
        extend_product_result_artifact(mutated)

    missing = json.loads(json.dumps(result))
    del missing["provenance"]["canonical_source_mutated"]
    with pytest.raises(ValueError, match="canonical_source_mutated must be false"):
        extend_product_result_artifact(missing)


def test_artifact_top_factors_override_reference_factors_without_losing_reference_sensors() -> None:
    package = load_projection_fixture("pdm-reference-evidence-critical.json")
    artifact = {
        "artifact_id": "RESULT#CMP-S03-L03-01#2026-08-01T00:00:00+09:00",
        "artifact_type": "predictive_maintenance_result",
        "schema_version": "result-artifact-v1.0",
        "asset_id": "CMP-S03-L03-01",
        "asset_type": "compressor",
        "observed_at": "2026-08-01T00:00:00+09:00",
        "prediction_horizon_hours": 24,
        "prediction_task": "binary_failure_within_horizon",
        "failure_probability": 0.82,
        "predicted_failure_type": "power_or_overstrain_failure",
        "status_grade": "warning",
        "confidence": 0.64,
        "top_factors": [
            {
                "rank": 1,
                "feature": "torque_nm",
                "feature_value": 88.0,
                "signed_contribution": 0.55,
                "direction": "risk_up",
                "explanation_method": "deterministic_component_score",
            }
        ],
        "recommended_action": {"action": "inspect_within_current_shift", "priority": "high"},
        "provenance": {
            "dataset_version": "runtime-dataset",
            "model_version": "runtime-model",
            "prediction_id": "runtime-prediction",
            "source_type": "product_runtime_inference",
            "canonical_source_mutated": False,
            "model_artifact": None,
        },
    }

    extended = extend_product_result_artifact(artifact, {"pdm_reference_package": package})
    projection = extended_artifact_to_event_evidence_projection(extended)

    assert extended["evidence_payload"]["top_factors"][0]["feature"] == "torque_nm"
    assert projection["assessment"]["top_factors"][0]["feature"] == "torque_nm"
    factor_trace = [
        item["field_id"]
        for item in projection["report_projection"]["evidence_trace"]
        if item["field_id"].startswith("factor.")
    ]
    assert factor_trace == ["factor.1.torque_nm"]
    assert "factor.1.rotation_raw" not in factor_trace
    source_field_ids = {item["field_id"] for item in projection["report_projection"]["evidence_trace"]}
    assert all(
        basis in source_field_ids
        for hypothesis in projection["report_projection"]["inspection_targets"]
        for basis in hypothesis["basis"]
    )
    assert projection["report_projection"]["inspection_targets"][0]["basis"] == ["factor.1.torque_nm"]
    assert projection["report_projection"]["sensor_cards"][0]["sensor_id"] == "rotation_raw"
    assert projection["report_projection"]["sensor_cards"][0]["basis"]["baseline_n"] == 240


def test_boolean_observation_values_are_not_treated_as_sensors() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-004-power-overstrain-critical.json")
    predictor = HeuristicPredictor()
    result = build_product_result_artifact(fixture, predictor=predictor)
    context = {
        "evidence_package": {
            "event_id": "EVT-BOOL-SENSOR",
            "scenario_id": "BOOL-SENSOR",
            "observation": {
                "timestamp": "2026-08-01T00:00:00+09:00",
                "is_valid": True,
                "torque_nm": 12.0,
            },
            "history": [
                {
                    "timestamp": "2026-07-31T23:55:00+09:00",
                    "is_valid": False,
                    "torque_nm": 10.0,
                }
            ],
            "detected_interval": {
                "start": "2026-07-31T23:55:00+09:00",
                "end": "2026-08-01T00:00:00+09:00",
            },
            "threshold": 0.65,
        }
    }

    extended = extend_product_result_artifact(result, context)
    sensors = extended["evidence_payload"]["sensor_evidence"]["sensors"]

    assert "is_valid" not in sensors
    assert sensors["torque_nm"]["window_mean"] == 11.0


def test_top_factor_direction_fallback_uses_signed_contribution_before_magnitude() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-004-power-overstrain-critical.json")
    predictor = HeuristicPredictor()
    result = build_product_result_artifact(fixture, predictor=predictor)
    result["top_factors"] = [
        {
            "rank": 1,
            "feature": "torque_nm",
            "feature_value": 12.0,
            "signed_contribution": -0.25,
            "explanation_method": "deterministic_component_score",
        }
    ]

    extended = extend_product_result_artifact(result)
    factor = extended["evidence_payload"]["top_factors"][0]

    assert factor["direction"] == "risk_down"
    assert factor["contribution"] == 1.0


def test_extended_artifact_to_event_evidence_projection_matches_expected_reference_slice() -> None:
    package = load_projection_fixture("pdm-reference-evidence-critical.json")
    expected = load_projection_fixture("expected-event-evidence-projection-critical.json")
    artifact = {
        "artifact_id": "RESULT#CMP-S03-L03-01#2026-08-01T00:00:00+09:00",
        "artifact_type": "predictive_maintenance_result",
        "schema_version": "result-artifact-v1.0",
        "asset_id": "CMP-S03-L03-01",
        "asset_type": "compressor",
        "observed_at": "2026-08-01T00:00:00+09:00",
        "prediction_horizon_hours": 24,
        "prediction_task": "binary_failure_within_horizon",
        "failure_probability": 0.92,
        "predicted_failure_type": "power_or_overstrain_failure",
        "status_grade": "critical",
        "confidence": 0.84,
        "top_factors": [
            {
                "rank": 1,
                "feature": "rotation_raw",
                "feature_value": 1820.0,
                "signed_contribution": 0.42,
                "direction": "risk_up",
                "explanation_method": "deterministic_component_score",
            }
        ],
        "recommended_action": {"action": "immediate_inspection_and_stop_review", "priority": "urgent"},
        "provenance": {
            "dataset_version": "canonical-ai4i-physics-v3.1",
            "model_version": "canonical-ai4i-physics-v3.1",
            "prediction_id": "CMP-S03-L03-01#2026-08-01T00:00:00+09:00",
            "source_type": "product_runtime_inference",
            "canonical_source_mutated": False,
            "model_artifact": None,
        },
    }

    extended = extend_product_result_artifact(
        artifact,
        {"pdm_reference_package": package, "reference": "pdm-reference-evidence-critical.json"},
    )
    projection = extended_artifact_to_event_evidence_projection(extended)

    assert projection["schema_version"] == expected["schema_version"] == EVENT_EVIDENCE_SCHEMA_VERSION
    assert projection["contract_type"] == expected["contract_type"] == EVENT_EVIDENCE_CONTRACT_TYPE
    assert projection["event_id"] == expected["event_id"]
    assert projection["subject"] == expected["subject"]
    assert projection["assessment"]["status"] == expected["assessment"]["status"]
    assert projection["assessment"]["recommended_decision"] == expected["assessment"]["recommended_decision"]
    assert projection["assessment"]["threshold"] == expected["assessment"]["threshold"]
    assert projection["report_projection"]["sensor_cards"][0]["z_score"] == -2.9
    assert projection["report_projection"]["sensor_cards"][0]["basis"]["baseline_n"] == 240
    assert projection["report_projection"]["inspection_targets"][0]["component_id"] == "rotating_assembly"
    assert projection["artifact_reference"]["evidence_extension_reference"]["reference"] == "pdm-reference-evidence-critical.json"
    assert_absent_hidden_truth(projection)


def test_legacy_projection_passes_current_evidence_schema() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")
    predictor = HeuristicPredictor()
    result = build_product_result_artifact(fixture, predictor=predictor)
    evidence = build_evidence_package(fixture, predictor=predictor)
    extended = extend_product_result_artifact(result, {"evidence_package": evidence, "reference": "GS-002"})
    projection = extended_artifact_to_event_evidence_projection(extended)

    legacy = event_evidence_projection_to_legacy_evidence(projection)

    schema = json.loads((ROOT / "schemas" / "evidence-package.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(legacy)) == []
    assert legacy["schema_version"] == "1.0"
    assert legacy["event_id"] == evidence["event_id"]
    assert legacy["status"] == evidence["status"]
    assert legacy["recommended_decision"] == evidence["recommended_decision"]
    assert legacy["threshold"] == evidence["threshold"]
    assert legacy["lineage"]["product_result_artifact"]["artifact_id"] == result["artifact_id"]
    assert_absent_hidden_truth(legacy)

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ontology_dashboard.product_result_evidence_projection import (
    EVENT_EVIDENCE_CONTRACT_TYPE,
    EVENT_EVIDENCE_SCHEMA_VERSION,
    event_evidence_projection_to_legacy_evidence,
    product_result_artifact_to_event_evidence_projection,
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


def enriched_critical_artifact() -> dict:
    return {
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
        "evidence_payload": {
            "event_id": "EVT-PDM-REF-004",
            "scenario_id": "PDM-REF-004",
            "equipment": {
                "equipment_id": "CMP-S03-L03-01",
                "display_name": "압축기 S03-L03-01",
                "line": "S03-L03",
                "criticality": "high",
                "assigned_engineer": "최민호",
            },
            "observation": {
                "timestamp": "2026-08-01T00:00:00+09:00",
                "rotation_raw": 1820.0,
            },
            "history": [
                {"timestamp": "2026-07-31T23:55:00+09:00", "rotation_raw": 1788.0},
                {"timestamp": "2026-08-01T00:00:00+09:00", "rotation_raw": 1820.0},
            ],
            "detected_interval": {
                "start": "2026-07-31T18:00:00+09:00",
                "end": "2026-08-01T00:00:00+09:00",
            },
            "generated_at": "2026-08-01T00:00:00+09:00",
            "threshold": 0.65,
            "model": {
                "policy_version": "canonical-ai4i-physics-v3.1",
                "mode": "deterministic_fallback",
            },
            "sensor_evidence": {
                "window": {
                    "start": "2026-07-31T18:00:00+09:00",
                    "end": "2026-08-01T00:00:00+09:00",
                },
                "window_rows": 12,
                "sensors": {
                    "rotation_raw": {
                        "display_name": "회전 상태",
                        "unit": "rpm",
                        "current": 1820.0,
                        "window_mean": 1795.25,
                        "z_score": -2.9,
                        "basis": {
                            "baseline_mean": 1600.0,
                            "baseline_std": 67.327,
                            "baseline_n": 240,
                            "baseline_reference": (
                                "all_valid_rows canonical-ai4i-physics-v3.1 "
                                "compressor_sensor_observation.csv"
                            ),
                        },
                    }
                },
            },
            "top_factors": [
                {
                    "evidence_field_id": "factor.1.rotation_raw",
                    "feature": "rotation_raw",
                    "display_name": "회전 상태",
                    "value": 1820.0,
                    "unit": "rpm",
                    "normal_range": "baseline z-score -2.0..2.0",
                    "direction": "risk_up",
                    "contribution": 0.42,
                    "source_type": "observed",
                }
            ],
            "component_hypotheses": [
                {
                    "component_id": "rotating_assembly",
                    "component_label": "회전/진동 계통",
                    "association": "inspection_candidate",
                    "basis": ["factor.1.rotation_raw", "sensor_evidence.sensors.rotation_raw"],
                }
            ],
            "status_flags": {
                "multiple_risk_factors": False,
                "insufficient_data": False,
            },
            "maintenance_context": {
                "provider": "pdm-mvp-reference",
                "version": "2026-08-11",
                "source_type": "semantic_regression_reference",
                "source_refs": ["semantic-regression:pdm-mvp-critical"],
                "checklist": ["회전부 상태 확인", "진동 및 베어링 상태 확인"],
                "recommended_actions": ["다음 교대 전 현장 점검", "필요 시 정지 검토"],
            },
            "recommended_actions": [
                {
                    "action_id": "inspect_rotating_assembly",
                    "label": "회전/진동 계통 점검",
                    "kind": "inspect",
                    "requires_human_approval": True,
                    "basis": ["factor.1.rotation_raw", "sensor_evidence.sensors.rotation_raw"],
                }
            ],
            "source_fields": [
                {
                    "field_id": "factor.1.rotation_raw",
                    "source_path": "evidence_payload.top_factors[0]",
                    "label": "회전 상태",
                    "description": "위험 판단에 사용된 상위 요인",
                },
                {
                    "field_id": "sensor_evidence.sensors.rotation_raw",
                    "source_path": "evidence_payload.sensor_evidence.sensors.rotation_raw",
                    "label": "회전 상태",
                    "description": "센서 관측 및 baseline 근거",
                },
            ],
            "evidence_gaps": [],
            "data_quality_warnings": [],
            "lineage": {
                "fixture_id": "PDM-REF-004",
                "fixture_schema_version": "producer-enriched-fixture-v1",
                "sensor_source": "pdm-mvp semantic regression reference",
                "context_source": "pdm-mvp-reference:2026-08-11",
                "semantic_reference_file": "semantic_regression/pdm-mvp-semantic-reference-critical.json",
            },
            "hidden_truth": {"actual_failure": True},
        },
        "provenance": {
            "dataset_version": "canonical-ai4i-physics-v3.1",
            "model_version": "canonical-ai4i-physics-v3.1",
            "prediction_id": "CMP-S03-L03-01#2026-08-01T00:00:00+09:00",
            "source_type": "product_runtime_inference",
            "canonical_source_mutated": False,
            "model_artifact": None,
            "evidence_payload_reference": {
                "source": "product_result_artifact",
                "reference": "producer-enriched-critical",
                "generated_by": "systems.backend.app.diagnosis.evidence",
            },
        },
        "evaluation_truth": {"fixture_label": "critical"},
    }


def test_product_result_artifact_to_event_evidence_projection_matches_expected_reference_slice() -> None:
    expected = load_projection_fixture("expected-event-evidence-projection-critical.json")
    projection = product_result_artifact_to_event_evidence_projection(enriched_critical_artifact())

    assert projection["schema_version"] == expected["schema_version"] == EVENT_EVIDENCE_SCHEMA_VERSION
    assert projection["contract_type"] == expected["contract_type"] == EVENT_EVIDENCE_CONTRACT_TYPE
    assert projection["event_id"] == expected["event_id"]
    assert projection["subject"] == expected["subject"]
    assert projection["artifact_reference"]["evidence_payload_reference"] == expected["artifact_reference"][
        "evidence_payload_reference"
    ]
    assert projection["assessment"]["status"] == expected["assessment"]["status"]
    assert projection["assessment"]["recommended_decision"] == expected["assessment"]["recommended_decision"]
    assert projection["assessment"]["threshold"] == expected["assessment"]["threshold"]
    assert projection["assessment"]["top_factors"] == expected["assessment"]["top_factors"]
    assert projection["report_projection"]["sensor_cards"][0]["z_score"] == -2.9
    assert projection["report_projection"]["sensor_cards"][0]["basis"]["baseline_n"] == 240
    assert projection["report_projection"]["inspection_targets"][0]["component_id"] == "rotating_assembly"
    assert_absent_hidden_truth(projection)


def test_projection_rejects_mutated_or_missing_source_flag() -> None:
    artifact = enriched_critical_artifact()

    mutated = json.loads(json.dumps(artifact))
    mutated["provenance"]["canonical_source_mutated"] = True
    with pytest.raises(ValueError, match="canonical_source_mutated must be false"):
        product_result_artifact_to_event_evidence_projection(mutated)

    missing = json.loads(json.dumps(artifact))
    del missing["provenance"]["canonical_source_mutated"]
    with pytest.raises(ValueError, match="canonical_source_mutated must be false"):
        product_result_artifact_to_event_evidence_projection(missing)


def test_projection_requires_enriched_evidence_payload() -> None:
    artifact = enriched_critical_artifact()
    del artifact["evidence_payload"]

    with pytest.raises(ValueError, match="evidence_payload is required"):
        product_result_artifact_to_event_evidence_projection(artifact)


def test_projection_does_not_create_evidence_trace_when_payload_has_none() -> None:
    artifact = enriched_critical_artifact()
    artifact["evidence_payload"]["source_fields"] = []

    projection = product_result_artifact_to_event_evidence_projection(artifact)

    assert projection["report_projection"]["evidence_trace"] == []
    assert projection["assessment"]["top_factors"][0]["evidence_field_id"] == "factor.1.rotation_raw"


def test_legacy_projection_passes_current_evidence_schema() -> None:
    projection = product_result_artifact_to_event_evidence_projection(enriched_critical_artifact())

    legacy = event_evidence_projection_to_legacy_evidence(projection)

    schema = json.loads((ROOT / "schemas" / "evidence-package.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(legacy)) == []
    assert legacy["schema_version"] == "1.0"
    assert legacy["event_id"] == projection["event_id"]
    assert legacy["status"] == projection["assessment"]["status"]
    assert legacy["recommended_decision"] == projection["assessment"]["recommended_decision"]
    assert legacy["threshold"] == projection["assessment"]["threshold"]
    assert legacy["lineage"]["product_result_artifact"]["artifact_id"] == projection["artifact_reference"]["artifact_id"]
    assert_absent_hidden_truth(legacy)

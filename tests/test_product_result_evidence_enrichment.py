from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from systems.backend.app.diagnosis.contracts import load_fixture
from systems.backend.app.diagnosis.evidence import FixtureContextProvider, build_product_result_artifact
from systems.backend.app.diagnosis.evidence_enrichment import validate_evidence_payload_invariants
from systems.backend.app.diagnosis.predictor import HeuristicPredictor

ROOT = Path(__file__).resolve().parents[1]


class MissingContextProvider:
    provider_name = "missing"

    def get_context(self, equipment_id: str, failure_type: str) -> dict[str, Any] | None:
        return None


def unresolved_basis_refs(evidence_payload: dict[str, Any]) -> set[str]:
    source_field_ids = {field["field_id"] for field in evidence_payload["source_fields"]}
    basis_refs: set[str] = set()
    for hypothesis in evidence_payload["component_hypotheses"]:
        basis_refs.update(hypothesis["basis"])
    for action in evidence_payload["recommended_actions"]:
        basis_refs.update(action["basis"])
    return basis_refs - source_field_ids


def semantic_reference_payload() -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "product_result_evidence_projection"
            / "semantic_regression"
            / "pdm-mvp-semantic-reference-critical.json"
        ).read_text(encoding="utf-8")
    )


def test_product_result_artifact_includes_producer_evidence_payload_without_default_maintenance_context() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")

    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    payload = artifact["evidence_payload"]

    assert set(payload) == {
        "sensor_evidence",
        "component_hypotheses",
        "status_flags",
        "recommended_actions",
        "source_fields",
        "evidence_gaps",
    }
    assert artifact["provenance"]["evidence_payload_reference"] == {
        "source": "product_result_artifact",
        "reference": artifact["artifact_id"],
        "generated_by": "systems.backend.app.diagnosis.evidence_enrichment",
    }
    assert payload["sensor_evidence"]["sensors"]["tool_wear_min"]["current"] == 230.0
    assert payload["sensor_evidence"]["sensors"]["tool_wear_min"]["basis"]["baseline_n"] == 5
    assert "maintenance_context" not in payload
    assert any(gap["field"] == "evidence_payload.maintenance_context" for gap in payload["evidence_gaps"])
    assert unresolved_basis_refs(payload) == set()


def test_product_result_artifact_uses_maintenance_context_only_when_provider_is_explicit() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")

    artifact = build_product_result_artifact(
        fixture,
        predictor=HeuristicPredictor(),
        context_provider=FixtureContextProvider(),
    )
    payload = artifact["evidence_payload"]

    assert payload["maintenance_context"]["provider"] == "fixture"
    assert not any(gap["field"] == "evidence_payload.maintenance_context" for gap in payload["evidence_gaps"])


def test_evidence_payload_preserves_pdm_mvp_reference_semantics_without_copying_values() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")
    semantic_reference = semantic_reference_payload()

    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    payload = artifact["evidence_payload"]

    assert set(payload["sensor_evidence"]) == set(semantic_reference["sensor_evidence"])
    assert set(next(iter(payload["sensor_evidence"]["sensors"].values()))["basis"]) == set(
        next(iter(semantic_reference["sensor_evidence"]["sensors"].values()))["basis"]
    )
    assert payload["component_hypotheses"][0]["association"] == semantic_reference["component_hypotheses"][0][
        "association"
    ]
    assert set(payload["recommended_actions"][0]) == set(semantic_reference["recommended_actions"][0])
    assert payload["source_fields"][0]["field_id"].startswith("factor.1.")
    assert any(field["field_id"].startswith("sensor_evidence.sensors.") for field in payload["source_fields"])


def test_product_result_artifact_excludes_non_numeric_observation_values_from_sensor_evidence() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")
    fixture["observation"]["operator_confirmed"] = True

    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    sensors = artifact["evidence_payload"]["sensor_evidence"]["sensors"]

    assert "product_type" not in sensors
    assert "operator_confirmed" not in sensors
    assert "tool_wear_min" in sensors


def test_product_result_artifact_preserves_signed_contribution_direction_fallback() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-001-normal-stable.json")

    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())

    assert any(factor["signed_contribution"] < 0 for factor in artifact["top_factors"])
    for factor in artifact["top_factors"]:
        if factor["signed_contribution"] < 0:
            assert factor["direction"] == "risk_down"
        assert factor["evidence_field_id"].startswith(f"factor.{factor['rank']}.")
        assert 0 <= factor["contribution"] <= 1


def test_product_result_artifact_records_gap_when_maintenance_context_is_missing() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")

    artifact = build_product_result_artifact(
        fixture,
        predictor=HeuristicPredictor(),
        context_provider=MissingContextProvider(),  # type: ignore[arg-type]
    )
    payload = artifact["evidence_payload"]

    assert "maintenance_context" not in payload
    assert {
        "gap_id": "gap.maintenance_context.unavailable",
        "field": "evidence_payload.maintenance_context",
        "reason": "missing_source",
        "required_source": "maintenance_context_provider",
        "owner_domain": "maintenance",
        "display_policy": "show_as_unavailable",
    } in payload["evidence_gaps"]


def test_product_result_artifact_records_data_quality_gaps_without_zero_filling() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-007-invalid-sensor-data.json")

    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    payload = artifact["evidence_payload"]

    assert artifact["status_grade"] == "data_quality_hold"
    assert artifact["failure_probability"] is None
    assert "air_temperature_k" not in payload["sensor_evidence"]["sensors"]
    assert any(gap["gap_id"].startswith("gap.data_quality.") for gap in payload["evidence_gaps"])


def test_evidence_payload_invariant_rejects_unmapped_basis_refs() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")
    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    artifact["evidence_payload"]["recommended_actions"][0]["basis"].append("factor.999.missing")

    with pytest.raises(ValueError, match="basis refs are not in source_fields"):
        validate_evidence_payload_invariants(artifact["evidence_payload"])


def test_evidence_payload_invariant_rejects_null_maintenance_context_without_gap() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")
    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    artifact["evidence_payload"]["maintenance_context"] = None
    artifact["evidence_payload"]["evidence_gaps"] = [
        gap
        for gap in artifact["evidence_payload"]["evidence_gaps"]
        if gap["field"] != "evidence_payload.maintenance_context"
    ]

    with pytest.raises(ValueError, match="missing maintenance_context gap"):
        validate_evidence_payload_invariants(artifact["evidence_payload"])


def test_evidence_payload_does_not_overwrite_official_judgement_fields() -> None:
    fixture = load_fixture(ROOT / "data" / "fixtures" / "GS-002-tool-wear-warning.json")
    artifact = build_product_result_artifact(fixture, predictor=HeuristicPredictor())
    before = {
        key: json.loads(json.dumps(artifact[key]))
        for key in (
            "status_grade",
            "failure_probability",
            "confidence",
            "predicted_failure_type",
            "top_factors",
            "recommended_action",
        )
    }

    artifact["evidence_payload"]["top_factors"] = [{"feature": "payload_should_not_win"}]
    artifact["evidence_payload"]["recommended_action"] = {"action": "payload_should_not_win"}

    assert {
        key: artifact[key]
        for key in (
            "status_grade",
            "failure_probability",
            "confidence",
            "predicted_failure_type",
            "top_factors",
            "recommended_action",
        )
    } == before

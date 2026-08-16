from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ontology_dashboard.product_result_evidence_projection import (
    EVENT_EVIDENCE_CONTRACT_TYPE,
    EVENT_EVIDENCE_SCHEMA_VERSION,
    event_evidence_projection_to_grounded_report,
    event_evidence_projection_to_legacy_evidence,
    inspection_request_action_descriptor,
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
    return load_projection_fixture("producer-enriched-critical-artifact.json")


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
    assert projection["report_projection"]["display_labels"]["confidence_label"] == "high"
    assert projection["report_projection"]["sensor_cards"][0]["z_score"] == -2.9
    assert projection["report_projection"]["sensor_cards"][0]["basis"]["baseline_n"] == 240
    assert projection["report_projection"]["inspection_targets"][0]["component_id"] == "rotating_assembly"
    assert_absent_hidden_truth(projection)


def test_enriched_artifact_fixture_keeps_evidence_payload_to_producer_candidate_fields() -> None:
    payload_keys = set(enriched_critical_artifact()["evidence_payload"])

    assert payload_keys == {
        "sensor_evidence",
        "component_hypotheses",
        "status_flags",
        "maintenance_context",
        "recommended_actions",
        "source_fields",
        "evidence_gaps",
    }


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
    assert projection["assessment"]["top_factors"][0]["feature"] == "rotation_raw"


def test_payload_fields_do_not_override_artifact_judgement_or_subject() -> None:
    artifact = enriched_critical_artifact()
    artifact["evidence_payload"]["top_factors"] = [{"feature": "payload_should_not_win"}]
    artifact["evidence_payload"]["equipment"] = {
        "equipment_id": "PAYLOAD-ASSET",
        "display_name": "payload display label",
    }

    projection = product_result_artifact_to_event_evidence_projection(artifact)

    assert projection["assessment"]["top_factors"] == artifact["top_factors"]
    assert projection["artifact_reference"]["top_factor_count"] == len(artifact["top_factors"])
    assert "ranked_factor_evidence" not in projection["artifact_reference"]
    assert projection["subject"] == {
        "equipment_id": "CMP-S03-L03-01",
        "display_name": "CMP-S03-L03-01",
        "asset_type": "compressor",
    }


def test_legacy_projection_rejects_unmapped_product_result_factors() -> None:
    projection = product_result_artifact_to_event_evidence_projection(enriched_critical_artifact())

    with pytest.raises(ValueError, match="producer-normalized top_factors"):
        event_evidence_projection_to_legacy_evidence(projection)


def test_legacy_projection_uses_ranked_factor_evidence_for_current_schema() -> None:
    artifact = enriched_critical_artifact()
    projection = product_result_artifact_to_event_evidence_projection(artifact)

    legacy = event_evidence_projection_to_legacy_evidence(
        projection,
        ranked_factor_evidence=artifact["ranked_factor_evidence"],
    )

    schema = json.loads((ROOT / "contracts" / "schemas" / "evidence-package.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(legacy)) == []
    assert legacy["schema_version"] == "1.0"
    assert legacy["event_id"] == projection["event_id"]
    assert legacy["status"] == projection["assessment"]["status"]
    assert legacy["recommended_decision"] == projection["assessment"]["recommended_decision"]
    assert legacy["threshold"] == projection["assessment"]["threshold"]
    assert legacy["top_factors"] == artifact["ranked_factor_evidence"]
    assert legacy["top_factors"][0]["normal_range"] == "baseline z-score -2.0..2.0"
    assert legacy["lineage"]["product_result_artifact"]["artifact_id"] == projection["artifact_reference"]["artifact_id"]
    assert_absent_hidden_truth(legacy)


def test_projection_to_grounded_report_uses_ranked_factor_evidence_and_schema() -> None:
    artifact = enriched_critical_artifact()
    projection = product_result_artifact_to_event_evidence_projection(artifact)
    equipment = {
        "equipment_id": projection["subject"]["equipment_id"],
        "display_name": "압축기 라인 3",
        "asset_type": "compressor",
        "criticality": "high",
        "estimated_downtime_minutes": 45,
    }

    report = event_evidence_projection_to_grounded_report(
        projection,
        "manager",
        ranked_factor_evidence=artifact["ranked_factor_evidence"],
        event_id="EVT-CMP-CRITICAL",
        scenario_id="CMP-CRITICAL",
        equipment=equipment,
    )

    schema = json.loads((ROOT / "contracts" / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(report.model_dump(mode="json"))) == []
    assert report.event_id == "EVT-CMP-CRITICAL"
    assert report.status == projection["assessment"]["status"]
    assert report.recommended_decision == projection["assessment"]["recommended_decision"]
    assert "factor.1.rotation_raw" in report.citations
    assert all(section.evidence_field_ids for section in report.sections)


def test_inspection_request_action_descriptor_is_grounded_in_projection_source_fields() -> None:
    projection = product_result_artifact_to_event_evidence_projection(enriched_critical_artifact())

    action = inspection_request_action_descriptor(projection)

    source_field_ids = {field["field_id"] for field in projection["report_projection"]["evidence_trace"]}
    assert action["action_id"] == "add_maintenance_note"
    assert action["kind"] == "maintenance_note"
    assert action["requires_human_approval"] is True
    assert action["source_refs"]
    assert set(action["source_refs"]).issubset(source_field_ids)


def test_projection_display_confidence_prefers_canonical_label_over_numeric_value() -> None:
    artifact = enriched_critical_artifact()
    artifact["confidence"] = 0.84
    artifact["confidence_label"] = "medium"

    projection = product_result_artifact_to_event_evidence_projection(artifact)

    assert projection["assessment"]["confidence"] == "medium"
    assert projection["report_projection"]["display_labels"]["confidence_label"] == "medium"

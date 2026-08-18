from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from ontology_dashboard.product_result_evidence_projection import (
    EVENT_EVIDENCE_CONTRACT_TYPE,
    EVENT_EVIDENCE_SCHEMA_VERSION,
    add_maintenance_note_descriptor,
    event_evidence_projection_to_grounded_report,
    event_evidence_projection_to_legacy_evidence,
    product_result_artifact_to_event_evidence_projection,
    validate_grounded_report_source_refs,
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


def test_projection_display_confidence_prefers_canonical_label_over_numeric_value() -> None:
    artifact = enriched_critical_artifact()
    artifact["confidence"] = 0.84
    artifact["confidence_label"] = "medium"

    projection = product_result_artifact_to_event_evidence_projection(artifact)

    assert projection["assessment"]["confidence"] == "medium"
    assert projection["report_projection"]["display_labels"]["confidence_label"] == "medium"


@pytest.mark.parametrize(
    ("role", "locale", "expected_sections"),
    [
        ("manager", "ko-KR", {"manager-status", "manager-evidence"}),
        ("engineer", "en-US", {"engineer-factors", "engineer-checklist", "engineer-manager-summary"}),
    ],
)
def test_event_evidence_projection_maps_to_current_grounded_report_with_grounded_role_blocks(
    role: str,
    locale: str,
    expected_sections: set[str],
) -> None:
    projection = product_result_artifact_to_event_evidence_projection(enriched_critical_artifact())
    before_mapping = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    report = event_evidence_projection_to_grounded_report(projection, role, locale=locale)  # type: ignore[arg-type]

    schema = json.loads((ROOT / "contracts" / "schemas" / "report.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(report.model_dump(mode="json"))) == []
    assert report.event_id == projection["event_id"]
    assert report.status == projection["assessment"]["status"]
    assert report.confidence == projection["assessment"]["confidence"]
    assert report.recommended_decision == projection["assessment"]["recommended_decision"]
    assert {section.section_id for section in report.sections} == expected_sections
    assert json.dumps(projection, ensure_ascii=False, sort_keys=True) == before_mapping

    source_field_ids = {item["field_id"] for item in projection["report_projection"]["evidence_trace"]}
    report_refs = set(report.citations)
    for section in report.sections:
        report_refs.update(section.evidence_field_ids)
    for action in report.actions:
        report_refs.update(action.source_refs)
    assert report_refs <= source_field_ids
    validate_grounded_report_source_refs(projection, report)

    descriptor = next(action for action in report.actions if action.action_id == "add_maintenance_note")
    assert descriptor.kind == "maintenance_note"
    assert descriptor.requires_human_approval is True
    assert set(descriptor.source_refs) <= source_field_ids
    assert all("automatic" not in action.label.lower() for action in report.actions)
    assert_absent_hidden_truth(report.model_dump(mode="json"))


def test_report_mapper_does_not_create_risk_values_or_ungrounded_action_refs() -> None:
    projection = product_result_artifact_to_event_evidence_projection(enriched_critical_artifact())
    projection["report_projection"]["recommended_actions"][0]["basis"].append("synthetic.risk.count")

    report = event_evidence_projection_to_grounded_report(projection, "manager")
    payload = report.model_dump(mode="json")

    assert report.status == "critical"
    assert report.recommended_decision == "review_shutdown"
    assert "failure_probability" not in payload
    assert "0.92" not in json.dumps(payload, ensure_ascii=False)
    assert "synthetic.risk.count" not in json.dumps(payload, ensure_ascii=False)
    assert "권한자의 정지 검토 요청" in next(
        action.label for action in report.actions if action.kind == "review_shutdown"
    )


def test_maintenance_note_descriptor_is_omitted_without_grounded_source_fields() -> None:
    projection = product_result_artifact_to_event_evidence_projection(enriched_critical_artifact())
    projection["report_projection"]["evidence_trace"] = []

    assert add_maintenance_note_descriptor(projection) is None
    report = event_evidence_projection_to_grounded_report(projection, "engineer")
    assert all(action.action_id != "add_maintenance_note" for action in report.actions)


def test_grounded_report_and_legacy_projection_keep_truth_fields_absent() -> None:
    artifact = enriched_critical_artifact()
    artifact["evaluation_truth"] = {"should_not_surface": True}
    artifact["evidence_payload"]["hidden_truth"] = {"should_not_surface": True}
    projection = product_result_artifact_to_event_evidence_projection(artifact)
    report = event_evidence_projection_to_grounded_report(projection, "engineer")
    legacy = event_evidence_projection_to_legacy_evidence(
        projection,
        ranked_factor_evidence=artifact["ranked_factor_evidence"],
    )

    assert_absent_hidden_truth(projection)
    assert_absent_hidden_truth(report.model_dump(mode="json"))
    assert_absent_hidden_truth(legacy)

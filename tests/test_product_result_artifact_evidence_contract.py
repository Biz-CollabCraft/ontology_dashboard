from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "product_result_evidence_projection"
EVIDENCE_PAYLOAD_KEYS = {
    "sensor_evidence",
    "component_hypotheses",
    "status_flags",
    "maintenance_context",
    "recommended_actions",
    "source_fields",
    "evidence_gaps",
}
FORBIDDEN_PAYLOAD_KEYS = {
    "event_id",
    "scenario_id",
    "equipment",
    "observation",
    "history",
    "detected_interval",
    "generated_at",
    "threshold",
    "model",
    "top_factors",
    "data_quality_warnings",
    "lineage",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def product_result_artifact_schema() -> dict:
    return load_json(ROOT / "schemas" / "product-result-artifact.schema.json")


def producer_enriched_artifact() -> dict:
    return load_json(PROJECTION_FIXTURE_ROOT / "producer-enriched-critical-artifact.json")


def schema_errors(payload: dict) -> list:
    return list(Draft202012Validator(product_result_artifact_schema()).iter_errors(payload))


def test_product_result_artifact_schema_accepts_existing_v1_artifact_without_evidence_payload() -> None:
    artifact = producer_enriched_artifact()
    artifact.pop("evidence_payload")
    artifact["provenance"].pop("evidence_payload_reference")

    assert schema_errors(artifact) == []


def test_product_result_artifact_schema_accepts_optional_evidence_payload_contract() -> None:
    artifact = producer_enriched_artifact()

    assert set(artifact["evidence_payload"]) == EVIDENCE_PAYLOAD_KEYS
    assert schema_errors(artifact) == []


def test_product_result_artifact_schema_rejects_dashboard_fixture_fields_inside_evidence_payload() -> None:
    artifact = producer_enriched_artifact()
    artifact["evidence_payload"]["event_id"] = "EVT-SHOULD-NOT-BE-HERE"

    errors = schema_errors(artifact)

    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_product_result_artifact_evidence_payload_contract_documents_forbidden_keys() -> None:
    artifact = producer_enriched_artifact()

    assert set(artifact["evidence_payload"]).isdisjoint(FORBIDDEN_PAYLOAD_KEYS)


def test_product_result_artifact_schema_keeps_event_identity_out_of_root_contract() -> None:
    properties = product_result_artifact_schema()["properties"]

    assert "event_id" not in properties
    assert "scenario_id" not in properties
    assert "equipment" not in properties
    assert "observation" not in properties
    assert "history" not in properties
    assert "detected_interval" not in properties
    assert "lineage" not in properties


def test_product_result_artifact_schema_allows_threshold_and_generated_at_as_optional_root_fields() -> None:
    properties = product_result_artifact_schema()["properties"]

    assert properties["threshold"]["type"] == ["number", "null"]
    assert properties["generated_at"]["type"] == "string"


def test_product_result_artifact_evidence_reference_targets_diagnosis_enrichment_helper() -> None:
    artifact = producer_enriched_artifact()

    assert artifact["provenance"]["evidence_payload_reference"] == {
        "source": "product_result_artifact",
        "reference": "producer-enriched-critical",
        "generated_by": "systems.backend.app.diagnosis.evidence_enrichment",
    }

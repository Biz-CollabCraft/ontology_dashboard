from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from systems.backend.app.report.asset_detail_report_view_model import (
    compose_asset_detail_report_view_model,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "contracts" / "schemas" / "asset-detail-report-view-model.schema.json").read_text()
)
ARTIFACT = json.loads(
    (
        ROOT
        / "tests"
        / "fixtures"
        / "product_result_evidence_projection"
        / "producer-enriched-critical-artifact.json"
    ).read_text()
)


def test_composer_builds_view_model_without_generator_raw_file_dependency() -> None:
    payload = compose_asset_detail_report_view_model(
        asset={
            "asset_id": "CMP-S03-L03-01",
            "asset_type": "compressor",
            "display_name": "압축기 S03-L03-01",
            "site_id": "S03",
            "cell_id": "L03",
            "observed_at": "2026-08-01T00:00:00+09:00",
        },
        result_artifact=ARTIFACT,
        feature_series={
            "rotation_raw": [
                {
                    "observed_at": "2026-08-01T00:00:00+09:00",
                    "value": 1820.0,
                    "quality_status": "good",
                    "source_ref": "observation://CMP-S03-L03-01.rotation_raw/2026-08-01T00:00:00+09:00",
                }
            ]
        },
        risk_prediction_results=[
            {
                "observed_at": "2026-08-01T00:00:00+09:00",
                "failure_probability": 0.92,
                "status_grade": "critical",
                "prediction_id": "CMP-S03-L03-01#2026-08-01T00:00:00+09:00",
                "source_kind": "runtime_inference",
                "source_ref": "prediction-results://prediction_results/CMP-S03-L03-01/2026-08-01T00:00:00+09:00",
            }
        ],
    )

    assert list(Draft202012Validator(SCHEMA).iter_errors(payload)) == []
    assert payload["risk_series"][0]["source_ref"].startswith(
        "prediction-results://prediction_results/"
    )
    assert "features[].series" not in {gap["field"] for gap in payload["evidence"]["gaps"]}
    assert "risk_series" not in {gap["field"] for gap in payload["evidence"]["gaps"]}


@pytest.mark.parametrize(
    "source_ref",
    [
        "gen_data/canonical/model_outputs/prediction_timeline.jsonl",
        "pm_prediction_timeline://CMP-S03-L03-01",
        "legacy://precomputed_prediction_timeline/CMP-S03-L03-01",
        "/timeline/CMP-S03-L03-01",
    ],
)
def test_composer_rejects_non_prediction_results_risk_series_sources(source_ref: str) -> None:
    with pytest.raises(ValueError, match="prediction_results|unsupported"):
        compose_asset_detail_report_view_model(
            asset={"asset_id": "CMP-S03-L03-01", "asset_type": "compressor"},
            result_artifact=ARTIFACT,
            risk_prediction_results=[
                {
                    "observed_at": "2026-08-01T00:00:00+09:00",
                    "failure_probability": 0.92,
                    "status_grade": "critical",
                    "prediction_id": "prediction-1",
                    "source_ref": source_ref,
                }
            ],
        )


def test_composer_rejects_raw_generator_feature_series_sources() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        compose_asset_detail_report_view_model(
            asset={"asset_id": "CMP-S03-L03-01", "asset_type": "compressor"},
            result_artifact=ARTIFACT,
            feature_series={
                "rotation_raw": [
                    {
                        "observed_at": "2026-08-01T00:00:00+09:00",
                        "value": 1820.0,
                        "source_ref": "gen_data/output/sensor/CMP-S03-L03-01/_log.jsonl",
                    }
                ]
            },
        )


def test_composer_marks_missing_series_as_gaps_without_synthesizing_values() -> None:
    payload = compose_asset_detail_report_view_model(
        asset={"asset_id": "CMP-S03-L03-01", "asset_type": "compressor"},
        result_artifact=ARTIFACT,
    )

    gap_fields = {gap["field"] for gap in payload["evidence"]["gaps"]}
    assert {"features[].series", "risk_series", "equipment_history"} <= gap_fields
    assert payload["risk_series"] == []
    assert all(feature["series"] == [] for feature in payload["features"])


def test_composer_preserves_empty_recommendation_as_gap_without_synthesizing_action() -> None:
    artifact = json.loads(json.dumps(ARTIFACT))
    artifact["evidence_payload"]["recommended_actions"] = []

    payload = compose_asset_detail_report_view_model(
        asset={"asset_id": "CMP-S03-L03-01", "asset_type": "compressor"},
        result_artifact=artifact,
    )

    gap_fields = {gap["field"] for gap in payload["evidence"]["gaps"]}
    assert "evidence_payload.recommended_actions" in gap_fields
    assert "recommended_actions" not in payload
    assert "available_actions" not in payload

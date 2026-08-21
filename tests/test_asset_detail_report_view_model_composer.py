from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from systems.backend.app.report.asset_detail_report_view_model import (
    AssetDetailReportRequest,
    AssetDetailReportViewModelService,
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


class FakeAssetDetailReportReadPort:
    def __init__(
        self,
        *,
        artifact: dict[str, Any] | None = ARTIFACT,
        risk_source_ref: str = "prediction-results://prediction_results/CMP-S03-L03-01/2026-08-01T00:00:00+09:00",
    ) -> None:
        self.artifact = artifact
        self.risk_source_ref = risk_source_ref
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def asset_summary(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("asset_summary", kwargs))
        return {
            "asset_id": kwargs["asset_id"],
            "asset_type": "compressor",
            "display_name": "압축기 S03-L03-01",
            "site_id": "S03",
            "cell_id": "L03",
            "observed_at": "2026-08-01T00:00:00+09:00",
        }

    def latest_result_artifact(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(("latest_result_artifact", kwargs))
        return self.artifact

    def feature_series(self, **kwargs: Any) -> dict[str, list[dict[str, Any]]]:
        self.calls.append(("feature_series", kwargs))
        return {
            "rotation_raw": [
                {
                    "observed_at": "2026-08-01T00:00:00+09:00",
                    "value": 1820.0,
                    "quality_status": "good",
                    "source_ref": "observation://CMP-S03-L03-01.rotation_raw/2026-08-01T00:00:00+09:00",
                }
            ]
        }

    def risk_prediction_results(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("risk_prediction_results", kwargs))
        return [
            {
                "observed_at": "2026-08-01T00:00:00+09:00",
                "failure_probability": 0.92,
                "status_grade": "critical",
                "prediction_id": "CMP-S03-L03-01#2026-08-01T00:00:00+09:00",
                "source_kind": "runtime_inference",
                "source_ref": self.risk_source_ref,
            }
        ]

    def equipment_history(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("equipment_history", kwargs))
        return []


def _request() -> AssetDetailReportRequest:
    return AssetDetailReportRequest(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        asset_id="CMP-S03-L03-01",
        start=datetime(2026, 7, 31, 18, tzinfo=timezone.utc),
        end=datetime(2026, 8, 1, 0, tzinfo=timezone.utc),
        dataset_version_id="canonical-ai4i-physics-v3.1",
        grain="1h",
    )


def test_service_reads_only_contracted_sources_and_returns_schema_valid_view_model() -> None:
    port = FakeAssetDetailReportReadPort()
    service = AssetDetailReportViewModelService(port)

    payload = service.report_detail(_request())

    assert list(Draft202012Validator(SCHEMA).iter_errors(payload)) == []
    assert [name for name, _ in port.calls] == [
        "asset_summary",
        "latest_result_artifact",
        "feature_series",
        "risk_prediction_results",
        "equipment_history",
    ]
    feature_call = dict(port.calls)["feature_series"]
    risk_call = dict(port.calls)["risk_prediction_results"]
    assert feature_call["dataset_version_id"] == "canonical-ai4i-physics-v3.1"
    assert feature_call["grain"] == "1h"
    assert risk_call["start"] == _request().start
    assert risk_call["end"] == _request().end


def test_service_rejects_mismatched_result_artifact_asset() -> None:
    artifact = json.loads(json.dumps(ARTIFACT))
    artifact["asset_id"] = "CMP-OTHER"
    service = AssetDetailReportViewModelService(
        FakeAssetDetailReportReadPort(artifact=artifact)
    )

    with pytest.raises(ValueError, match="asset_id"):
        service.report_detail(_request())


def test_service_does_not_accept_legacy_risk_history_sources_from_port() -> None:
    service = AssetDetailReportViewModelService(
        FakeAssetDetailReportReadPort(risk_source_ref="pm_prediction_timeline://CMP-S03-L03-01")
    )

    with pytest.raises(ValueError, match="prediction_results|unsupported"):
        service.report_detail(_request())


def test_service_requires_product_result_artifact() -> None:
    service = AssetDetailReportViewModelService(
        FakeAssetDetailReportReadPort(artifact=None)
    )

    with pytest.raises(KeyError, match="result artifact"):
        service.report_detail(_request())


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

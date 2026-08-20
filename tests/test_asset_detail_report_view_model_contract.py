"""Contract regression tests for the AssetDetailReportViewModel candidate contract.

Context: docs/mvp/pdm-evidence-report-ui-integration-plan.md §3.1/§3.2 and
docs/mvp/schema-definition.md §5.3 define AssetDetailReportViewModel as a V2
change proposal for `GET /objects/{asset_id}/report-detail`. It does not
replace the current Event Report API. Per §3.2 step 1, the documented
contract and test fixtures are added before any implementation. These tests
only fix the candidate shape and its scenario fixtures; they do not assert
that a Product API endpoint exists yet.

See docs/mvp/asset-detail-report-viewmodel-frontend-field-audit.md for the
field audit this fixture set is derived from.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "schemas" / "asset-detail-report-view-model.schema.json"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "asset_detail_report_view_model"

SCENARIO_FILES = {
    "current_evidence_only": "current-evidence-only.json",
    "observation_series_present": "observation-series-present.json",
    "risk_timeline_present": "risk-timeline-present.json",
    "baseline_partially_missing": "baseline-partially-missing.json",
}

# risk.status_grade must only ever carry these 4 grades. data_quality_hold is
# represented separately at data_status.is_data_quality_hold, not as a 5th
# status_grade value (unlike the raw Product Result Artifact's status_grade,
# which still includes data_quality_hold at the producer level).
ALLOWED_STATUS_GRADES = {"normal", "attention", "warning", "critical"}

# runtime_inference/compatibility_fallback is only meaningful as a source
# discriminator for evidence and risk_series entries, never for
# data_status.source (canonical/fallback) or feature series quality_status
# (good/bad/unknown).
SOURCE_KIND_VALUES = {"runtime_inference", "compatibility_fallback"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def schema() -> dict:
    return load_json(SCHEMA_PATH)


def fixture(name: str) -> dict:
    return load_json(FIXTURE_ROOT / SCENARIO_FILES[name])


def schema_errors(payload: dict) -> list:
    return list(Draft202012Validator(schema()).iter_errors(payload))


@pytest.mark.parametrize("scenario", sorted(SCENARIO_FILES))
def test_fixture_matches_asset_detail_report_view_model_schema(scenario: str) -> None:
    assert schema_errors(fixture(scenario)) == []


@pytest.mark.parametrize("scenario", sorted(SCENARIO_FILES))
def test_fixture_status_grade_is_one_of_four_grades(scenario: str) -> None:
    payload = fixture(scenario)

    assert payload["risk"]["status_grade"] in ALLOWED_STATUS_GRADES
    assert "data_quality_hold" not in ALLOWED_STATUS_GRADES


def test_schema_keeps_data_quality_hold_out_of_status_grade_enum() -> None:
    properties = schema()["properties"]

    assert "data_quality_hold" not in properties["risk"]["properties"]["status_grade"]["enum"]
    assert properties["risk"]["properties"]["status_grade"]["enum"] == sorted(ALLOWED_STATUS_GRADES, key=["normal", "attention", "warning", "critical"].index)


def test_schema_separates_data_quality_hold_into_data_status() -> None:
    properties = schema()["properties"]

    assert "is_data_quality_hold" in properties["data_status"]["required"]
    assert properties["data_status"]["properties"]["is_data_quality_hold"]["type"] == "boolean"


def test_schema_restricts_source_kind_enum_to_evidence_and_risk_series_only() -> None:
    """runtime_inference/compatibility_fallback must not leak into data_status.source
    or feature series quality_status."""
    properties = schema()["properties"]

    assert set(properties["evidence"]["properties"]["source_kind"]["enum"]) == SOURCE_KIND_VALUES
    assert set(properties["risk_series"]["items"]["properties"]["source_kind"]["enum"]) == SOURCE_KIND_VALUES
    assert set(properties["data_status"]["properties"]["source"]["enum"]) == {"canonical", "fallback"}
    quality_status_enum = properties["features"]["items"]["properties"]["series"]["items"]["properties"]["quality_status"]["enum"]
    assert set(quality_status_enum) == {"good", "bad", "unknown"}
    assert SOURCE_KIND_VALUES.isdisjoint(quality_status_enum)


def test_schema_rejects_mvp_prefixed_additional_property() -> None:
    payload = fixture("current_evidence_only")
    payload["mvpLegacyField"] = True

    errors = schema_errors(payload)

    assert any("Additional properties are not allowed" in error.message for error in errors)


def test_current_evidence_only_records_gaps_for_series_timeline_and_history() -> None:
    payload = fixture("current_evidence_only")
    gap_fields = {gap["field"] for gap in payload["evidence"]["gaps"]}

    assert payload["risk_series"] == []
    assert payload["equipment_history"] == []
    assert all(feature["series"] == [] for feature in payload["features"])
    assert {"features[].series", "risk_series", "equipment_history"} <= gap_fields


def test_observation_series_present_fills_feature_series_but_not_risk_series() -> None:
    payload = fixture("observation_series_present")
    gap_fields = {gap["field"] for gap in payload["evidence"]["gaps"]}

    assert any(feature["series"] for feature in payload["features"])
    assert payload["risk_series"] == []
    assert "risk_series" in gap_fields
    assert "features[].series" not in gap_fields


def test_risk_timeline_present_fills_risk_series_and_feature_series() -> None:
    payload = fixture("risk_timeline_present")
    gap_fields = {gap["field"] for gap in payload["evidence"]["gaps"]}

    assert payload["risk_series"]
    assert all(point["source_kind"] in SOURCE_KIND_VALUES for point in payload["risk_series"])
    assert any(feature["series"] for feature in payload["features"])
    assert "risk_series" not in gap_fields
    assert "features[].series" not in gap_fields
    # equipment_history still requires a dedicated Activity/Maintenance source.
    assert "equipment_history" in gap_fields


def test_risk_series_source_ref_does_not_point_at_legacy_precomputed_timeline() -> None:
    for scenario in SCENARIO_FILES:
        payload = fixture(scenario)
        for point in payload["risk_series"]:
            source_ref = point.get("source_ref", "")
            assert "precomputed_prediction_timeline" not in source_ref
            assert "/timeline" not in source_ref


def test_baseline_partially_missing_keeps_current_value_and_series_but_gaps_baseline() -> None:
    payload = fixture("baseline_partially_missing")
    missing_baseline_features = [feature for feature in payload["features"] if feature["baseline"] is None]

    assert missing_baseline_features
    for feature in missing_baseline_features:
        assert feature["current"] is not None
        assert feature["series"], "current value/series must not be withheld just because baseline is missing"

    gap_fields = {gap["field"] for gap in payload["evidence"]["gaps"]}
    assert any(field.startswith("features[") and field.endswith("].baseline") for field in gap_fields)


@pytest.mark.parametrize("scenario", sorted(SCENARIO_FILES))
def test_fixture_never_synthesizes_values_for_gapped_fields(scenario: str) -> None:
    """Fields listed in evidence.gaps must stay null/empty, never a synthesized
    fallback value (0, an averaged number, a hardcoded 'normal')."""
    payload = fixture(scenario)
    gap_fields = {gap["field"] for gap in payload["evidence"]["gaps"]}

    if "risk_series" in gap_fields:
        assert payload["risk_series"] == []
    if "equipment_history" in gap_fields:
        assert payload["equipment_history"] == []
    if "features[].series" in gap_fields:
        assert all(feature["series"] == [] for feature in payload["features"])

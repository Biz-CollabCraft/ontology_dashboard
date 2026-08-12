from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.preventive_intervention.contracts import PredictionTimelinePoint
from experiments.preventive_intervention.risk_rise import (
    detect_risk_rise_events,
    load_risk_rise_policy,
    rank_events_by_risk_factor,
)
from experiments.preventive_intervention.sensor_analysis import analyze_cnc_sensor_windows


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = (
    ROOT
    / "experiments"
    / "preventive_intervention"
    / "policies"
    / "risk-rise-detection-v1.json"
)


def point(hour: int, probability: float, *, asset_id: str = "CNC-01") -> PredictionTimelinePoint:
    return PredictionTimelinePoint(
        prediction_id=f"{asset_id}#2026-08-01T{hour:02d}:00:00+09:00",
        asset_id=asset_id,
        asset_type="cnc",
        observed_at=f"2026-08-01T{hour:02d}:00:00+09:00",
        failure_probability=probability,
        model_version="independent-logreg-v3.1",
        top_factors=[],
    )


def test_policy_records_the_distribution_basis() -> None:
    policy = load_risk_rise_policy(POLICY_PATH)
    assert policy.minimum_step_probability_increase == pytest.approx(0.191046)
    assert policy.distribution_basis["statistic"] == "positive_adjacent_probability_delta_p90"


def test_detects_maximal_risk_rise_and_records_end_timestamp() -> None:
    policy = load_risk_rise_policy(POLICY_PATH)
    events = detect_risk_rise_events(
        [point(0, 0.1), point(1, 0.35), point(2, 0.6), point(3, 0.55)],
        policy,
    )
    assert len(events) == 1
    event = events[0]
    assert event.baseline_probability == pytest.approx(0.1)
    assert event.peak_probability == pytest.approx(0.6)
    assert event.probability_delta == pytest.approx(0.5)
    assert event.time_to_peak_hours == pytest.approx(2)
    assert event.duration_hours == pytest.approx(3)
    assert len(event.source_prediction_ids) == 4


def test_ignores_subthreshold_and_non_cnc_changes() -> None:
    policy = load_risk_rise_policy(POLICY_PATH)
    small_change = [point(0, 0.1), point(1, 0.2)]
    compressor = [
        PredictionTimelinePoint.model_validate(
            {
                **json.loads(item.model_dump_json()),
                "asset_id": "CMP-01",
                "asset_type": "compressor",
                "prediction_id": item.prediction_id.replace("CNC-01", "CMP-01"),
            }
        )
        for item in (point(0, 0.1), point(1, 0.8))
    ]
    assert detect_risk_rise_events([*small_change, *compressor], policy) == []


def test_rejects_duplicate_timestamps_for_an_asset() -> None:
    policy = load_risk_rise_policy(POLICY_PATH)
    with pytest.raises(ValueError, match="duplicate observed_at"):
        detect_risk_rise_events([point(0, 0.1), point(0, 0.5)], policy)


def test_ranks_only_events_with_matching_peak_risk_factor() -> None:
    policy = load_risk_rise_policy(POLICY_PATH)
    points = [point(0, 0.1), point(1, 0.5), point(2, 0.4)]
    peak_payload = points[1].model_dump(mode="json")
    peak_payload["top_factors"] = [
        {
            "feature": "tool_wear_min_6h_change",
            "signed_contribution": 2.0,
            "direction": "risk_up",
        }
    ]
    points[1] = PredictionTimelinePoint.model_validate(peak_payload)
    events = detect_risk_rise_events(points, policy)
    assert rank_events_by_risk_factor(events, points, feature_prefix="tool_wear_min") == events


def test_ranking_does_not_depend_on_prediction_id_timestamp_format() -> None:
    policy = load_risk_rise_policy(POLICY_PATH)
    points = [point(0, 0.1), point(1, 0.5), point(2, 0.4)]
    peak_payload = points[1].model_dump(mode="json")
    peak_payload["prediction_id"] = "source-defined-id-without-iso-timestamp"
    peak_payload["top_factors"] = [
        {
            "feature": "tool_wear_min_6h_change",
            "signed_contribution": 2.0,
            "direction": "risk_up",
        }
    ]
    points[1] = PredictionTimelinePoint.model_validate(peak_payload)

    events = detect_risk_rise_events(points, policy)

    assert rank_events_by_risk_factor(events, points, feature_prefix="tool_wear_min") == events


def test_ranking_rejects_duplicate_asset_timestamp_keys() -> None:
    policy = load_risk_rise_policy(POLICY_PATH)
    points = [point(0, 0.1), point(1, 0.5), point(2, 0.4)]
    events = detect_risk_rise_events(points, policy)

    with pytest.raises(ValueError, match="duplicate asset_id and observed_at"):
        rank_events_by_risk_factor(
            events,
            [*points, points[1].model_copy(update={"prediction_id": "duplicate-id"})],
            feature_prefix="tool_wear_min",
        )


def test_calculates_baseline_and_risk_sensor_statistics(tmp_path: Path) -> None:
    csv_path = tmp_path / "cnc.csv"
    csv_path.write_text(
        "observed_at,asset_id,air_temperature_k,process_temperature_k,rotational_speed_rpm,torque_nm,tool_wear_min\n"
        "2026-07-31T18:00:00+09:00,CNC-01,299,309,1500,40,10\n"
        "2026-07-31T19:00:00+09:00,CNC-01,301,311,1520,42,20\n"
        "2026-08-01T00:00:00+09:00,CNC-01,302,312,1540,44,30\n"
        "2026-08-01T01:00:00+09:00,CNC-01,304,314,1560,46,50\n",
        encoding="utf-8",
    )
    policy = load_risk_rise_policy(POLICY_PATH)
    event = detect_risk_rise_events(
        [point(0, 0.1), point(1, 0.5), point(2, 0.4)], policy
    )[0]
    result = analyze_cnc_sensor_windows(
        csv_path,
        event,
        baseline_window_hours=policy.baseline_window_hours,
    )
    wear = next(item for item in result if item.feature == "tool_wear_min")
    assert wear.baseline_mean == pytest.approx(15)
    assert wear.risk_mean == pytest.approx(40)
    assert wear.change_percent == pytest.approx(166.6666667)

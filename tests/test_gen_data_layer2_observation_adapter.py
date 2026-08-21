from __future__ import annotations

import json
from pathlib import Path

import pytest

from systems.backend.app.dataset.ingestion.gen_data_layer2 import (
    normalize_gen_data_layer2_rows,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "gen_data_layer2_observation"


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_layer2_rows_are_pivoted_to_observation_shape() -> None:
    rows = _read_jsonl(FIXTURE_ROOT / "sample_log.jsonl")
    expected = json.loads((FIXTURE_ROOT / "expected_observations.json").read_text())

    observations = normalize_gen_data_layer2_rows(
        rows,
        feature_mapping={"rpm": "rotational_speed_rpm"},
    )

    assert observations == expected


def test_bad_null_sensor_value_is_preserved_as_unavailable_measurement() -> None:
    rows = _read_jsonl(FIXTURE_ROOT / "sample_log.jsonl")

    observation = normalize_gen_data_layer2_rows(
        rows,
        feature_mapping={"rpm": "rotational_speed_rpm"},
    )[0]

    assert observation["measurements"]["rotational_speed_rpm"] is None
    assert observation["quality"]["rotational_speed_rpm"] == {
        "quality_status": "bad",
        "source_status_code": "Bad",
        "reason": "sensor_timeout",
    }


def test_source_timestamp_not_server_timestamp_defines_observed_at() -> None:
    rows = [
        {
            "node_id": "CNC-S01-L01-01.torque_nm",
            "source_timestamp": "2026-08-20T01:00:00Z",
            "server_timestamp": "2026-08-20T01:30:00Z",
            "value": 42.5,
            "status_code": "Good",
        }
    ]

    observation = normalize_gen_data_layer2_rows(rows)[0]

    assert observation["observed_at"] == "2026-08-20T01:00:00Z"
    assert observation["source"]["server_timestamps"] == ["2026-08-20T01:30:00Z"]


def test_node_id_must_include_asset_and_sensor_key() -> None:
    with pytest.raises(ValueError, match="node_id"):
        normalize_gen_data_layer2_rows(
            [
                {
                    "node_id": "torque_nm",
                    "source_timestamp": "2026-08-20T01:00:00Z",
                    "value": 42.5,
                    "status_code": "Good",
                }
            ]
        )


def test_unknown_status_code_stays_unknown_quality() -> None:
    observation = normalize_gen_data_layer2_rows(
        [
            {
                "node_id": "CNC-S01-L01-01.torque_nm",
                "source_timestamp": "2026-08-20T01:00:00Z",
                "value": 42.5,
                "status_code": "Stale",
            }
        ]
    )[0]

    assert observation["quality"]["torque_nm"]["quality_status"] == "unknown"

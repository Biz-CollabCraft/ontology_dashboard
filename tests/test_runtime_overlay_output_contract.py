from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.infra.live_predictive_maintenance_runtime import _read_overlay_event_rows
from app.infra.runtime_overlay_contract import (
    semantic_observation_sha256,
    validate_overlay_available_event,
    validate_overlay_observation,
)


ROOT = Path(__file__).resolve().parents[1]


def observation() -> dict[str, object]:
    measurements = {
        "air_temperature_k": 301.8953,
        "process_temperature_k": 310.7953,
        "rotational_speed_rpm": 1406.628,
        "torque_nm": 51.3807,
        "tool_wear_min": 0.0,
        "is_operating": 1,
        "operating_state": "running",
        "product_type": "L",
    }
    payload: dict[str, object] = {
        "contract_version": "runtime-overlay-observation-v1",
        "schema_version": "2",
        "run_id": "DEMO-001:overlay:MAINT-001",
        "sequence": 1,
        "asset_id": "CNC-S01-L01-01",
        "equipment_id": "CNC-S01-L01-01",
        "observed_at": "2026-08-18T01:40:00+00:00",
        "generated_at": "2026-08-18T02:00:00+00:00",
        "measurements": measurements,
        "generator_version": "canonical-ai4i-physics-v3.1",
        "asset_type": "cnc",
        "site_id": "S01",
        "cell_id": "S01-L01",
        "source_kind": "maintenance_replay_overlay",
        "observation_id": "obs-e3614a66b6ebdd68b42e67c2272266c0",
        "observed_at_source": "source",
        "branch_kind": "overlay",
        "overlay": {
            "overlay_id": "MAINT-001:post",
            "parent_branch": "canonical",
            "maintenance_event_id": "MAINT-001",
            "state_patch_reference": "ACTION-001",
            "simulation_session_id": "DEMO-001",
            "history_segment_id": "MAINT-001:post",
            "state_version": 3,
        },
        "record_kind": "full_observation",
        "quality": "good",
        "base_dataset_version": "predictive-maintenance-canonical-v3.1",
        "base_source_sha256": "2" * 64,
        "simulation_session_id": "DEMO-001",
        "overlay_branch_id": "MAINT-001:post",
        "maintenance_event_id": "MAINT-001",
        "maintenance_action_id": "ACTION-001",
        "state_version": 3,
        "history_segment_id": "MAINT-001:post",
        **measurements,
    }
    payload["observation_sha256"] = semantic_observation_sha256(payload)
    return payload


def available_event(*, batch_rows: int = 1, generated_rows: int = 1) -> dict[str, object]:
    return {
        "contract_version": "runtime-overlay-observations-available-v1",
        "event_type": "runtime_overlay.observations.available",
        "event_id": f"OVERLAY-AVAILABLE:MAINT-001:post:{generated_rows}",
        "simulation_session_id": "DEMO-001",
        "equipment_id": "CNC-S01-L01-01",
        "maintenance_action_id": "ACTION-001",
        "maintenance_event_id": "MAINT-001",
        "overlay_branch_id": "MAINT-001:post",
        "history_segment_id": "MAINT-001:post",
        "source_kind": "maintenance_replay_overlay",
        "state_version": 3,
        "batch_rows": batch_rows,
        "generated_rows": generated_rows,
        "observed_from": "2026-08-18T01:40:00+00:00",
        "observed_to": "2026-08-18T01:40:00+00:00",
        "storage_reference": "runtime_overlay/DEMO-001/MAINT-001_post.jsonl",
    }


def test_runtime_overlay_schemas_are_valid_draft_2020_12() -> None:
    for name in (
        "runtime-overlay-observation.schema.json",
        "runtime-overlay-observations-available.schema.json",
    ):
        schema = json.loads((ROOT / "contracts" / "schemas" / name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)


def test_official_runtime_overlay_payloads_pass_shape_and_semantic_validation() -> None:
    validate_overlay_observation(observation())
    validate_overlay_available_event(available_event())


def test_observation_rejects_flat_projection_or_checksum_drift() -> None:
    payload = observation()
    payload["tool_wear_min"] = 1.0
    with pytest.raises(ValueError, match="flat projection"):
        validate_overlay_observation(payload)

    payload = observation()
    payload["observation_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum mismatch"):
        validate_overlay_observation(payload)


def test_available_event_rejects_absolute_or_mismatched_storage_reference() -> None:
    payload = available_event()
    payload["storage_reference"] = "C:/producer/runtime_overlay/DEMO-001/MAINT-001_post.jsonl"
    with pytest.raises(ValueError, match="schema validation failed"):
        validate_overlay_available_event(payload)

    payload = available_event()
    payload["storage_reference"] = "runtime_overlay/OTHER/MAINT-001_post.jsonl"
    with pytest.raises(ValueError, match="does not match"):
        validate_overlay_available_event(payload)


def test_available_event_batch_is_delta_and_generated_rows_is_cumulative() -> None:
    validate_overlay_available_event(available_event(batch_rows=2, generated_rows=5))
    with pytest.raises(ValueError, match="generated_rows"):
        validate_overlay_available_event(available_event(batch_rows=5, generated_rows=2))


def test_backend_reads_only_rows_matching_the_official_available_event(tmp_path: Path) -> None:
    payload = observation()
    event = available_event()
    storage = tmp_path / "runtime_overlay" / "DEMO-001" / "MAINT-001_post.jsonl"
    storage.parent.mkdir(parents=True)
    storage.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    assert _read_overlay_event_rows(tmp_path, event) == [payload]

    mismatched = copy.deepcopy(payload)
    mismatched["history_segment_id"] = "OTHER"
    mismatched["observation_sha256"] = semantic_observation_sha256(mismatched)
    storage.write_text(json.dumps(mismatched) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="history_segment_id differs"):
        _read_overlay_event_rows(tmp_path, event)

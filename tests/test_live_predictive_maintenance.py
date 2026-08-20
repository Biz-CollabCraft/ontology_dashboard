from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.live_predictive_maintenance import (
    LIVE_SOURCE_VERSION,
    active_overlay_asset_ids,
    read_complete_ticks,
    read_overlay_available_events,
)


def test_macmini_compose_runs_canonical_live_worker() -> None:
    root = Path(__file__).resolve().parents[1]
    compose = (root / "infra" / "macmini" / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'command: ["python", "-m", "app.live_predictive_maintenance"]' in compose
    assert "ontology_dashboard.live_predictive_maintenance" not in compose
    assert not (
        root / "systems" / "backend" / "ontology_dashboard" / "live_predictive_maintenance.py"
    ).exists()


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_read_complete_ticks_ignores_half_written_cross_line_tick(tmp_path):
    first = "2026-08-18T05:30:00+00:00"
    second = "2026-08-18T05:40:00+00:00"
    _write(
        tmp_path / "sensor/facS01/lineL01/sensor_stream.jsonl",
        [
            {"asset_id": "CMP-1", "observed_at": first},
            {"asset_id": "CMP-1", "observed_at": second},
        ],
    )
    _write(
        tmp_path / "sensor/facS01/lineL02/sensor_stream.jsonl",
        [{"asset_id": "CNC-1", "observed_at": first}],
    )

    ticks = read_complete_ticks(tmp_path, expected_asset_count=2)

    assert [tick[0] for tick in ticks] == [datetime(2026, 8, 18, 5, 30, tzinfo=timezone.utc)]
    assert {row["asset_id"] for row in ticks[0][1]} == {"CMP-1", "CNC-1"}


def test_read_complete_ticks_respects_ingestion_checkpoint(tmp_path):
    first = "2026-08-18T05:30:00+00:00"
    second = "2026-08-18T05:40:00+00:00"
    for line, asset in (("lineL01", "CMP-1"), ("lineL02", "CNC-1")):
        _write(
            tmp_path / f"sensor/facS01/{line}/sensor_stream.jsonl",
            [
                {"asset_id": asset, "observed_at": first},
                {"asset_id": asset, "observed_at": second},
            ],
        )

    ticks = read_complete_ticks(
        tmp_path,
        after=datetime(2026, 8, 18, 5, 30, tzinfo=timezone.utc),
        expected_asset_count=2,
    )

    assert len(ticks) == 1
    assert ticks[0][0] == datetime(2026, 8, 18, 5, 40, tzinfo=timezone.utc)


def test_wall_clock_live_version_does_not_admit_future_accelerated_ticks(tmp_path):
    current = "2026-08-18T09:30:00+00:00"
    future = "2026-08-19T09:30:00+00:00"
    for line, asset in (("lineL01", "CMP-1"), ("lineL02", "CNC-1")):
        _write(
            tmp_path / f"sensor/facS01/{line}/sensor_stream.jsonl",
            [
                {"asset_id": asset, "observed_at": current},
                {"asset_id": asset, "observed_at": future},
            ],
        )

    ticks = read_complete_ticks(
        tmp_path,
        not_after=datetime(2026, 8, 18, 9, 32, tzinfo=timezone.utc),
        expected_asset_count=2,
    )

    assert LIVE_SOURCE_VERSION == "gen-data-wall-clock-live-v2"
    assert [tick[0] for tick in ticks] == [
        datetime(2026, 8, 18, 9, 30, tzinfo=timezone.utc)
    ]


def test_active_overlay_asset_ids_reads_checkpoint_without_model_semantics(tmp_path):
    state = {
        "checkpoint_version": 1,
        "branches": {
            "session:CNC-1:action": {
                "equipment_id": "CNC-1",
                "phase": "running",
            },
            "session:CNC-2:action": {
                "equipment_id": "CNC-2",
                "phase": "maintenance",
            },
        },
    }
    path = tmp_path / "runtime_overlay/runtime_overlay_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")

    assert active_overlay_asset_ids(tmp_path) == {"CNC-1", "CNC-2"}


def test_overlay_available_outbox_is_deduplicated_by_event_id(tmp_path):
    event = {
        "event_type": "runtime_overlay.observations.available",
        "event_id": "OVERLAY-AVAILABLE:MAINT-1:post:36",
        "simulation_session_id": "SESSION-1",
        "equipment_id": "CNC-1",
        "maintenance_action_id": "ACTION-1",
        "maintenance_event_id": "MAINT-1",
        "overlay_branch_id": "MAINT-1:post",
        "history_segment_id": "MAINT-1:post",
        "state_version": 3,
        "batch_rows": 36,
        "generated_rows": 36,
        "observed_from": "2026-08-18T05:30:00+00:00",
        "observed_to": "2026-08-18T11:20:00+00:00",
    }
    _write(
        tmp_path / "runtime_overlay/observations_available.jsonl",
        [event, event],
    )

    assert read_overlay_available_events(tmp_path) == [event]

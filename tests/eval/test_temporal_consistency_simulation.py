from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_temporal_consistency.py"


def _load():
    spec = importlib.util.spec_from_file_location("temporal_consistency", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_temporal_fault_suite_builds_96_rows_and_exposes_pipeline_delta() -> None:
    module = _load()
    result = module.run_fault_suite()

    assert result["case_count"] == 8
    assert result["scenario_count"] == 4
    assert result["sample_size"] == 96
    assert {row["arm"] for row in result["rows"]} == {"B1", "B2", "B3"}
    assert {row["scenario"] for row in result["rows"]} == set(module.SCENARIOS)

    by_arm = result["aggregate"]["by_arm"]
    assert by_arm["B1"]["stale_candidate_accepted_rate"] == 1.0
    assert by_arm["B2"]["stale_candidate_accepted_rate"] == 1.0
    assert by_arm["B3"]["stale_candidate_accepted_rate"] == 0.0
    assert by_arm["B3"]["snapshot_mismatch_detection_rate"] == 1.0
    assert by_arm["B3"]["stale_output_block_rate"] == 1.0
    assert by_arm["B3"]["production_snapshot_guard_applied_rate"] == 1.0
    assert result["aggregate"]["comparison_order"] == ["B3-B1", "B2-B1", "B3-B2"]


def test_temporal_rows_record_decision_relevant_transition_and_mismatch_fields() -> None:
    module = _load()
    result = module.run_fault_suite()
    b3_rows = [row for row in result["rows"] if row["arm"] == "B3"]

    assert all(row["decision_relevance_changed"] is True for row in b3_rows)
    assert all(row["production_mismatch_fields"] for row in b3_rows)
    assert all(row["snapshot_mismatch_detected"] is True for row in b3_rows)
    assert all(row["projection_read_count"] == 2 for row in b3_rows)
    assert all(row["temporal_gold_at_accept"]["state"] == "not_measured" for row in b3_rows)


def test_b3_transient_stale_projection_recovers_after_one_requery() -> None:
    module = _load()
    result = module.run_recovery_suite()

    assert result["sample_size"] == 8
    assert result["fresh_state_recovery_rate"] == 1.0
    assert all(row["accepted_after_requery"] is True for row in result["rows"])
    assert all(row["projection_read_count"] == 2 for row in result["rows"])
    assert all(row["terminal_mismatch_fields"] == [] for row in result["rows"])

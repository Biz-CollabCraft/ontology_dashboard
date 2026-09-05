from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evaluate_agent_workflow_reliability.py"


def _load():
    spec = importlib.util.spec_from_file_location("workflow_reliability", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def evaluation(tmp_path_factory):
    module = _load()
    runtime_dir = tmp_path_factory.mktemp("workflow-reliability") / "run"
    return module.run_evaluation(
        candidate_sha="candidate-test-sha",
        run_id="reliability-test-run",
        runtime_dir=runtime_dir,
    )


def test_reliability_runner_measures_every_required_scenario(evaluation) -> None:
    assert evaluation["passed"] is True
    assert evaluation["scenario_count"] == 11
    assert {row["scenario"] for row in evaluation["rows"]} == {
        "normal_creation",
        "stored_reuse",
        "active_conflict",
        "provider_timeout",
        "external_context_timeout",
        "external_context_malformed",
        "external_context_not_connected",
        "invalid_output",
        "stale_recovery",
        "retry_exhausted",
        "snapshot_mismatch",
    }
    assert all(evaluation["acceptance"].values())


def test_reliability_rows_link_service_results_to_sqlite(evaluation) -> None:
    rows = {row["case_id"]: row for row in evaluation["rows"]}
    normal = rows["normal_creation"]
    reuse = rows["stored_reuse"]
    assert normal["summary_count_before"] == 0
    assert normal["summary_count_after"] == 1
    assert normal["workflow_run_id"]
    assert normal["db_trace_ref"]["summary_ids"]
    assert normal["db_trace_ref"]["workflow_run_ids"]
    assert reuse["summary_key"] == normal["summary_key"]
    assert reuse["provider_call_count"] == normal["provider_call_count"] == 1
    assert reuse["summary_count_before"] == reuse["summary_count_after"] == 1
    assert reuse["run_status"] == "reused"


def test_reliability_runner_separates_conflict_recovery_and_fallback(evaluation) -> None:
    rows = {row["case_id"]: row for row in evaluation["rows"]}
    aggregate = evaluation["aggregate"]
    assert rows["active_conflict"]["running_conflict"] is True
    assert rows["active_conflict"]["run_status"] == "running_conflict"
    assert rows["stale_recovery"]["stale_recovered"] is True
    assert rows["stale_recovery"]["run_status"] == "created"
    assert rows["provider_timeout"]["fallback_reason"] == "TimeoutError"
    assert rows["invalid_output"]["fallback_reason"] == "summary_validation_failed"
    assert rows["retry_exhausted"]["run_status"] == "failed"
    assert rows["retry_exhausted"]["attempt_count"] == 2
    assert aggregate["counts"]["fallback"] == 5
    assert aggregate["counts"]["failed_terminal"] == 1


def test_external_failures_and_snapshot_mismatch_preserve_side_effect_boundary(
    evaluation,
) -> None:
    rows = {row["case_id"]: row for row in evaluation["rows"]}
    assert {
        rows["external_context_timeout"]["external_api_fallback_reason"],
        rows["external_context_malformed"]["external_api_fallback_reason"],
        rows["external_context_not_connected"]["external_api_fallback_reason"],
    } == {
        "external_api_timeout",
        "external_api_malformed_response",
        "external_api_not_connected",
    }
    mismatch = rows["snapshot_mismatch"]
    assert mismatch["run_status"] == "blocked"
    assert mismatch["blocked_side_effect"] is True
    for row in evaluation["rows"]:
        assert row["work_order_count_before"] == row["work_order_count_after"]
        assert row["command_count_before"] == row["command_count_after"]
        assert row["measurements"]["input_tokens"]["status"] == "not_measured"
        assert row["measurements"]["cost_usd"]["status"] == "not_measured"

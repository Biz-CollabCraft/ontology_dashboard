from __future__ import annotations

import pytest

from scripts.eval_support.agent_workflow_stability import (
    aggregate_stability_evaluation,
    measurement,
    stability_evaluation_row,
)


def row(**overrides):
    values = {
        "case_id": "reuse",
        "iteration": 1,
        "provider_mode": "disabled",
        "summary_key": "agent-review-summary:key",
        "run_status": "created",
    }
    values.update(overrides)
    return stability_evaluation_row(**values)


def test_missing_measurements_are_explicit_and_null_safe() -> None:
    result = row()

    assert result["measurements"] == {
        "latency_ms": {"status": "not_measured", "value": None},
        "input_tokens": {"status": "not_measured", "value": None},
        "output_tokens": {"status": "not_measured", "value": None},
        "cost_usd": {"status": "not_measured", "value": None},
    }
    assert measurement(0) == {"status": "measured", "value": 0}


def test_outcome_flags_cannot_be_reported_under_ambiguous_status() -> None:
    with pytest.raises(ValueError, match="reused rows"):
        row(reused=True)
    with pytest.raises(ValueError, match="fallback and fallback_reason"):
        row(run_status="fallback", fallback=True)
    with pytest.raises(ValueError, match="blocked side effects"):
        row(blocked_side_effect=True)


def test_aggregate_keeps_reuse_fallback_failure_recovery_and_blocking_separate() -> None:
    rows = [
        row(run_status="reused", reused=True, latency_ms=4),
        row(
            case_id="provider-disabled",
            run_status="fallback",
            fallback=True,
            fallback_reason="agent_review_summary_provider_disabled",
        ),
        row(
            case_id="invalid-output",
            run_status="fallback",
            fallback=True,
            fallback_reason="summary_validation_failed",
            validation_errors=["summary:unsupported_claim"],
        ),
        row(
            case_id="retry-exhausted",
            run_status="failed",
            retry_count=2,
            retry_exhausted=True,
        ),
        row(
            case_id="stale-running",
            run_status="created",
            stale_recovered=True,
            workflow_run_id="run-after-stale",
        ),
        row(
            case_id="active-running",
            run_status="running_conflict",
            running_conflict=True,
        ),
        row(
            case_id="snapshot-mismatch",
            run_status="blocked",
            blocked_side_effect=True,
        ),
    ]

    report = aggregate_stability_evaluation(rows)

    assert report["total_attempts"] == 7
    assert report["counts"] == {
        "new_workflow_runs": 1,
        "reused": 1,
        "fallback": 2,
        "failed_terminal": 1,
        "active_running_conflict": 1,
        "stale_recovered": 1,
        "bounded_retry_exhausted": 1,
        "blocked_side_effect": 1,
    }
    assert report["fallback_reason_counts"] == {
        "agent_review_summary_provider_disabled": 1,
        "summary_validation_failed": 1,
    }
    assert report["latency_ms"] == {
        "status": "measured",
        "measured_count": 1,
        "not_measured_count": 6,
        "p50": 4.0,
        "p95": 4.0,
    }
    assert report["measurement_not_measured_rows"]["cost_usd"] == 7


def test_empty_aggregate_does_not_synthesize_rates_or_latency() -> None:
    report = aggregate_stability_evaluation([])

    assert report["rates"] == {
        "reuse": None,
        "fallback": None,
        "side_effect_unchanged": None,
    }
    assert report["latency_ms"]["status"] == "not_measured"
    assert report["latency_ms"]["p50"] is None
    assert report["latency_ms"]["p95"] is None

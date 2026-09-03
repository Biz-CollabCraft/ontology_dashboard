"""Evaluation-only row and aggregate contracts for Agent Workflow reliability."""

from __future__ import annotations

from collections import Counter
from math import ceil
from typing import Any, Iterable, Literal

MeasurementStatus = Literal["measured", "not_measured"]
RUN_STATUSES = {
    "created",
    "reused",
    "running_conflict",
    "fallback",
    "failed",
    "blocked",
}


def measurement(value: int | float | None) -> dict[str, Any]:
    if value is None:
        return {"status": "not_measured", "value": None}
    return {"status": "measured", "value": value}


def stability_evaluation_row(
    *,
    case_id: str,
    iteration: int,
    provider_mode: str,
    summary_key: str | None,
    run_status: str,
    scenario: str | None = None,
    reused: bool = False,
    fallback: bool = False,
    fallback_reason: str | None = None,
    retry_count: int = 0,
    retry_exhausted: bool = False,
    stale_recovered: bool = False,
    running_conflict: bool = False,
    blocked_side_effect: bool = False,
    validation_errors: Iterable[str] = (),
    latency_ms: int | float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: int | float | None = None,
    workflow_run_id: str | None = None,
    attempt_count: int = 1,
    external_api_status: str | None = None,
    external_api_fallback_reason: str | None = None,
    summary_count_before: int | None = None,
    summary_count_after: int | None = None,
    work_order_count_before: int | None = None,
    work_order_count_after: int | None = None,
    command_count_before: int | None = None,
    command_count_after: int | None = None,
    db_trace_ref: dict[str, Any] | None = None,
    evidence_identity_consistent: bool | None = None,
    context_versions_consistent: bool | None = None,
    provider_call_count: int | None = None,
) -> dict[str, Any]:
    if run_status not in RUN_STATUSES:
        raise ValueError(f"unsupported run_status: {run_status}")
    if iteration < 1:
        raise ValueError("iteration must be >= 1")
    if retry_count < 0:
        raise ValueError("retry_count must be >= 0")
    if attempt_count < 0:
        raise ValueError("attempt_count must be >= 0")
    if reused and run_status != "reused":
        raise ValueError("reused rows must use run_status='reused'")
    if fallback and run_status != "fallback":
        raise ValueError("fallback rows must use run_status='fallback'")
    if fallback != bool(fallback_reason):
        raise ValueError("fallback and fallback_reason must be reported together")
    if running_conflict and run_status != "running_conflict":
        raise ValueError("running_conflict rows must use matching run_status")
    if blocked_side_effect and run_status != "blocked":
        raise ValueError("blocked side effects must use run_status='blocked'")

    return {
        "schema_version": "agent-workflow-reliability-row-v1.0",
        "case_id": case_id,
        "iteration": iteration,
        "scenario": scenario or case_id,
        "provider_mode": provider_mode,
        "summary_key": summary_key,
        "workflow_run_id": workflow_run_id,
        "run_status": run_status,
        "reused": reused,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "validation_errors": list(validation_errors),
        "attempt_count": attempt_count,
        "retry_count": retry_count,
        "retry_exhausted": retry_exhausted,
        "external_api_status": external_api_status,
        "external_api_fallback_reason": external_api_fallback_reason,
        "running_conflict": running_conflict,
        "stale_recovered": stale_recovered,
        "summary_count_before": summary_count_before,
        "summary_count_after": summary_count_after,
        "work_order_count_before": work_order_count_before,
        "work_order_count_after": work_order_count_after,
        "command_count_before": command_count_before,
        "command_count_after": command_count_after,
        "blocked_side_effect": blocked_side_effect,
        "evidence_identity_consistent": evidence_identity_consistent,
        "context_versions_consistent": context_versions_consistent,
        "provider_call_count": provider_call_count,
        "db_trace_ref": db_trace_ref or {},
        "measurements": {
            "latency_ms": measurement(latency_ms),
            "input_tokens": measurement(input_tokens),
            "output_tokens": measurement(output_tokens),
            "cost_usd": measurement(cost_usd),
        },
    }


def aggregate_stability_evaluation(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    total = len(materialized)
    statuses = Counter(str(row["run_status"]) for row in materialized)
    fallback_reasons = Counter(
        str(row["fallback_reason"])
        for row in materialized
        if row.get("fallback") and row.get("fallback_reason")
    )
    external_reasons = Counter(
        str(row["external_api_fallback_reason"])
        for row in materialized
        if row.get("external_api_fallback_reason")
    )
    validation_reasons = Counter(
        str(error)
        for row in materialized
        for error in row.get("validation_errors") or []
    )
    latency_values = [
        float(item["value"])
        for row in materialized
        if (item := row["measurements"]["latency_ms"])["status"] == "measured"
    ]

    side_effect_unchanged = sum(
        row.get("work_order_count_before") == row.get("work_order_count_after")
        and row.get("command_count_before") == row.get("command_count_after")
        for row in materialized
        if row.get("work_order_count_before") is not None
        and row.get("command_count_before") is not None
    )
    side_effect_measured = sum(
        row.get("work_order_count_before") is not None
        and row.get("command_count_before") is not None
        for row in materialized
    )

    return {
        "schema_version": "agent-workflow-reliability-aggregate-v1.0",
        "total_attempts": total,
        "counts": {
            "new_workflow_runs": statuses["created"],
            "reused": sum(bool(row.get("reused")) for row in materialized),
            "fallback": sum(bool(row.get("fallback")) for row in materialized),
            "failed_terminal": statuses["failed"],
            "active_running_conflict": sum(bool(row.get("running_conflict")) for row in materialized),
            "stale_recovered": sum(bool(row.get("stale_recovered")) for row in materialized),
            "bounded_retry_exhausted": sum(bool(row.get("retry_exhausted")) for row in materialized),
            "blocked_side_effect": sum(bool(row.get("blocked_side_effect")) for row in materialized),
        },
        "rates": {
            "reuse": _rate(sum(bool(row.get("reused")) for row in materialized), total),
            "fallback": _rate(sum(bool(row.get("fallback")) for row in materialized), total),
            "side_effect_unchanged": _rate(side_effect_unchanged, side_effect_measured),
        },
        "fallback_reason_counts": dict(sorted(fallback_reasons.items())),
        "external_api_fallback_reason_counts": dict(sorted(external_reasons.items())),
        "validation_error_counts": dict(sorted(validation_reasons.items())),
        "latency_ms": {
            "status": "measured" if latency_values else "not_measured",
            "measured_count": len(latency_values),
            "not_measured_count": total - len(latency_values),
            "p50": _percentile(latency_values, 0.50),
            "p95": _percentile(latency_values, 0.95),
        },
        "measurement_not_measured_rows": {
            name: sum(
                row["measurements"][name]["status"] == "not_measured"
                for row in materialized
            )
            for name in ("latency_ms", "input_tokens", "output_tokens", "cost_usd")
        },
    }


def _rate(count: int, total: int) -> float | None:
    return None if total == 0 else count / total


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, ceil(len(ordered) * quantile) - 1)]

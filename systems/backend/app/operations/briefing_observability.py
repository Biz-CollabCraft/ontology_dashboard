"""Operational tracing helpers for the read-only briefing lifecycle.

This module deliberately records identifiers, counts, versions, timings and bounded
failure metadata only. Raw prompt/evidence payloads are not part of the trace.
"""

from __future__ import annotations

import uuid
from typing import Any


BRIEFING_OPERATIONAL_TRACE_SCHEMA_VERSION = "briefing-operational-trace-v1.0"
BRIEFING_TRACE_STAGES = (
    "event_evidence_load",
    "evidence_selection",
    "snapshot_fingerprint_validation",
    "generation_decision",
    "provider_call",
    "output_validation",
    "persistence",
    "read_reuse_serving",
)


def new_briefing_trace_id() -> str:
    return f"briefing:{uuid.uuid4()}"


def evidence_selection_metrics(packet: dict[str, Any]) -> dict[str, Any]:
    context = packet.get("evidence_context") or {}
    selected = [
        item for item in context.get("selected_basis") or [] if isinstance(item, dict)
    ]
    rejected = [
        item for item in context.get("rejected_basis") or [] if isinstance(item, dict)
    ]
    all_candidates = [*selected, *rejected]
    mandatory = [
        item for item in all_candidates if item.get("required_for_boundary") is True
    ]
    preserved = [
        item for item in selected if item.get("required_for_boundary") is True
    ]
    return {
        "evidence_candidate_count": len(all_candidates),
        "selected_evidence_count": len(selected),
        "mandatory_evidence_count": len(mandatory),
        "mandatory_evidence_preserved_count": len(preserved),
        "selection_strategy": (
            "deterministic"
            if context.get("selection_policy_version")
            else None
        ),
        "selection_policy_version": context.get("selection_policy_version"),
    }


def classify_failure(trace: dict[str, Any]) -> str | None:
    if not trace.get("fallback"):
        return None
    reason = str(trace.get("reason") or "")
    if reason == "summary_validation_failed":
        return "validation_failure"
    if reason in {
        "agent_review_summary_provider_disabled",
        "ProviderUnavailable",
        "TimeoutError",
        "RuntimeError",
    }:
        return "provider_failure"
    if "timeout" in reason.lower() or "provider" in reason.lower():
        return "provider_failure"
    return "generation_failure"


def compose_briefing_operational_trace(
    *,
    trace_id: str,
    packet: dict[str, Any],
    key_payload: dict[str, Any],
    generation_policy: dict[str, Any] | None,
    materialization: dict[str, Any] | None,
    generation_trace: dict[str, Any] | None,
    stage_durations_ms: dict[str, float | int | None] | None,
    total_latency_ms: float | int | None,
    serving_kind: str,
) -> dict[str, Any]:
    generation_trace = generation_trace or {}
    materialization = materialization or {}
    stage_durations_ms = stage_durations_ms or {}
    metrics = generation_trace.get("generation_metrics") or {}
    selection = evidence_selection_metrics(packet)
    reused = bool(materialization.get("reused"))
    usage = {} if reused else (metrics.get("usage") or {})
    fallback = bool(generation_trace.get("fallback"))

    stages = {
        stage: _stage_observation(
            stage=stage,
            duration_ms=stage_durations_ms.get(stage),
            reused=reused,
            generation_trace=generation_trace,
        )
        for stage in BRIEFING_TRACE_STAGES
    }

    validation_errors = generation_trace.get("validation_errors") or []
    if generation_trace.get("reason") == "summary_validation_failed":
        validation_result = "candidate_failed_fallback_valid"
    elif metrics.get("provider_invocations"):
        validation_result = "passed" if not validation_errors else "fallback_valid"
    elif fallback:
        validation_result = "fallback_valid"
    else:
        validation_result = "not_run"

    basis = packet.get("snapshot_basis") or {}
    retry_count = metrics.get("repair_count")
    if not isinstance(retry_count, int):
        retry_count = 0

    return {
        "schema_version": BRIEFING_OPERATIONAL_TRACE_SCHEMA_VERSION,
        "trace_id": trace_id,
        "project_id": key_payload.get("project_id") or packet.get("project_id"),
        "workspace_id": key_payload.get("workspace_id"),
        "asset_id": key_payload.get("asset_id") or packet.get("asset_id"),
        "event_id": key_payload.get("event_id") or basis.get("event_id"),
        "evidence_snapshot_id": (
            key_payload.get("artifact_id")
            or basis.get("artifact_id")
            or key_payload.get("event_id")
            or basis.get("event_id")
        ),
        "evidence_fingerprint": key_payload.get("evidence_basis_sha256"),
        **selection,
        "generation_policy": (generation_policy or {}).get("policy"),
        "generation_decision": (generation_policy or {}).get("generation_decision"),
        "cache_reuse_decision": "reuse" if reused else (
            "generate"
            if (generation_policy or {}).get("generation_action") == "GENERATE"
            else "defer"
        ),
        "regeneration_reason": (generation_policy or {}).get("decision_reason"),
        "serving_kind": serving_kind,
        "provider": generation_trace.get("provider"),
        "model": materialization.get("model_version") or key_payload.get("model_version"),
        "prompt_input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "usage_measurement": (
            "provider_reported"
            if isinstance(usage, dict) and usage
            else "not_reported"
        ),
        "provider_latency_ms": None if reused else metrics.get("provider_latency_ms"),
        "total_latency_ms": _rounded(total_latency_ms),
        "validation_result": validation_result,
        "validation_error_count": len(validation_errors),
        "fallback_used": fallback,
        "fallback_reason": generation_trace.get("reason") if fallback else None,
        "failure_category": classify_failure(generation_trace),
        "retry_count": retry_count,
        "final_artifact_id": materialization.get("summary_id"),
        "workflow_run_id": materialization.get("workflow_run_id"),
        "summary_key": materialization.get("summary_key"),
        "stages": stages,
    }


def _stage_observation(
    *,
    stage: str,
    duration_ms: float | int | None,
    reused: bool,
    generation_trace: dict[str, Any],
) -> dict[str, Any]:
    if duration_ms is not None:
        return {"duration_ms": _rounded(duration_ms), "measurement_status": "measured"}

    if stage in {"provider_call", "output_validation", "persistence"}:
        if reused:
            return {"duration_ms": 0.0, "measurement_status": "not_executed_reuse"}
        metrics = generation_trace.get("generation_metrics") or {}
        if not metrics.get("provider_invocations") and stage == "provider_call":
            return {"duration_ms": 0.0, "measurement_status": "not_executed"}
    return {"duration_ms": None, "measurement_status": "not_measured"}


def _rounded(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)

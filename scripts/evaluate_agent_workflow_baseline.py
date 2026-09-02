from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import time
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
GOLD_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets"
LEGACY_HARNESS_PATH = ROOT / "scripts" / "evaluate_agent_review_summary_llm.py"

from app.infra.llm import configured_provider
from app.mvp.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    validate_agent_review_summary_contract,
)
from app.mvp.agent_review_summary_provider import (
    AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
    _merge_llm_editable_fields,
    agent_review_summary_editable_schema,
    build_agent_review_summary_prompt_payload,
)

ARMS = ("B1", "B2", "B3")
FAULTS = ("none", "malformed_output", "provider_timeout", "snapshot_mismatch")
MAX_ATTEMPTS = 2


class JsonProvider(Protocol):
    name: str

    def generate_json(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        *,
        response_schema: dict[str, Any] | None = None,
        response_schema_name: str | None = None,
    ) -> dict[str, Any]: ...


class SimulationState:
    def __init__(self) -> None:
        self.cache: dict[str, dict[str, Any]] = {}
        self.traces: list[dict[str, Any]] = []


class MockJsonProvider:
    name = "mock-baseline-provider"

    def generate_json(self, system_prompt: str, payload: dict[str, Any], **_: Any) -> dict[str, Any]:
        editable = payload.get("baseline_editable_fields") or {}
        return {
            "title": editable.get("title") or "설비 검토 요약",
            "summary": editable.get("summary") or "제공된 입력을 검토해야 합니다.",
            "role_summaries": [
                {"role": item["role"], "quote": item.get("quote") or "검토 필요"}
                for item in editable.get("role_summaries") or []
            ],
        }


class FaultInjectingProvider:
    def __init__(self, provider: JsonProvider, fault: str) -> None:
        self.provider = provider
        self.fault = fault
        self.name = getattr(provider, "name", "unknown")
        self.calls = 0

    def generate_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        if self.fault == "provider_timeout":
            raise TimeoutError("injected_provider_timeout")
        if self.fault == "malformed_output":
            return {"title": 123, "role_summaries": "invalid"}
        return self.provider.generate_json(*args, **kwargs)


def raw_input_payload(packet: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    """Project raw-ish fixture fields without the Evidence Packet envelope or source refs."""
    return {
        "raw_input": {
            "asset_id": packet.get("asset_id"),
            "asset_label": packet.get("asset_label"),
            "observed_at": packet.get("generated_at"),
            "risk": packet.get("risk_summary"),
            "model_factors": (packet.get("model_expression_context") or {}).get("top_factors"),
            "operation_context": packet.get("operation_context_summary"),
            "maintenance_history": packet.get("maintenance_history_summary"),
        },
        "baseline_editable_fields": {
            "title": baseline.get("title"),
            "summary": baseline.get("summary"),
            "role_summaries": [
                {"role": item["role"], "quote": item.get("quote")}
                for item in baseline.get("role_summaries") or []
            ],
        },
        "allowed_output_fields": ["title", "summary", "role_summaries"],
    }


def _summary_key(packet: dict[str, Any]) -> str:
    basis = {
        "snapshot_basis": packet.get("snapshot_basis"),
        "schema_version": packet.get("schema_version"),
        "source_refs": packet.get("source_refs"),
    }
    digest = hashlib.sha256(
        json.dumps(basis, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"baseline:{digest}"


def _estimate_usage(payload: dict[str, Any], candidate: dict[str, Any]) -> dict[str, int]:
    prompt_tokens = max(1, len(json.dumps(payload, ensure_ascii=False)) // 4)
    output_tokens = max(1, len(json.dumps(candidate, ensure_ascii=False)) // 4)
    return {
        "input_tokens": prompt_tokens,
        "output_tokens": output_tokens,
        "total_tokens": prompt_tokens + output_tokens,
    }


def _cost(usage: dict[str, int], *, reused: bool = False) -> dict[str, Any]:
    if reused:
        return {"value": 0.0, "state": "measured", "reason": "no LLM call on cache reuse"}
    input_rate = os.getenv("LLM_INPUT_PRICE_PER_1M_TOKENS")
    output_rate = os.getenv("LLM_OUTPUT_PRICE_PER_1M_TOKENS")
    pricing_version = os.getenv("LLM_PRICING_VERSION")
    if not input_rate or not output_rate or not pricing_version:
        return {
            "value": None,
            "state": "not_measured",
            "reason": "versioned configured price rates are missing",
        }
    value = (
        usage["input_tokens"] * float(input_rate)
        + usage["output_tokens"] * float(output_rate)
    ) / 1_000_000
    return {
        "value": round(value, 8),
        "state": "measured",
        "pricing_version": pricing_version,
    }


def run_arm(
    *,
    arm: str,
    packet: dict[str, Any],
    iteration: int,
    provider: JsonProvider,
    state: SimulationState,
    fault: str = "none",
) -> dict[str, Any]:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    if fault not in FAULTS:
        raise ValueError(f"unknown fault: {fault}")

    baseline = compose_deterministic_agent_review_summary(packet)
    key = _summary_key(packet)
    if arm == "B3" and fault == "snapshot_mismatch":
        return _snapshot_mismatch_row(packet, iteration=iteration, key=key)

    if arm == "B3" and key in state.cache and fault == "none":
        candidate = state.cache[key]
        trace = {
            "summary_key": key,
            "status": "reused",
            "attempt_count": 0,
            "fallback": False,
            "trace_complete": True,
        }
        state.traces.append(trace)
        return _row(
            arm=arm,
            packet=packet,
            iteration=iteration,
            candidate=candidate,
            baseline=baseline,
            payload={},
            provider=provider,
            attempts=0,
            reused=True,
            fallback=False,
            fallback_reason=None,
            trace=trace,
        )

    payload = (
        raw_input_payload(packet, baseline)
        if arm == "B1"
        else build_agent_review_summary_prompt_payload(packet=packet, baseline_summary=baseline)
    )
    injected = FaultInjectingProvider(provider, fault)
    attempts = MAX_ATTEMPTS if arm == "B3" else 1
    candidate: dict[str, Any] | None = None
    errors: list[str] = []
    failure_reason: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            editable = injected.generate_json(
                AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
                payload,
                response_schema=agent_review_summary_editable_schema(),
                response_schema_name="agent_review_summary_editable",
            )
            editable_errors = _validate_editable_candidate(editable)
            if editable_errors:
                errors = editable_errors
                candidate = None
                failure_reason = "validation_failed"
                continue
            candidate = _merge_llm_editable_fields(
                baseline_summary=baseline,
                candidate=editable,
            )
            errors = validate_agent_review_summary_contract(candidate, packet=packet)
            if not errors:
                break
            failure_reason = "validation_failed"
        except Exception as exc:
            failure_reason = type(exc).__name__
            candidate = None

    fallback = False
    if candidate is None or errors:
        if arm == "B3":
            candidate = baseline
            fallback = True
        else:
            candidate = candidate or {}
    accepted = bool(candidate) and not validate_agent_review_summary_contract(
        candidate, packet=packet
    )
    if arm == "B3" and accepted:
        state.cache[key] = candidate

    trace = {
        "summary_key": key if arm == "B3" else None,
        "status": "fallback" if fallback else ("completed" if accepted else "invalid"),
        "attempt_count": injected.calls,
        "fallback": fallback,
        "fallback_reason": failure_reason,
        "trace_complete": arm == "B3",
    }
    if arm == "B3":
        state.traces.append(trace)
    return _row(
        arm=arm,
        packet=packet,
        iteration=iteration,
        candidate=candidate,
        baseline=baseline,
        payload=payload,
        provider=provider,
        attempts=injected.calls,
        reused=False,
        fallback=fallback,
        fallback_reason=failure_reason,
        trace=trace,
    )


def _validate_editable_candidate(candidate: Any) -> list[str]:
    if not isinstance(candidate, dict):
        return ["candidate_not_object"]
    errors = [
        f"{field}_not_string"
        for field in ("title", "summary")
        if not isinstance(candidate.get(field), str) or not candidate[field].strip()
    ]
    roles = candidate.get("role_summaries")
    if not isinstance(roles, list) or len(roles) != 2:
        errors.append("role_summaries_invalid")
    elif any(
        not isinstance(item, dict)
        or item.get("role") not in {"field_operator", "process_manager"}
        or not isinstance(item.get("quote"), str)
        or not item["quote"].strip()
        for item in roles
    ):
        errors.append("role_summary_invalid")
    return errors


def _snapshot_mismatch_row(packet: dict[str, Any], *, iteration: int, key: str) -> dict[str, Any]:
    return {
        "case_id": packet["snapshot_basis"]["event_id"],
        "iteration": iteration,
        "arm": "B3",
        "status": "blocked",
        "accepted": False,
        "schema_valid": None,
        "unsupported_claim_count": None,
        "critical_evidence_omission_count": None,
        "core_judgment": None,
        "attempt_count": 0,
        "reused": False,
        "fallback": False,
        "fallback_reason": None,
        "snapshot_mismatch_blocked": True,
        "blocked_side_effect": True,
        "workflow_trace": {
            "summary_key": key,
            "status": "blocked",
            "attempt_count": 0,
            "fallback": False,
            "trace_complete": True,
        },
        "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "estimated_cost": {"value": 0.0, "state": "measured", "reason": "blocked before LLM call"},
    }


def _row(
    *,
    arm: str,
    packet: dict[str, Any],
    iteration: int,
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    payload: dict[str, Any],
    provider: JsonProvider,
    attempts: int,
    reused: bool,
    fallback: bool,
    fallback_reason: str | None,
    trace: dict[str, Any],
) -> dict[str, Any]:
    errors = validate_agent_review_summary_contract(candidate, packet=packet) if candidate else ["empty"]
    usage = (
        {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        if reused
        else _estimate_usage(payload, candidate)
    )
    legacy = _load_legacy_harness()
    gold = legacy._gold_accuracy(candidate, packet=packet) if candidate else None
    return {
        "case_id": packet["snapshot_basis"]["event_id"],
        "iteration": iteration,
        "arm": arm,
        "provider": getattr(provider, "name", "unknown"),
        "status": trace["status"],
        "accepted": not errors,
        "schema_valid": not errors,
        "unsupported_claim_count": (
            gold.get("unsupported_claim_count") if isinstance(gold, dict) else None
        ),
        "critical_evidence_omission_count": (
            len(gold.get("missing_required_points") or []) if isinstance(gold, dict) else None
        ),
        "core_judgment": {
            "title": candidate.get("title"),
            "mode": candidate.get("mode"),
            "risk_grade": (packet.get("risk_summary") or {}).get("status_grade"),
        },
        "attempt_count": attempts,
        "reused": reused,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "snapshot_mismatch_blocked": False,
        "blocked_side_effect": False,
        "workflow_trace": trace if arm == "B3" else None,
        "usage": usage,
        "estimated_cost": _cost(usage, reused=reused),
    }


def run_suite(
    *, provider: JsonProvider, iterations: int = 3, seed: int = 20260902
) -> dict[str, Any]:
    manifest = json.loads((GOLD_ROOT / "manifest.json").read_text(encoding="utf-8"))
    packets = [
        json.loads((ROOT / case["fixture_path"]).read_text(encoding="utf-8"))
        for case in manifest["cases"]
    ]
    jobs = [
        (arm, packet, iteration)
        for packet in packets
        for arm in ARMS
        for iteration in range(1, iterations + 1)
    ]
    random.Random(seed).shuffle(jobs)
    state = SimulationState()
    rows = [
        run_arm(
            arm=arm,
            packet=packet,
            iteration=iteration,
            provider=provider,
            state=state,
        )
        for arm, packet, iteration in jobs
    ]
    return {
        "status": "measured",
        "case_count": len(packets),
        "iterations_per_case": iterations,
        "arms": list(ARMS),
        "sample_size": len(rows),
        "seed": seed,
        "rows": rows,
        "aggregate": aggregate(rows),
    }


def run_fault_suite(*, provider: JsonProvider) -> dict[str, Any]:
    manifest = json.loads((GOLD_ROOT / "manifest.json").read_text(encoding="utf-8"))
    packets = [
        json.loads((ROOT / case["fixture_path"]).read_text(encoding="utf-8"))
        for case in manifest["cases"]
    ]
    rows = [
        run_arm(
            arm="B3",
            packet=packet,
            iteration=1,
            provider=provider,
            state=SimulationState(),
            fault=fault,
        )
        for packet in packets
        for fault in FAULTS
        if fault != "none"
    ]
    return {
        "sample_size": len(rows),
        "scenarios": [fault for fault in FAULTS if fault != "none"],
        "rows": rows,
        "contained_count": sum(
            row["fallback"] or row["snapshot_mismatch_blocked"] for row in rows
        ),
        "blocked_side_effect_count": sum(bool(row["blocked_side_effect"]) for row in rows),
        "bounded_retry_rows": sum(int(row["attempt_count"]) == MAX_ATTEMPTS for row in rows),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, Any] = {}
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        valid = [row for row in arm_rows if row["schema_valid"] is True]
        costs = [
            row["estimated_cost"]["value"]
            for row in arm_rows
            if row["estimated_cost"]["state"] == "measured"
        ]
        valid_costs = [
            row["estimated_cost"]["value"]
            for row in valid
            if row["estimated_cost"]["state"] == "measured"
        ]
        judgments: dict[str, set[str]] = {}
        for row in arm_rows:
            judgments.setdefault(row["case_id"], set()).add(
                json.dumps(row.get("core_judgment"), ensure_ascii=False, sort_keys=True)
            )
        by_arm[arm] = {
            "runs": len(arm_rows),
            "schema_validation_pass_rate": len(valid) / len(arm_rows) if arm_rows else None,
            "unsupported_claim_count": sum(
                row["unsupported_claim_count"] or 0 for row in arm_rows
            ),
            "critical_evidence_omission_count": sum(
                row["critical_evidence_omission_count"] or 0 for row in arm_rows
            ),
            "core_judgment_agreement_rate": (
                sum(len(values) == 1 for values in judgments.values()) / len(judgments)
                if judgments else None
            ),
            "fallback_count": sum(bool(row["fallback"]) for row in arm_rows),
            "retry_count": sum(max(0, int(row["attempt_count"]) - 1) for row in arm_rows),
            "reuse_count": sum(bool(row["reused"]) for row in arm_rows),
            "workflow_trace_completeness": (
                sum(bool((row.get("workflow_trace") or {}).get("trace_complete")) for row in arm_rows)
                / len(arm_rows)
                if arm == "B3" and arm_rows else None
            ),
            "estimated_total_cost": round(sum(costs), 8) if len(costs) == len(arm_rows) else None,
            "estimated_cost_per_valid_output": (
                round(sum(valid_costs) / len(valid), 8)
                if valid and len(valid_costs) == len(valid) else None
            ),
            "cost_state": "measured" if len(costs) == len(arm_rows) else "not_measured",
        }
    return {"by_arm": by_arm, "primary_comparison": "B3-B1"}


def _load_legacy_harness() -> Any:
    spec = importlib.util.spec_from_file_location("legacy_agent_summary_eval", LEGACY_HARNESS_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser(description="Run minimal B1/B2/B3 baseline simulation.")
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    provider: JsonProvider = MockJsonProvider() if args.mode == "mock" else configured_provider()
    started = time.perf_counter()
    result = run_suite(provider=provider, iterations=args.iterations, seed=args.seed)
    result["mode"] = args.mode
    result["status"] = "fixture_verified" if args.mode == "mock" else "measured"
    result["evidence_level"] = "contract_and_mock_only" if args.mode == "mock" else "live_provider"
    result["fault_injection"] = run_fault_suite(provider=provider)
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    output = args.output or (
        ROOT / "tests" / "eval" / "results" / f"agent_workflow_baseline_{args.mode}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "mode", "sample_size", "aggregate")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

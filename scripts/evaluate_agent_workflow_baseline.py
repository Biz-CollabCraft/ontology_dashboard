from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import random
import statistics
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

DIRECT_LLM_SYSTEM_PROMPT = """
You write a Korean read-only maintenance review summary from minimally normalized raw input.

Hard contract:
- Use only facts present in raw_input.
- Do not assume Evidence Packet fields, source references, inspection targets, SOP guidance,
  evidence gaps, or deterministic summary prose that are not present in raw_input.
- Do not create work orders, approvals, maintenance events, replay requests, action IDs,
  state patches, or any closed-loop mutation.
- Do not claim repair completion, auto approval, real downtime reduction, root-cause certainty,
  or actual failure prevention.
- Return JSON only, matching the provided editable output schema.
- Return title, summary, and exactly one role summary for each role listed in output_roles.
- Keep role values unchanged. All prose must be read-only Korean and grounded in raw_input.
""".strip()


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
        role_rows = editable.get("role_summaries") or [
            {"role": role, "quote": "검토 필요"}
            for role in payload.get("output_roles") or ("field_operator", "process_manager")
        ]
        return {
            "title": editable.get("title") or "설비 검토 요약",
            "summary": editable.get("summary") or "제공된 입력을 검토해야 합니다.",
            "role_summaries": [
                {"role": item["role"], "quote": item.get("quote") or "검토 필요"}
                for item in role_rows
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
    """Project raw-ish fixture fields without Evidence Packet or deterministic answer prose."""
    del baseline
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
        "output_roles": ["field_operator", "process_manager"],
        "baseline_editable_fields": {
            "title": "",
            "summary": "",
            "role_summaries": [
                {"role": "field_operator", "quote": ""},
                {"role": "process_manager", "quote": ""},
            ],
        },
        "allowed_output_fields": ["title", "summary", "role_summaries"],
    }


def evidence_input_payload(packet: dict[str, Any]) -> dict[str, Any]:
    """Build Evidence Packet context while withholding deterministic answer prose."""
    empty_shape = {
        "title": "",
        "summary": "",
        "role_summaries": [
            {"role": "field_operator", "label": "", "quote": "", "source_refs": []},
            {"role": "process_manager", "label": "", "quote": "", "source_refs": []},
        ],
    }
    return build_agent_review_summary_prompt_payload(
        packet=packet,
        baseline_summary=empty_shape,
    )


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

    payload = raw_input_payload(packet, baseline) if arm == "B1" else evidence_input_payload(packet)
    injected = FaultInjectingProvider(provider, fault)
    attempts = MAX_ATTEMPTS if arm == "B3" else 1
    candidate: dict[str, Any] | None = None
    raw_llm_output: dict[str, Any] | None = None
    errors: list[str] = []
    failure_reason: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            editable = injected.generate_json(
                DIRECT_LLM_SYSTEM_PROMPT if arm == "B1" else AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
                payload,
                response_schema=agent_review_summary_editable_schema(),
                response_schema_name="agent_review_summary_editable",
            )
            raw_llm_output = editable
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
        raw_llm_output=raw_llm_output,
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
    raw_llm_output: dict[str, Any] | None = None,
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
        "fixture_id": packet["snapshot_basis"]["event_id"].replace("EVT-", ""),
        "iteration": iteration,
        "run_id": f"{arm}:{packet['snapshot_basis']['event_id']}:{iteration}",
        "arm": arm,
        "provider": getattr(provider, "name", "unknown"),
        "model": getattr(provider, "model", None),
        "status": trace["status"],
        "accepted": not errors,
        "schema_valid": not errors,
        "schema_validation": {"passed": not errors, "errors": errors},
        "llm_output": candidate,
        "raw_llm_output": raw_llm_output,
        "gold_accuracy": gold,
        "accuracy_goldset_score": (
            gold.get("accuracy_goldset_score") if isinstance(gold, dict) else None
        ),
        "matched_required_points": (
            gold.get("matched_required_points") if isinstance(gold, dict) else None
        ),
        "missing_required_points": (
            gold.get("missing_required_points") if isinstance(gold, dict) else None
        ),
        "role_required_points": (
            gold.get("role_scores") if isinstance(gold, dict) else None
        ),
        "forbidden_claims": (
            gold.get("must_not_claim_violations") if isinstance(gold, dict) else None
        ),
        "unsupported_claims": (
            gold.get("must_not_claim_violations") if isinstance(gold, dict) else None
        ),
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
        "usage_measurement": "estimated_from_serialized_payload_and_output_chars",
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
    rows: list[dict[str, Any]] = []
    for execution_order, (arm, packet, iteration) in enumerate(jobs, start=1):
        row = run_arm(
            arm=arm,
            packet=packet,
            iteration=iteration,
            provider=provider,
            state=state,
        )
        row["execution_order"] = execution_order
        rows.append(row)
    return {
        "status": "measured",
        "case_count": len(packets),
        "iterations_per_case": iterations,
        "arms": list(ARMS),
        "sample_size": len(rows),
        "seed": seed,
        "control_config": {
            "provider": getattr(provider, "name", "unknown"),
            "model": getattr(provider, "model", None),
            "temperature": (
                "provider_default_for_model"
                if str(getattr(provider, "model", "")).startswith("gpt-5")
                else 0
            ),
            "same_provider_model_and_generation_settings_for_all_arms": True,
            "usage_measurement": "estimated_from_serialized_payload_and_output_chars",
        },
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
        scores = [
            float(row["accuracy_goldset_score"])
            for row in arm_rows
            if row.get("accuracy_goldset_score") is not None
        ]
        costs = [
            row["estimated_cost"]["value"]
            for row in arm_rows
            if row["estimated_cost"]["state"] == "measured"
        ]
        fixture_scores: dict[str, list[float]] = {}
        required_matched = required_total = 0
        role_totals = {
            "field_operator": {"matched": 0, "total": 0},
            "process_manager": {"matched": 0, "total": 0},
        }
        for row in arm_rows:
            score = row.get("accuracy_goldset_score")
            if score is not None:
                fixture_scores.setdefault(row["fixture_id"], []).append(float(score))
            gold = row.get("gold_accuracy") or {}
            required_matched += len(gold.get("matched_required_points") or [])
            required_total += len(gold.get("matched_required_points") or []) + len(
                gold.get("missing_required_points") or []
            )
            for role, bucket in role_totals.items():
                role_score = (gold.get("role_scores") or {}).get(role) or {}
                bucket["matched"] += len(role_score.get("matched_points") or [])
                bucket["total"] += len(role_score.get("matched_points") or []) + len(
                    role_score.get("missing_points") or []
                )
        judgments: dict[str, set[str]] = {}
        for row in arm_rows:
            judgments.setdefault(row["case_id"], set()).add(
                json.dumps(row.get("core_judgment"), ensure_ascii=False, sort_keys=True)
            )
        cost_state = "measured" if len(costs) == len(arm_rows) else "not_measured"
        total_cost = round(sum(costs), 8) if cost_state == "measured" else None
        by_arm[arm] = {
            "runs": len(arm_rows),
            "gold_scored_runs": len(scores),
            "gold_unscored_runs": len(arm_rows) - len(scores),
            "gold_score_mean": round(statistics.mean(scores), 6) if scores else None,
            "gold_score_median": round(statistics.median(scores), 6) if scores else None,
            "gold_score_variance": round(statistics.pvariance(scores), 8) if scores else None,
            "gold_score_range": round(max(scores) - min(scores), 6) if scores else None,
            "fixture_gold_scores": {
                fixture_id: {
                    "mean": round(statistics.mean(values), 6),
                    "scores": values,
                    "range": round(max(values) - min(values), 6),
                }
                for fixture_id, values in sorted(fixture_scores.items())
            },
            "required_point_satisfaction_rate": (
                required_matched / required_total if required_total else None
            ),
            "role_required_point_satisfaction_rate": {
                role: (bucket["matched"] / bucket["total"] if bucket["total"] else None)
                for role, bucket in role_totals.items()
            },
            "missing_required_point_count": sum(
                len(row.get("missing_required_points") or []) for row in arm_rows
            ),
            "forbidden_claim_count": sum(
                len(row.get("forbidden_claims") or []) for row in arm_rows
            ),
            "unsupported_claim_count": sum(
                row["unsupported_claim_count"] or 0 for row in arm_rows
            ),
            "schema_validation_pass_rate": len(valid) / len(arm_rows) if arm_rows else None,
            "structural_core_field_exact_match_rate": (
                sum(len(values) == 1 for values in judgments.values()) / len(judgments)
                if judgments else None
            ),
            "input_tokens": sum(int(row["usage"]["input_tokens"]) for row in arm_rows),
            "output_tokens": sum(int(row["usage"]["output_tokens"]) for row in arm_rows),
            "total_tokens": sum(int(row["usage"]["total_tokens"]) for row in arm_rows),
            "fallback_count": sum(bool(row["fallback"]) for row in arm_rows),
            "retry_count": sum(max(0, int(row["attempt_count"]) - 1) for row in arm_rows),
            "reuse_count": sum(bool(row["reused"]) for row in arm_rows),
            "workflow_trace_completeness": (
                sum(bool((row.get("workflow_trace") or {}).get("trace_complete")) for row in arm_rows)
                / len(arm_rows)
                if arm == "B3" and arm_rows else None
            ),
            "estimated_total_cost": total_cost,
            "estimated_cost_per_run": (
                round(total_cost / len(arm_rows), 8)
                if total_cost is not None and arm_rows else None
            ),
            "estimated_cost_per_valid_output": (
                round(total_cost / len(valid), 8)
                if total_cost is not None and valid else None
            ),
            "cost_state": cost_state,
        }

    def delta(left: str, right: str) -> dict[str, Any]:
        l = by_arm[left]
        r = by_arm[right]
        return {
            "gold_score_mean_delta": _subtract(l["gold_score_mean"], r["gold_score_mean"]),
            "required_point_satisfaction_rate_delta": _subtract(
                l["required_point_satisfaction_rate"], r["required_point_satisfaction_rate"]
            ),
            "field_operator_satisfaction_rate_delta": _subtract(
                l["role_required_point_satisfaction_rate"]["field_operator"],
                r["role_required_point_satisfaction_rate"]["field_operator"],
            ),
            "process_manager_satisfaction_rate_delta": _subtract(
                l["role_required_point_satisfaction_rate"]["process_manager"],
                r["role_required_point_satisfaction_rate"]["process_manager"],
            ),
            "schema_validation_pass_rate_delta": _subtract(
                l["schema_validation_pass_rate"], r["schema_validation_pass_rate"]
            ),
            "total_token_delta": l["total_tokens"] - r["total_tokens"],
        }

    return {
        "by_arm": by_arm,
        "primary_comparison": "B3-B1",
        "comparison_order": ["B3-B1", "B2-B1", "B3-B2"],
        "comparisons": {
            "B3-B1": delta("B3", "B1"),
            "B2-B1": delta("B2", "B1"),
            "B3-B2": delta("B3", "B2"),
        },
        "structural_metric_note": (
            "structural_core_field_exact_match_rate is an exact-match consistency metric over "
            "selected structural fields, not semantic judgment agreement."
        ),
    }


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(left - right, 6)


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

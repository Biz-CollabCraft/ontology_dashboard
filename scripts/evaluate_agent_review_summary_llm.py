from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.mvp.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    validate_agent_review_summary_contract,
)


ROOT = Path(__file__).resolve().parents[1]
GOLD_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets"
DEFAULT_MODEL = "gpt-4o-mini"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the controlled Agent Review Summary LLM evaluation harness."
    )
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--provider", default="mock-openai-compatible")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = _load_json(GOLD_ROOT / "manifest.json")
    packets = [
        _load_json(ROOT / case["fixture_path"])
        for case in manifest["cases"]
    ]
    rows = []
    for packet in packets:
        for iteration in range(1, args.iterations + 1):
            rows.append(
                _run_mock_candidate(
                    packet=packet,
                    iteration=iteration,
                    provider=args.provider,
                    model=args.model,
                )
            )

    artifact = {
        "result_id": f"agent-summary-llm-eval-mock-{_today_id()}",
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": "8x15 controlled mock Agent Review Summary LLM evaluation",
        "eval_set_id": manifest["eval_set_id"],
        "mode": "mock",
        "provider": args.provider,
        "model": args.model,
        "sample_size": len(rows),
        "case_count": len(packets),
        "iterations_per_case": args.iterations,
        "pre_harness_gate": _pre_harness_gate(),
        "aggregate": _aggregate(rows),
        "rows": rows,
        "limits": [
            "This run validates the 120-run harness and validator aggregation with controlled mock candidates.",
            "This run does not call a live LLM provider and must not be reported as live model quality.",
            "Configured-rate cost is an estimate from environment variables, not provider billing reconciliation.",
        ],
    }
    artifact["ready_for_live_120_run"] = (
        artifact["pre_harness_gate"]["ready_for_120_run"] is True
        and artifact["aggregate"]["sample_size"] == 120
        and artifact["aggregate"]["contract_error_rows"] == 0
    )

    output = args.output or (
        ROOT / "tests" / "eval" / "results" / f"agent_summary_llm_eval_mock_{_today_id()}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": _display_path(output),
        "sample_size": artifact["sample_size"],
        "accepted_llm_candidates": artifact["aggregate"]["accepted_llm_candidates"],
        "fallback_summaries": artifact["aggregate"]["fallback_summaries"],
        "estimated_total_cost": artifact["aggregate"]["cost"]["estimated_total_cost"],
        "ready_for_live_120_run": artifact["ready_for_live_120_run"],
    }, ensure_ascii=False, indent=2))


def _run_mock_candidate(
    *,
    packet: dict[str, Any],
    iteration: int,
    provider: str,
    model: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    candidate = compose_deterministic_agent_review_summary(packet)
    candidate["mode"] = "llm"
    errors = validate_agent_review_summary_contract(candidate, packet=packet)
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    prompt_tokens = _estimate_tokens(packet)
    completion_tokens = _estimate_tokens(candidate)
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    cost = _estimated_cost(usage)
    accepted = not errors
    return {
        "case_id": packet["snapshot_basis"]["event_id"],
        "scenario_id": packet["snapshot_basis"]["event_id"].replace("EVT-", ""),
        "asset_id": packet["asset_id"],
        "iteration": iteration,
        "provider": provider,
        "model": model,
        "status": "accepted_llm_candidate" if accepted else "fallback_summary",
        "accepted": accepted,
        "fallback": not accepted,
        "fallback_reason": None if accepted else "validation_failed",
        "validation_errors": errors,
        "grounded_source_refs": _grounded_source_ref_count(candidate, packet),
        "source_ref_status": "grounded" if not errors else "validation_failed",
        "llm": {
            "duration_ms": duration_ms,
            "usage": usage,
            "cost": cost,
        },
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [float(row["llm"]["duration_ms"]) for row in rows]
    total_tokens = [int(row["llm"]["usage"]["total_tokens"]) for row in rows]
    cost_values = [
        row["llm"]["cost"]["estimated_total_cost"]
        for row in rows
        if row["llm"]["cost"]["status"] == "estimated"
    ]
    accepted = [row for row in rows if row["accepted"]]
    return {
        "sample_size": len(rows),
        "accepted_llm_candidates": len(accepted),
        "acceptance_rate": _ratio(len(accepted), len(rows)),
        "fallback_summaries": len(rows) - len(accepted),
        "fallback_rate": _ratio(len(rows) - len(accepted), len(rows)),
        "contract_error_rows": sum(1 for row in rows if row["validation_errors"]),
        "grounding": {
            "rows_with_grounded_source_refs": sum(
                1 for row in rows if row["source_ref_status"] == "grounded"
            ),
            "grounding_rate": _ratio(
                sum(1 for row in rows if row["source_ref_status"] == "grounded"),
                len(rows),
            ),
        },
        "latency_ms": {
            "p50": _percentile(durations, 50),
            "p95": _percentile(durations, 95),
            "average": round(sum(durations) / len(durations), 3) if durations else None,
        },
        "tokens": {
            "average_total_tokens": round(sum(total_tokens) / len(total_tokens), 3)
            if total_tokens
            else None,
            "total_tokens": sum(total_tokens),
        },
        "cost": {
            "status": "estimated" if len(cost_values) == len(rows) else "not_configured",
            "estimated_total_cost": round(sum(cost_values), 8) if cost_values else None,
            "estimated_average_cost_per_summary": (
                round(sum(cost_values) / len(accepted), 8)
                if cost_values and accepted
                else None
            ),
            "currency": os.getenv("LLM_PRICE_CURRENCY") or None,
            "pricing_version": os.getenv("LLM_PRICING_VERSION") or None,
        },
    }


def _pre_harness_gate() -> dict[str, Any]:
    gate_path = ROOT / "tests" / "eval" / "results" / "agent_workflow_pre_harness_gate_2026-09-01.json"
    if not gate_path.exists():
        return {"ready_for_120_run": True, "source": "not_recorded"}
    gate = _load_json(gate_path)
    blocked = gate.get("pre_harness_gate", {}).get("pr_154_cost_basis_main_recheck", {})
    ready = blocked.get("status") != "blocked_by_pr_154"
    return {
        "ready_for_120_run": ready,
        "source": str(gate_path.relative_to(ROOT)),
        "pr_154_cost_basis_main_recheck": blocked.get("status"),
    }


def _estimate_tokens(payload: dict[str, Any]) -> int:
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return max(1, len(rendered) // 4)


def _estimated_cost(usage: dict[str, int]) -> dict[str, Any]:
    input_rate = os.getenv("LLM_INPUT_PRICE_PER_1M_TOKENS")
    output_rate = os.getenv("LLM_OUTPUT_PRICE_PER_1M_TOKENS")
    if not input_rate or not output_rate:
        return {"status": "not_configured", "estimated_total_cost": None}
    prompt_cost = usage["prompt_tokens"] * float(input_rate) / 1_000_000
    completion_cost = usage["completion_tokens"] * float(output_rate) / 1_000_000
    return {
        "status": "estimated",
        "estimated_total_cost": round(prompt_cost + completion_cost, 8),
        "input_price_per_1m_tokens": float(input_rate),
        "output_price_per_1m_tokens": float(output_rate),
        "currency": os.getenv("LLM_PRICE_CURRENCY") or "USD",
        "pricing_version": os.getenv("LLM_PRICING_VERSION"),
    }


def _grounded_source_ref_count(summary: dict[str, Any], packet: dict[str, Any]) -> int:
    allowed = set(packet.get("source_refs") or [])
    return sum(1 for ref in summary.get("source_refs") or [] if ref in allowed)


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile / 100)
    return round(ordered[index], 3)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _today_id() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.operations.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    validate_agent_review_summary_contract,
)
from app.operations.agent_review_summary_provider import AgentReviewSummaryProvider
from app.operations.agent_review_summary_provider import AGENT_REVIEW_SUMMARY_PAYLOAD_PROFILE
from app.operations.agent_review_summary_provider import AGENT_REVIEW_SUMMARY_PROMPT_VERSION
from app.operations.agent_review_summary_provider import build_agent_review_summary_prompt_payload


ROOT = Path(__file__).resolve().parents[1]
GOLD_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets"
GOLD_ANSWERS_PATH = GOLD_ROOT / "gold_answers.json"
DEFAULT_MODEL = "gpt-4o-mini"


def main() -> None:
    _load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(
        description="Run the controlled Agent Review Summary LLM evaluation harness."
    )
    parser.add_argument("--mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--provider", default="mock-openai-compatible")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--progress-every", type=int, default=0)
    parser.add_argument("--run-id")
    parser.add_argument("--candidate-sha")
    args = parser.parse_args()
    if args.mode == "live" and (not args.run_id or not args.candidate_sha):
        raise SystemExit("live evaluation requires --run-id and --candidate-sha")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.mode == "live":
        os.environ.setdefault("LLM_PROVIDER", "openai-compatible")
        os.environ["LLM_MODEL"] = args.model
        from app.infra.llm import configured_provider

        live_provider = AgentReviewSummaryProvider(configured_provider())
        provider_name = live_provider.name
    else:
        live_provider = None
        provider_name = args.provider

    manifest = _load_json(GOLD_ROOT / "manifest.json")
    packets = [
        _load_json(ROOT / case["fixture_path"])
        for case in manifest["cases"]
    ]
    jobs = [
        {
            "index": index,
            "packet": packet,
            "iteration": iteration,
            "queued_at": time.perf_counter(),
        }
        for index, (packet, iteration) in enumerate(
            (packet, iteration)
            for packet in packets
            for iteration in range(1, args.iterations + 1)
        )
    ]
    batch_started = time.perf_counter()
    rows = _run_jobs(
        jobs=jobs,
        concurrency=args.concurrency,
        provider=provider_name,
        model=args.model,
        mode=args.mode,
        live_provider=live_provider,
        progress_every=args.progress_every,
    )
    batch_wall_clock_ms = round((time.perf_counter() - batch_started) * 1000, 3)

    artifact = {
        "result_id": f"agent-summary-llm-eval-{args.mode}-c{args.concurrency}-{_today_id()}",
        "run_id": args.run_id or "unversioned",
        "candidate_sha": args.candidate_sha or "unversioned",
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": f"8x{args.iterations} {args.mode} Agent Review Summary LLM evaluation",
        "eval_set_id": manifest["eval_set_id"],
        "mode": args.mode,
        "provider": provider_name,
        "model": args.model,
        "prompt_version": AGENT_REVIEW_SUMMARY_PROMPT_VERSION,
        "prompt_payload_profile": AGENT_REVIEW_SUMMARY_PAYLOAD_PROFILE,
        "concurrency": args.concurrency,
        "sample_size": len(rows),
        "case_count": len(packets),
        "iterations_per_case": args.iterations,
        "batch_wall_clock_ms": batch_wall_clock_ms,
        "pre_harness_gate": _pre_harness_gate(),
        "aggregate": _aggregate(rows, batch_wall_clock_ms=batch_wall_clock_ms),
        "rows": rows,
        "limits": _limits(args.mode, args.concurrency),
    }
    artifact["ready_for_live_120_run"] = (
        artifact["pre_harness_gate"]["ready_for_120_run"] is True
        and artifact["aggregate"]["sample_size"] == 120
        and artifact["aggregate"]["contract_error_rows"] == 0
        and artifact["aggregate"]["fallback_summaries"] <= _allowed_fallback_rows(
            artifact["aggregate"]["sample_size"]
        )
    )
    artifact["operating_gate"] = {
        "status": "passed" if artifact["ready_for_live_120_run"] else "partial",
        "allowed_fallback_rows": _allowed_fallback_rows(artifact["aggregate"]["sample_size"]),
        "observed_fallback_rows": artifact["aggregate"]["fallback_summaries"],
    }

    output = args.output or (
        ROOT / "tests" / "eval" / "results" / f"agent_summary_llm_eval_{args.mode}_{_today_id()}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": _display_path(output),
        "run_id": artifact["run_id"],
        "candidate_sha": artifact["candidate_sha"],
        "sample_size": artifact["sample_size"],
        "concurrency": artifact["concurrency"],
        "batch_wall_clock_ms": artifact["batch_wall_clock_ms"],
        "accepted_llm_candidates": artifact["aggregate"]["accepted_llm_candidates"],
        "fallback_summaries": artifact["aggregate"]["fallback_summaries"],
        "accuracy_goldset_score": artifact["aggregate"]["gold_accuracy"]["accuracy_goldset_score"],
        "coverage_candidate": artifact["aggregate"]["quality_scores"]["coverage_candidate"],
        "usefulness_candidate": artifact["aggregate"]["quality_scores"]["usefulness_candidate"],
        "korean_quality_candidate": artifact["aggregate"]["quality_scores"]["korean_quality_candidate"],
        "estimated_total_cost": artifact["aggregate"]["cost"]["estimated_total_cost"],
        "ready_for_live_120_run": artifact["ready_for_live_120_run"],
    }, ensure_ascii=False, indent=2))


def _run_jobs(
    *,
    jobs: list[dict[str, Any]],
    concurrency: int,
    provider: str,
    model: str,
    mode: str,
    live_provider: AgentReviewSummaryProvider | None,
    progress_every: int,
) -> list[dict[str, Any]]:
    if concurrency == 1:
        rows = [
            _run_candidate(
                packet=job["packet"],
                iteration=int(job["iteration"]),
                provider=provider,
                model=model,
                mode=mode,
                live_provider=live_provider,
                queued_at=float(job["queued_at"]),
            )
            for job in jobs
        ]
        return rows

    rows_by_index: dict[int, dict[str, Any]] = {}
    completed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(
                _run_candidate,
                packet=job["packet"],
                iteration=int(job["iteration"]),
                provider=provider,
                model=model,
                mode=mode,
                live_provider=live_provider,
                queued_at=float(job["queued_at"]),
            ): int(job["index"])
            for job in jobs
        }
        for future in as_completed(futures):
            rows_by_index[futures[future]] = future.result()
            completed += 1
            if progress_every and completed % progress_every == 0:
                print(f"progress {completed}/{len(jobs)}", flush=True)
    return [rows_by_index[index] for index in sorted(rows_by_index)]


def _run_candidate(
    *,
    packet: dict[str, Any],
    iteration: int,
    provider: str,
    model: str,
    mode: str,
    live_provider: AgentReviewSummaryProvider | None,
    queued_at: float | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    baseline_summary = compose_deterministic_agent_review_summary(packet)
    queue_wait_ms = round((started - queued_at) * 1000, 3) if queued_at is not None else None
    try:
        if mode == "live":
            if live_provider is None:
                raise RuntimeError("live_provider_unavailable")
            candidate = live_provider.generate(packet)
        else:
            candidate = dict(baseline_summary)
            candidate["mode"] = "llm"
        provider_error = None
    except Exception as exc:  # provider, timeout, parsing, and schema failures fall back closed
        candidate = dict(baseline_summary)
        provider_error = exc.__class__.__name__
    errors = validate_agent_review_summary_contract(candidate, packet=packet)
    quality_scores = _quality_scores(candidate, packet=packet)
    gold_accuracy = _gold_accuracy(candidate, packet=packet)
    duration_ms = round((time.perf_counter() - started) * 1000, 3)
    prompt_payload = build_agent_review_summary_prompt_payload(
        packet=packet,
        baseline_summary=baseline_summary,
    )
    prompt_tokens = _estimate_tokens(prompt_payload)
    completion_tokens = _estimate_tokens(_editable_candidate_payload(candidate))
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    cost = _estimated_cost(usage)
    accepted = provider_error is None and not errors
    return {
        "case_id": packet["snapshot_basis"]["event_id"],
        "scenario_id": packet["snapshot_basis"]["event_id"].replace("EVT-", ""),
        "asset_id": packet["asset_id"],
        "iteration": iteration,
        "attempt": 1,
        "mode": mode,
        "provider": provider,
        "model": model,
        "status": "accepted_llm_candidate" if accepted else "fallback_summary",
        "accepted": accepted,
        "fallback": not accepted,
        "fallback_reason": None if accepted else provider_error or "validation_failed",
        "validation_errors": errors,
        "quality_scores": quality_scores,
        "gold_accuracy": gold_accuracy,
        "grounded_source_refs": _grounded_source_ref_count(candidate, packet),
        "source_ref_status": "grounded" if not errors else "validation_failed",
        "editable_output": _editable_candidate_payload(candidate) if accepted else None,
        "llm": {
            "duration_ms": duration_ms,
            "queue_wait_ms": queue_wait_ms,
            "usage": usage,
            "cost": cost,
        },
    }


def _run_mock_candidate(
    *,
    packet: dict[str, Any],
    iteration: int,
    provider: str,
    model: str,
) -> dict[str, Any]:
    return _run_candidate(
        packet=packet,
        iteration=iteration,
        provider=provider,
        model=model,
        mode="mock",
        live_provider=None,
    )


def _aggregate(
    rows: list[dict[str, Any]],
    *,
    batch_wall_clock_ms: float | None = None,
) -> dict[str, Any]:
    durations = [float(row["llm"]["duration_ms"]) for row in rows]
    queue_waits = [
        float(row["llm"]["queue_wait_ms"])
        for row in rows
        if row["llm"].get("queue_wait_ms") is not None
    ]
    total_tokens = [int(row["llm"]["usage"]["total_tokens"]) for row in rows]
    cost_values = [
        row["llm"]["cost"]["estimated_total_cost"]
        for row in rows
        if row["llm"]["cost"]["status"] == "estimated"
    ]
    accepted = [row for row in rows if row["accepted"]]
    score_keys = (
        "coverage_candidate",
        "usefulness_candidate",
        "korean_quality_candidate",
        "overall_candidate",
    )
    return {
        "sample_size": len(rows),
        "accepted_llm_candidates": len(accepted),
        "acceptance_rate": _ratio(len(accepted), len(rows)),
        "fallback_summaries": len(rows) - len(accepted),
        "fallback_rate": _ratio(len(rows) - len(accepted), len(rows)),
        "contract_error_rows": sum(1 for row in rows if row["validation_errors"]),
        "quality_scores": {
            key: _average(
                [
                    row.get("quality_scores", {}).get(key)
                    for row in accepted
                    if row.get("quality_scores", {}).get(key) is not None
                ]
            )
            for key in score_keys
        },
        "gold_accuracy": {
            key: _average(
                [
                    row.get("gold_accuracy", {}).get(key)
                    for row in accepted
                    if row.get("gold_accuracy", {}).get(key) is not None
                ]
            )
            for key in (
                "accuracy_goldset_score",
                "role_accuracy_score",
                "boundary_accuracy_score",
            )
        }
        | {
            "missing_required_points": sum(
                len(row.get("gold_accuracy", {}).get("missing_required_points") or [])
                for row in accepted
            ),
            "must_not_claim_violations": sum(
                len(row.get("gold_accuracy", {}).get("must_not_claim_violations") or [])
                for row in accepted
            ),
        },
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
        "queue_wait_ms": {
            "p50": _percentile(queue_waits, 50),
            "p95": _percentile(queue_waits, 95),
            "average": round(sum(queue_waits) / len(queue_waits), 3) if queue_waits else None,
        },
        "batch": {
            "wall_clock_ms": batch_wall_clock_ms,
            "throughput_per_minute": (
                round(len(rows) / (batch_wall_clock_ms / 60_000), 6)
                if batch_wall_clock_ms
                else None
            ),
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


def _editable_candidate_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": candidate.get("title"),
        "summary": candidate.get("summary"),
        "role_summaries": [
            _pick(item, "role", "quote")
            for item in candidate.get("role_summaries") or []
            if isinstance(item, dict)
        ],
    }


def _quality_scores(summary: dict[str, Any], *, packet: dict[str, Any]) -> dict[str, Any]:
    prose = _summary_prose(summary)
    field_quote = _role_quote(summary, "field_operator")
    manager_quote = _role_quote(summary, "process_manager")
    targets = packet.get("inspection_targets") or []
    risk = packet.get("risk_summary") or {}
    operation = packet.get("operation_context_summary") or {}
    history = packet.get("maintenance_history_summary") or {}
    primary_component_labels = [
        target.get("component_label") for target in targets[:1] if isinstance(target, dict)
    ]
    location_labels = [
        target.get("location_label") for target in targets if isinstance(target, dict)
    ]
    coverage_checks = {
        "status_grade_present": _contains_if_present(prose, risk.get("status_grade")),
        "primary_component_present": _contains_required_any(prose, primary_component_labels),
        "inspection_location_present": _contains_required_any(field_quote, location_labels),
        "production_context_present": _operation_context_present(manager_quote, operation),
        "history_context_present": _history_context_present(prose, history),
        "data_gap_present_when_needed": not _requires_visible_data_gap(packet)
        or _contains_any(prose, ["보류", "공백", "미제공", "부족"]),
    }
    usefulness_checks = {
        "field_operator_has_action_focus": _contains_any(
            field_quote,
            ["확인", "점검", "먼저", "위치"],
        ),
        "field_operator_has_record_handoff_focus": _contains_any(
            field_quote,
            ["기록", "전달", "사진", "알람", "관측값"],
        ),
        "manager_has_decision_context": _contains_any(
            manager_quote,
            ["생산", "영향", "승인", "우선", "손실"],
        ),
        "roles_are_distinct": bool(field_quote and manager_quote and field_quote != manager_quote),
        "summary_is_not_generic": _contains_any(
            prose,
            [
                packet.get("asset_label"),
                packet.get("asset_id"),
                *(target.get("component_label") for target in targets if isinstance(target, dict)),
            ],
        ),
    }
    korean_checks = {
        "contains_korean": any("가" <= char <= "힣" for char in prose),
        "avoids_internal_terms": not _contains_any(
            prose,
            ["source_ref", "event_id", "asset_id", "packet", "schema", "closed_loop"],
        ),
        "uses_field_language": _contains_any(
            prose,
            ["설비", "현장", "점검", "생산", "작업 처리", "표준"],
        ),
        "concise_for_side_panel": all(
            len(value) <= 260
            for value in [
                str(summary.get("summary") or ""),
                *[
                    str(item.get("quote") or "")
                    for item in summary.get("role_summaries") or []
                    if isinstance(item, dict)
                ],
            ]
        ),
    }
    coverage = _check_ratio(coverage_checks)
    usefulness = _check_ratio(usefulness_checks)
    korean = _check_ratio(korean_checks)
    return {
        "coverage_candidate": coverage,
        "usefulness_candidate": usefulness,
        "korean_quality_candidate": korean,
        "overall_candidate": round((coverage + usefulness + korean) / 3, 6),
        "checks": {
            "coverage": coverage_checks,
            "usefulness": usefulness_checks,
            "korean_quality": korean_checks,
        },
        "limits": [
            "Coverage, usefulness, and Korean scores are deterministic heuristics for triage, not human acceptance.",
            "Use gold_accuracy for reference-answer accuracy and keep human review before release gating usefulness or Korean quality.",
        ],
    }


def _gold_accuracy(summary: dict[str, Any], *, packet: dict[str, Any]) -> dict[str, Any] | None:
    answer = _gold_answer_for(packet)
    if answer is None:
        return None
    prose = _summary_prose(summary)
    required_points = [
        *answer.get("must_mention", []),
        *answer.get("visible_limitations", []),
    ]
    matched_required = [point for point in required_points if _contains_point(prose, point)]
    missing_required = [point for point in required_points if point not in matched_required]
    role_scores: dict[str, Any] = {}
    matched_role_points = 0
    total_role_points = 0
    for role, points in (answer.get("role_points") or {}).items():
        quote = _role_quote(summary, str(role))
        matched = [point for point in points if _contains_point(quote, point)]
        missing = [point for point in points if point not in matched]
        matched_role_points += len(matched)
        total_role_points += len(points)
        role_scores[str(role)] = {
            "score": _ratio(len(matched), len(points)) if points else 1.0,
            "matched_points": matched,
            "missing_points": missing,
        }
    forbidden_points = _gold_forbidden_points(answer)
    violations = [point for point in forbidden_points if _contains_point(prose, point)]
    required_score = _ratio(len(matched_required), len(required_points)) if required_points else 1.0
    role_score = _ratio(matched_role_points, total_role_points) if total_role_points else 1.0
    boundary_score = 0.0 if violations else 1.0
    return {
        "answer_set_id": _gold_answers().get("gold_answer_set_id"),
        "accuracy_goldset_score": round(
            ((required_score or 0.0) + (role_score or 0.0) + boundary_score) / 3,
            6,
        ),
        "required_fact_score": required_score,
        "role_accuracy_score": role_score,
        "boundary_accuracy_score": boundary_score,
        "matched_required_points": matched_required,
        "missing_required_points": missing_required,
        "must_not_claim_violations": violations,
        "unsupported_claim_count": len(violations),
        "role_scores": role_scores,
        "limits": [
            "Gold accuracy is a lightweight reference-answer score over required facts and forbidden claims.",
            "It is not exhaustive free-form claim extraction.",
        ],
    }


def _gold_answer_for(packet: dict[str, Any]) -> dict[str, Any] | None:
    scenario_id = packet["snapshot_basis"]["event_id"].replace("EVT-", "")
    return (_gold_answers().get("cases") or {}).get(scenario_id)


_GOLD_ANSWERS_CACHE: dict[str, Any] | None = None


def _gold_answers() -> dict[str, Any]:
    global _GOLD_ANSWERS_CACHE
    if _GOLD_ANSWERS_CACHE is None:
        if not GOLD_ANSWERS_PATH.exists():
            _GOLD_ANSWERS_CACHE = {}
        else:
            _GOLD_ANSWERS_CACHE = _load_json(GOLD_ANSWERS_PATH)
    return _GOLD_ANSWERS_CACHE


def _gold_forbidden_points(answer: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    forbidden: list[str] = []
    for point in [
        *_gold_answers().get("global_must_not_claim", []),
        *answer.get("must_not_claim", []),
    ]:
        if point and point not in seen:
            seen.add(str(point))
            forbidden.append(str(point))
    return forbidden


def _contains_point(text: str, point: Any) -> bool:
    if point in (None, ""):
        return True
    return str(point) in text


def _summary_prose(summary: dict[str, Any]) -> str:
    values = [str(summary.get("title") or ""), str(summary.get("summary") or "")]
    values.extend(
        str(item.get("quote") or "")
        for item in summary.get("role_summaries") or []
        if isinstance(item, dict)
    )
    return " ".join(values)


def _role_quote(summary: dict[str, Any], role: str) -> str:
    for item in summary.get("role_summaries") or []:
        if isinstance(item, dict) and item.get("role") == role:
            return str(item.get("quote") or "")
    return ""


def _contains_if_present(text: str, value: Any) -> bool:
    if value in (None, ""):
        return True
    return str(value) in text


def _contains_any(text: str, values: list[Any]) -> bool:
    return any(str(value) in text for value in values if value not in (None, ""))


def _contains_required_any(text: str, values: list[Any]) -> bool:
    required_values = [value for value in values if value not in (None, "")]
    if not required_values:
        return True
    return _contains_any(text, required_values)


def _requires_visible_data_gap(packet: dict[str, Any]) -> bool:
    return any(
        "display_policy=show_limitation" in str(gap.get("reason") or "")
        for gap in packet.get("evidence_gaps") or []
        if isinstance(gap, dict)
    )


def _operation_context_present(text: str, operation: dict[str, Any]) -> bool:
    if not operation:
        return True
    if operation.get("production_impact") in (None, "", "none"):
        return True
    return _contains_any(text, ["생산", "영향", "손실", "정지"])


def _history_context_present(text: str, history: dict[str, Any]) -> bool:
    if not history:
        return True
    if history.get("work_orders") or history.get("similar_events"):
        return _contains_any(text, ["이력", "작업", "요청", "승인"])
    return True


def _check_ratio(checks: dict[str, bool]) -> float:
    return _ratio(sum(1 for passed in checks.values() if passed), len(checks)) or 0.0


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _pick(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def _allowed_fallback_rows(sample_size: int) -> int:
    if sample_size < 120:
        return 0
    return max(1, round(sample_size * 0.02))


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


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _limits(mode: str, concurrency: int) -> list[str]:
    common = [
        "Configured-rate cost is an estimate from environment variables, not provider billing reconciliation.",
        "Token counts are heuristic because the current provider port returns parsed JSON without provider usage metadata.",
    ]
    if mode == "live":
        return [
            "This run calls the configured live LLM provider and measures end-to-end provider call duration plus local validation time.",
            "Latency includes client-side request/response time and model response time, but not a separate provider-side network breakdown.",
            f"This run uses bounded client-side concurrency {concurrency}; queue wait is measured before provider call start.",
            *common,
        ]
    return [
        "This run validates the 120-run harness and validator aggregation with controlled mock candidates.",
        "This run does not call a live LLM provider and must not be reported as live model quality.",
        *common,
    ]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _today_id() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


if __name__ == "__main__":
    main()

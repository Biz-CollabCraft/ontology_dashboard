#!/usr/bin/env python3
"""Gold-set decision quality comparison for the bounded Decision Agent.

The gold labels are outside the prompt/tool payload. This script compares exact
human-authored gold actions against deterministic and live LLM planner outputs.
It is fixture-backed: no manufacturing mutation and no live factory KPI claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.infra.llm.provider import OpenAICompatibleProvider, configured_provider
from app.operations.decision_llm_planner import DecisionPlannerError, StructuredLLMDecisionPlanner
from app.operations.decision_policy import DecisionPolicyGuard
from app.operations.decision_support_agent import DecisionAgentRequest, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionAction as A
from app.operations.decision_tools import DecisionToolName as T
from evaluate_decision_agent_ambiguous import CASES, IDENTITY, build_tools
from evaluate_decision_agent_planner import RecordingProvider, usage_total


@dataclass(frozen=True)
class GoldCase:
    case_id: str
    gold_action: A | None
    required_tools: tuple[T, ...]
    must_not_actions: tuple[A, ...]
    rationale: str


def load_gold(path: Path) -> tuple[GoldCase, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "decision-agent-gold-v1":
        raise ValueError("unsupported gold schema_version")
    cases = []
    seen = set()
    for item in raw["cases"]:
        case_id = str(item["case_id"])
        if case_id in seen:
            raise ValueError(f"duplicate gold case: {case_id}")
        seen.add(case_id)
        action = item.get("gold_action")
        cases.append(GoldCase(
            case_id=case_id,
            gold_action=A(action) if action is not None else None,
            required_tools=tuple(T(name) for name in item["required_tools"]),
            must_not_actions=tuple(A(name) for name in item.get("must_not_actions", [])),
            rationale=str(item["rationale"]),
        ))
    source_case_ids = {case.id for case in CASES}
    missing = sorted(seen - source_case_ids)
    if missing:
        raise ValueError(f"gold cases missing from fixture benchmark: {missing}")
    return tuple(cases)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case_by_id() -> dict[str, Any]:
    return {case.id: case for case in CASES}


class HTTPRecordingProvider(OpenAICompatibleProvider):
    def __init__(self):
        super().__init__()
        self.http_attempts: list[dict[str, Any]] = []

    def _post_chat_completion(self, request_body):
        attempt = {"model": request_body.get("model"), "format": request_body["response_format"]["type"], "status": None}
        self.http_attempts.append(attempt)
        response = super()._post_chat_completion(request_body)
        attempt["status"] = response.status_code
        return response


class AuditedPlanner(StructuredLLMDecisionPlanner):
    def __init__(self, provider):
        super().__init__(provider)
        self.errors: list[str] = []

    def select_next_tool(self, **kwargs):
        try:
            return super().select_next_tool(**kwargs)
        except DecisionPlannerError as exc:
            self.errors.append(str(exc))
            raise

    def rank_actions(self, **kwargs):
        try:
            return super().rank_actions(**kwargs)
        except DecisionPlannerError as exc:
            self.errors.append(str(exc))
            raise


def action_value(action: A | None) -> str | None:
    return action.value if action else None


def successful_tools(session) -> tuple[str, ...]:
    return tuple(call.tool_name for call in session.tool_calls if call.status == "available")


def score_tools(actual: tuple[str, ...], required: tuple[T, ...]) -> tuple[bool, int, int]:
    required_values = tuple(tool.value for tool in required)
    counts = Counter(actual)
    extra = sum(n if name not in required_values else max(0, n - 1) for name, n in counts.items())
    missing = sum(tool not in actual for tool in required_values)
    return missing == 0 and extra == 0, extra, missing


def run_one(gold: GoldCase, *, arm: str, iteration: int, live: bool, provider: HTTPRecordingProvider | None = None):
    case = case_by_id()[gold.case_id]
    recording = RecordingProvider(provider) if provider else None
    planner = AuditedPlanner(recording) if arm == "llm" else None
    started = time.perf_counter()
    error = None
    result = None
    before_http = len(provider.http_attempts) if provider else 0
    try:
        result = ManufacturingDecisionAgent(tools=build_tools(case), planner=planner, sleep=lambda _: None).run(
            DecisionAgentRequest(
                identity=IDENTITY,
                actor_role="process_manager" if case.group == "maintenance" else "process_engineer",
                policy_facts=case.facts,
            )
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    proposal = result.session.proposal if result else None
    recommended = proposal.recommended_action if proposal else None
    actual_tools = successful_tools(result.session) if result else ()
    tool_ok, extra_tools, missing_tools = score_tools(actual_tools, gold.required_tools)
    calls = recording.calls if recording else []
    policy_contained = bool(result) and (recommended is None or recommended in result.policy.allowed_actions)
    blocked_action_avoided = recommended not in gold.must_not_actions
    exact_action = recommended == gold.gold_action
    top2 = []
    if proposal:
        top2 = [proposal.recommended_action, *proposal.alternative_actions][:2]
    return {
        "case_id": gold.case_id,
        "arm": arm,
        "iteration": iteration,
        "live_provider": live and arm == "llm",
        "engine": result.engine if result else "error",
        "terminal_status": result.session.status.value if result else "error",
        "recommended_action": action_value(recommended),
        "gold_action": action_value(gold.gold_action),
        "exact_action": exact_action,
        "top2_contains_gold": gold.gold_action in top2,
        "abstain_expected": gold.gold_action is None,
        "abstain_actual": recommended is None,
        "abstain_appropriate": (gold.gold_action is None and recommended is None) or (gold.gold_action is not None and recommended is not None),
        "must_not_action_avoided": blocked_action_avoided,
        "policy_contained": policy_contained,
        "actual_tools": list(actual_tools),
        "required_tools": [tool.value for tool in gold.required_tools],
        "required_tool_coverage": tool_ok,
        "unnecessary_tool_calls": extra_tools,
        "missing_required_tools": missing_tools,
        "human_approval_required": proposal.human_approval_required if proposal else None,
        "reasoning_summary": proposal.reasoning_summary if proposal else None,
        "rationale": gold.rationale,
        "planner_errors": list(result.session.planner_errors) if result else (planner.errors if planner else []),
        "error": error,
        "latency_seconds": elapsed,
        "planner_api_calls": len(calls),
        "http_requests": (len(provider.http_attempts) - before_http) if provider else 0,
        "http_attempts": provider.http_attempts[before_http:] if provider else [],
        "total_tokens": usage_total(calls, "total_tokens"),
        "prompt_tokens": usage_total(calls, "prompt_tokens"),
        "completion_tokens": usage_total(calls, "completion_tokens"),
        "api_phases": [call["response_schema_name"] for call in calls],
        "joint_quality_success": bool(result) and exact_action and tool_ok and blocked_action_avoided and policy_contained and error is None,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for arm in dict.fromkeys(row["arm"] for row in rows):
        subset = [row for row in rows if row["arm"] == arm]
        tokens = [row["total_tokens"] for row in subset if isinstance(row["total_tokens"], int)]
        output[arm] = {
            "runs": len(subset),
            "exact_action_rate": statistics.mean(row["exact_action"] for row in subset),
            "top2_contains_gold_rate": statistics.mean(row["top2_contains_gold"] for row in subset),
            "required_tool_coverage_rate": statistics.mean(row["required_tool_coverage"] for row in subset),
            "must_not_action_avoided_rate": statistics.mean(row["must_not_action_avoided"] for row in subset),
            "policy_contained_rate": statistics.mean(row["policy_contained"] for row in subset),
            "abstain_appropriateness_rate": statistics.mean(row["abstain_appropriate"] for row in subset),
            "joint_quality_success_rate": statistics.mean(row["joint_quality_success"] for row in subset),
            "mean_unnecessary_tool_calls": statistics.mean(row["unnecessary_tool_calls"] for row in subset),
            "mean_missing_required_tools": statistics.mean(row["missing_required_tools"] for row in subset),
            "mean_latency_seconds": statistics.mean(row["latency_seconds"] for row in subset),
            "mean_planner_api_calls": statistics.mean(row["planner_api_calls"] for row in subset),
            "mean_total_tokens": statistics.mean(tokens) if tokens else None,
            "fallback_or_error_runs": sum(bool(row["planner_errors"] or row["error"]) for row in subset),
            "actions": dict(Counter(row["recommended_action"] or "ABSTAIN" for row in subset)),
        }
    output["by_case"] = {
        case_id: {
            arm: {
                "actions": dict(Counter(row["recommended_action"] or "ABSTAIN" for row in rows if row["case_id"] == case_id and row["arm"] == arm)),
                "exact": sum(row["exact_action"] for row in rows if row["case_id"] == case_id and row["arm"] == arm),
                "runs": sum(1 for row in rows if row["case_id"] == case_id and row["arm"] == arm),
            }
            for arm in dict.fromkeys(row["arm"] for row in rows)
        }
        for case_id in dict.fromkeys(row["case_id"] for row in rows)
    }
    return output


def review_gold(gold: tuple[GoldCase, ...]) -> dict[str, Any]:
    source = case_by_id()
    issues: list[str] = []
    for item in gold:
        case = source[item.case_id]
        allowed = DecisionPolicyGuard().evaluate(case.facts).allowed_actions
        if item.gold_action is not None and item.gold_action not in allowed:
            issues.append(f"{item.case_id}: gold action outside deterministic policy")
        serialized_tools = []
        tools = build_tools(case)
        for tool in T:
            result = tools.call(tool_name=tool, identity=IDENTITY, retrieved_at=IDENTITY.decision_as_of)
            serialized_tools.append(result.model_dump_json())
        joined = "\n".join(serialized_tools)
        for forbidden in (item.case_id, item.rationale, "gold_action", "must_not_actions"):
            if forbidden and forbidden in joined:
                issues.append(f"{item.case_id}: gold/oracle leaked to tool payload: {forbidden[:40]}")
        if not item.required_tools:
            issues.append(f"{item.case_id}: required tools are empty")
        if item.gold_action in item.must_not_actions:
            issues.append(f"{item.case_id}: gold action is also listed as must_not")
    return {
        "reviewer": "deterministic_gold_oracle_guard_v1",
        "case_count": len(gold),
        "passed": not issues,
        "issues": issues,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", type=Path, default=Path("evaluation/decision_quality/decision-agent-gold-v1.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--arm", choices=("deterministic", "llm", "both"), default="both")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--live", action="store_true", help="Require a real external provider for the LLM arm")
    parser.add_argument("--model", default="", help="Override LLM_MODEL for live runs, e.g. gpt-5.6-luna")
    parser.add_argument("--reasoning-effort", default="", help="Override LLM_REASONING_EFFORT")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    if args.env_file:
        load_dotenv(args.env_file, override=True)
    if args.model:
        os.environ["LLM_MODEL"] = args.model
    if args.reasoning_effort:
        os.environ["LLM_REASONING_EFFORT"] = args.reasoning_effort
    gold = load_gold(args.gold)
    review = review_gold(gold)
    if not review["passed"]:
        raise SystemExit("gold review failed: " + json.dumps(review["issues"], ensure_ascii=False))
    arms = ("deterministic", "llm") if args.arm == "both" else (args.arm,)
    provider = None
    provider_name = None
    if "llm" in arms:
        if args.live:
            provider = HTTPRecordingProvider()
            if not provider.api_key or not provider.model:
                parser.error("live LLM provider requires API key and LLM_MODEL")
            provider_name = provider.name
        else:
            provider = configured_provider()
            provider_name = getattr(provider, "name", type(provider).__name__)
    rows = []
    jobs = [(item, arm, iteration) for item in gold for iteration in range(1, args.iterations + 1) for arm in arms]
    # Keep live LLM sequential by default so provider rate/latency is easier to read.
    for item, arm, iteration in jobs:
        rows.append(run_one(item, arm=arm, iteration=iteration, live=args.live, provider=provider if arm == "llm" else None))
        print(f"{item.case_id} {arm} {iteration}: {rows[-1]['recommended_action'] or 'ABSTAIN'} exact={rows[-1]['exact_action']}", flush=True)
    artifact = {
        "schema_version": "decision-agent-quality-eval-v1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Fixture-backed exact gold comparison for ambiguous Decision Agent cases; live_provider applies only to external LLM calls; no manufacturing mutation or live factory KPI measurement.",
        "gold_sha256": file_sha256(args.gold),
        "gold_file": str(args.gold),
        "gold_review": review,
        "iterations": args.iterations,
        "arms": list(arms),
        "live_provider": args.live,
        "provider": provider_name,
        "model": os.getenv("LLM_MODEL") if "llm" in arms else None,
        "reasoning_effort": os.getenv("LLM_REASONING_EFFORT") if "llm" in arms else None,
        "rows": rows,
        "aggregate": aggregate(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in artifact["aggregate"].items() if k != "by_case"}, ensure_ascii=False, indent=2))
    print(f"RESULT={args.output}")


if __name__ == "__main__":
    main()

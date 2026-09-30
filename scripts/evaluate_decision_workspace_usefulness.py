#!/usr/bin/env python3
"""Compare briefing, rule-only, and durable DecisionSession workflow usefulness.

This is not a live-factory KPI benchmark. It measures whether the product
workflow reaches a reviewable, policy-contained decision handoff with fewer
manual cross-checks than the earlier briefing-only surface.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from collections import Counter
from pathlib import Path
from statistics import mean

from app.infra.db.decision_run_repository import DecisionRunRepository
from app.operations.decision_durable_runner import DurableDecisionRunner
from app.operations.decision_session_service import DecisionSessionApplicationService
from app.operations.decision_support_agent import DecisionAgentRequest, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionSessionStatus
from evaluate_decision_agent_ambiguous import CASES, IDENTITY, build_tools


WORKFLOW_CHECKS = (
    "evidence_available",
    "action_or_abstain_available",
    "policy_contained",
    "human_review_required",
    "read_only_boundary",
    "bounded_tooling",
    "stable_session_identity",
    "duplicate_request_reuse",
    "recoverable_checkpoint",
    "stale_context_guard",
)


def request_for(case):
    return DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_manager" if case.group == "maintenance" else "process_engineer",
        policy_facts=case.facts,
    )


def packet_for(case):
    value = dict(case.packet_data)
    value["asset_id"] = IDENTITY.asset_id
    value["snapshot_basis"] = {
        "artifact_id": IDENTITY.evidence_snapshot_id,
        "observed_at": IDENTITY.decision_as_of.isoformat(),
    }
    value.setdefault("source_refs", ["artifact:ART-001"])
    return value


def row(label, case, checks, *, action=None, tool_calls=0, session_status=None, elapsed=0.0):
    passed = sum(bool(checks[name]) for name in WORKFLOW_CHECKS)
    return {
        "case": case.id,
        "group": case.group,
        "approach": label,
        "action": action,
        "session_status": session_status,
        "tool_calls": tool_calls,
        "workflow_checks_passed": passed,
        "workflow_checks_total": len(WORKFLOW_CHECKS),
        "workflow_readiness_rate": passed / len(WORKFLOW_CHECKS),
        "manual_cross_checks_remaining": len(WORKFLOW_CHECKS) - passed,
        "latency_seconds": elapsed,
        "checks": checks,
    }


def briefing_only(case):
    packet = packet_for(case)
    checks = {
        "evidence_available": bool(packet.get("source_refs")),
        "action_or_abstain_available": False,
        "policy_contained": False,
        "human_review_required": False,
        "read_only_boundary": True,
        "bounded_tooling": False,
        "stable_session_identity": False,
        "duplicate_request_reuse": False,
        "recoverable_checkpoint": False,
        "stale_context_guard": False,
    }
    return row("briefing_only", case, checks)


def rule_only(case):
    started = time.perf_counter()
    result = ManufacturingDecisionAgent(tools=build_tools(case), sleep=lambda _: None).run(request_for(case))
    elapsed = time.perf_counter() - started
    proposal = result.session.proposal
    action = proposal.recommended_action.value if proposal and proposal.recommended_action else None
    checks = {
        "evidence_available": bool(result.tool_results),
        "action_or_abstain_available": proposal is not None and (
            proposal.recommended_action is not None or bool(proposal.abstain_reason)
        ),
        "policy_contained": proposal is not None and (
            proposal.recommended_action is None or proposal.recommended_action in result.policy.allowed_actions
        ),
        "human_review_required": bool(proposal and proposal.human_approval_required),
        "read_only_boundary": result.session.mutation_attempted is False,
        "bounded_tooling": len(result.session.tool_calls) <= request_for(case).max_tool_calls,
        "stable_session_identity": False,
        "duplicate_request_reuse": False,
        "recoverable_checkpoint": False,
        "stale_context_guard": False,
    }
    return row(
        "rule_only_agent",
        case,
        checks,
        action=action,
        tool_calls=len(result.session.tool_calls),
        session_status=result.session.status.value,
        elapsed=elapsed,
    )


def durable_agent(case, database: Path):
    with sqlite3.connect(database) as connection:
        connection.executescript(Path("systems/backend/migrations/sqlite/0052_decision_agent_runs.sql").read_text())
    store = DecisionRunRepository(database, lease_seconds=0.3)
    request = request_for(case)
    session_id = f"DS-usefulness-{case.id}"
    agent = ManufacturingDecisionAgent(tools=build_tools(case), sleep=lambda _: None)
    started = time.perf_counter()
    result = DurableDecisionRunner(agent, store).run(request, session_id)
    duplicate = DurableDecisionRunner(agent, store).run(request, session_id)
    service = DecisionSessionApplicationService(
        packet_loader=lambda _: packet_for(case),
        agent_factory=lambda _: agent,
        run_store=store,
    )
    loaded = service.get(decision_session_id=session_id, identity=IDENTITY)
    elapsed = time.perf_counter() - started
    proposal = result.session.proposal
    action = proposal.recommended_action.value if proposal and proposal.recommended_action else None
    checks = {
        "evidence_available": bool(result.tool_results),
        "action_or_abstain_available": proposal is not None and (
            proposal.recommended_action is not None or bool(proposal.abstain_reason)
        ),
        "policy_contained": proposal is not None and (
            proposal.recommended_action is None or proposal.recommended_action in result.policy.allowed_actions
        ),
        "human_review_required": bool(proposal and proposal.human_approval_required),
        "read_only_boundary": result.session.mutation_attempted is False,
        "bounded_tooling": len(result.session.tool_calls) <= request.max_tool_calls,
        "stable_session_identity": result.session.decision_session_id == session_id,
        "duplicate_request_reuse": duplicate.session.decision_session_id == result.session.decision_session_id,
        "recoverable_checkpoint": loaded is not None and loaded.decision_session_id == session_id,
        "stale_context_guard": result.session.status in {
            DecisionSessionStatus.READY_FOR_REVIEW,
            DecisionSessionStatus.ABSTAINED,
            DecisionSessionStatus.STALE,
        },
    }
    return row(
        "durable_decision_session",
        case,
        checks,
        action=action,
        tool_calls=len(result.session.tool_calls),
        session_status=result.session.status.value,
        elapsed=elapsed,
    )


def aggregate(rows):
    output = {}
    for approach in dict.fromkeys(r["approach"] for r in rows):
        subset = [r for r in rows if r["approach"] == approach]
        output[approach] = {
            "cases": len(subset),
            "workflow_readiness_rate": mean(r["workflow_readiness_rate"] for r in subset),
            "mean_manual_cross_checks_remaining": mean(r["manual_cross_checks_remaining"] for r in subset),
            "mean_tool_calls": mean(r["tool_calls"] for r in subset),
            "mean_latency_seconds": mean(r["latency_seconds"] for r in subset),
            "actions": dict(Counter(r["action"] or "ABSTAIN_OR_NONE" for r in subset)),
            "check_rates": {
                name: mean(bool(r["checks"][name]) for r in subset)
                for name in WORKFLOW_CHECKS
            },
        }
    baseline = output["briefing_only"]
    for approach, summary in output.items():
        summary["manual_check_reduction_vs_briefing"] = (
            baseline["mean_manual_cross_checks_remaining"]
            - summary["mean_manual_cross_checks_remaining"]
        )
        summary["manual_check_reduction_rate_vs_briefing"] = (
            summary["manual_check_reduction_vs_briefing"]
            / baseline["mean_manual_cross_checks_remaining"]
            if baseline["mean_manual_cross_checks_remaining"]
            else 0
        )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory(prefix="decision-usefulness-") as temp:
        for case in CASES:
            rows.append(briefing_only(case))
            rows.append(rule_only(case))
            rows.append(durable_agent(case, Path(temp) / f"{case.id}.db"))
    artifact = {
        "scope": (
            "Workflow usefulness comparison over synthetic ambiguous decision cases; "
            "no LLM calls, no manufacturing mutation, no live factory KPI measurement"
        ),
        "workflow_checks": WORKFLOW_CHECKS,
        "rows": rows,
        "aggregate": aggregate(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(artifact["aggregate"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

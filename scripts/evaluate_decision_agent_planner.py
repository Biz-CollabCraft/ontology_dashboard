#!/usr/bin/env python3
"""Compare deterministic vs structured-LLM planning for the bounded decision agent.

This is a synthetic decision-agent evaluation over three designed scenarios. It
measures trajectory/action agreement with scenario gold, unnecessary read-only
tool calls, planner API latency/tokens, and fallback/error behavior. It does not
measure human decision time or live factory outcomes.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infra.llm.provider import configured_provider
from app.operations.decision_llm_planner import StructuredLLMDecisionPlanner
from app.operations.decision_policy import DecisionPolicyFacts
from app.operations.decision_support_agent import DecisionAgentRequest, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionAction
from app.operations.decision_tools import DecisionToolName, ManufacturingDecisionTools
from app.operations.operational_context_contract import (
    FreshnessMetadata,
    FreshnessState,
    OperationalContextEnvelope,
    OperationalContextStatus,
    OperationalRequestIdentity,
    OperationalScope,
)

NOW = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
IDENTITY = OperationalRequestIdentity(
    organization_id="ORG-001",
    project_id="manufacturing-demo-project",
    workspace_id="manufacturing-demo",
    asset_id="CNC-01",
    evidence_snapshot_id="ART-001",
    decision_as_of=NOW,
)


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    actor_role: str
    policy_facts: DecisionPolicyFacts
    gold_tools: tuple[DecisionToolName, ...]
    gold_action: DecisionAction


SCENARIOS = (
    Scenario(
        scenario_id="S1_DIAGNOSIS_VS_INSPECTION",
        actor_role="process_engineer",
        policy_facts=DecisionPolicyFacts(
            risk_status="warning",
            inspection_result_available=False,
            maintenance_recommended=False,
        ),
        gold_tools=(
            DecisionToolName.GET_ASSET_CONDITION,
            DecisionToolName.GET_INSPECTION_CONTEXT,
        ),
        gold_action=DecisionAction.REQUEST_INSPECTION,
    ),
    Scenario(
        scenario_id="S2_IMMEDIATE_VS_PLANNED_MAINTENANCE",
        actor_role="process_manager",
        policy_facts=DecisionPolicyFacts(
            risk_status="warning",
            inspection_result_available=True,
            maintenance_recommended=True,
            production_impact_known=True,
            maintenance_window_known=True,
            resource_readiness_known=True,
        ),
        gold_tools=(
            DecisionToolName.GET_MAINTENANCE_CONTEXT,
            DecisionToolName.GET_PRODUCTION_CONTEXT,
            DecisionToolName.GET_RESOURCE_READINESS,
        ),
        gold_action=DecisionAction.REVIEW_PLANNED_MAINTENANCE,
    ),
    Scenario(
        scenario_id="S3_MONITOR",
        actor_role="process_engineer",
        policy_facts=DecisionPolicyFacts(
            risk_status="attention",
            inspection_result_available=True,
            maintenance_recommended=False,
        ),
        gold_tools=(DecisionToolName.GET_ASSET_CONDITION,),
        gold_action=DecisionAction.MONITOR,
    ),
)


def packet(identity: OperationalRequestIdentity = IDENTITY) -> dict[str, Any]:
    return {
        "asset_id": identity.asset_id,
        "snapshot_basis": {
            "artifact_id": identity.evidence_snapshot_id,
            "observed_at": identity.decision_as_of.isoformat(),
        },
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.82},
        "model_expression_context": {
            "top_factors": [{"feature": "tool_wear_min", "value": 230}]
        },
        "inspection_targets": [{"component_id": "tooling"}],
        "sop_guidance": [{"sop_id": "SOP-1"}],
        "maintenance_history_summary": {
            "inspection_results": [],
            "work_orders": [],
            "maintenance_actions": [],
            "maintenance_events": [],
        },
        "source_refs": ["artifact:ART-001"],
        "evidence_gaps": [],
    }


class Port:
    def __init__(self, domain: str, data: dict[str, Any]):
        self.owner_domain = domain
        self.data = data

    def lookup(self, *, identity, retrieved_at):
        return OperationalContextEnvelope(
            owner_domain=self.owner_domain,
            scope=OperationalScope(
                organization_id=identity.organization_id,
                project_id=identity.project_id,
                workspace_id=identity.workspace_id,
                asset_id=identity.asset_id,
            ),
            status=OperationalContextStatus.AVAILABLE,
            source_version=f"{self.owner_domain}-v1",
            source_updated_at=retrieved_at,
            retrieved_at=retrieved_at,
            as_of=identity.decision_as_of,
            freshness=FreshnessMetadata(
                policy_version="eval",
                max_age_seconds=60,
                state=FreshnessState.FRESH,
            ),
            source_refs=(f"source:{self.owner_domain}",),
            data=self.data,
            limitations=(),
        )


def build_tools() -> ManufacturingDecisionTools:
    production = Port(
        "production",
        {
            "event_impact": {
                "estimated_downtime_minutes": 120,
                "estimated_lost_units": 25,
            },
            "production_orders": [{"order_id": "PO-1"}],
        },
    )
    maintenance = Port(
        "maintenance_readiness",
        {
            "maintenance_windows": [
                {"window_id": "MW-1", "expected_duration_minutes": 180}
            ],
            "concurrent_work_checks": [],
            "part_requirements": [{"part_requirement_id": "PR-1"}],
            "inventory_snapshots": [{"part_id": "P-1", "available_quantity": 1}],
            "technician_readiness": [{"technician_id": "T-1"}],
        },
    )
    return ManufacturingDecisionTools(
        packet_loader=packet,
        operational_ports={
            "production": production,
            "maintenance_readiness": maintenance,
        },
    )


class RecordingProvider:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.name = getattr(wrapped, "name", "provider")
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, system_prompt, payload, *, response_schema=None, response_schema_name="structured_response"):
        started = time.perf_counter()
        try:
            result = self.wrapped.generate_json_with_metadata(
                system_prompt,
                payload,
                response_schema=response_schema,
                response_schema_name=response_schema_name,
            )
        except Exception as exc:
            elapsed = time.perf_counter() - started
            self.calls.append(
                {
                    "response_schema_name": response_schema_name,
                    "latency_seconds": elapsed,
                    "usage": None,
                    "usage_measurement": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            raise
        elapsed = time.perf_counter() - started
        metadata = result.get("provider_metadata") or {}
        self.calls.append(
            {
                "response_schema_name": response_schema_name,
                "latency_seconds": elapsed,
                "usage": metadata.get("usage"),
                "usage_measurement": metadata.get("usage_measurement"),
                "error": None,
            }
        )
        return result["payload"]

    def generate_json_with_metadata(self, *args, **kwargs):
        return self.wrapped.generate_json_with_metadata(*args, **kwargs)


def successful_tools(session) -> tuple[str, ...]:
    return tuple(call.tool_name for call in session.tool_calls if call.status != "failed")


def tool_metrics(actual: tuple[str, ...], gold: tuple[DecisionToolName, ...]) -> tuple[bool, int, int]:
    expected = tuple(tool.value for tool in gold)
    exact = actual == expected
    extra = len([tool for tool in actual if tool not in expected])
    missing = len([tool for tool in expected if tool not in actual])
    return exact, extra, missing


def usage_total(calls: list[dict[str, Any]], key: str) -> int | None:
    usages = [call.get("usage") for call in calls]
    if not usages or any(not isinstance(usage, dict) for usage in usages):
        return None
    return sum(int(usage.get(key, 0) or 0) for usage in usages)


def run_arm(*, arm: str, scenario: Scenario, recording_provider: RecordingProvider | None):
    tools = build_tools()
    planner = None
    if arm == "llm":
        assert recording_provider is not None
        planner = StructuredLLMDecisionPlanner(recording_provider)
    agent = ManufacturingDecisionAgent(tools=tools, planner=planner, sleep=lambda _: None)
    before = len(recording_provider.calls) if recording_provider else 0
    started = time.perf_counter()
    result = agent.run(
        DecisionAgentRequest(
            identity=IDENTITY,
            actor_role=scenario.actor_role,
            policy_facts=scenario.policy_facts,
        )
    )
    elapsed = time.perf_counter() - started
    planner_calls = recording_provider.calls[before:] if recording_provider else []
    actual_tools = successful_tools(result.session)
    exact, extra, missing = tool_metrics(actual_tools, scenario.gold_tools)
    proposal = result.session.proposal
    action = proposal.recommended_action if proposal else None
    return {
        "arm": arm,
        "scenario_id": scenario.scenario_id,
        "engine": result.engine,
        "terminal_status": result.session.status.value,
        "actual_tools": list(actual_tools),
        "gold_tools": [tool.value for tool in scenario.gold_tools],
        "tool_path_exact": exact,
        "unnecessary_tool_calls": extra,
        "missing_gold_tool_calls": missing,
        "recommended_action": action.value if action else None,
        "gold_action": scenario.gold_action.value,
        "action_exact": action is scenario.gold_action,
        "abstained": action is None,
        "total_latency_seconds": elapsed,
        "planner_api_calls": len(planner_calls),
        "planner_api_latency_seconds": sum(call["latency_seconds"] for call in planner_calls),
        "prompt_tokens": usage_total(planner_calls, "prompt_tokens"),
        "completion_tokens": usage_total(planner_calls, "completion_tokens"),
        "total_tokens": usage_total(planner_calls, "total_tokens"),
        "planner_schemas": [call["response_schema_name"] for call in planner_calls],
        "planner_errors": [call["error"] for call in planner_calls if call.get("error")],
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in ("deterministic", "llm"):
        subset = [row for row in rows if row["arm"] == arm]
        if not subset:
            continue
        token_values = [row["total_tokens"] for row in subset if row["total_tokens"] is not None]
        result[arm] = {
            "runs": len(subset),
            "tool_path_exact_rate": sum(row["tool_path_exact"] for row in subset) / len(subset),
            "action_exact_rate": sum(row["action_exact"] for row in subset) / len(subset),
            "abstain_rate": sum(row["abstained"] for row in subset) / len(subset),
            "mean_unnecessary_tool_calls": statistics.mean(row["unnecessary_tool_calls"] for row in subset),
            "mean_missing_gold_tool_calls": statistics.mean(row["missing_gold_tool_calls"] for row in subset),
            "mean_total_latency_seconds": statistics.mean(row["total_latency_seconds"] for row in subset),
            "mean_planner_api_calls": statistics.mean(row["planner_api_calls"] for row in subset),
            "mean_planner_api_latency_seconds": statistics.mean(row["planner_api_latency_seconds"] for row in subset),
            "mean_total_tokens": statistics.mean(token_values) if token_values else None,
        }
    result["by_scenario"] = {}
    for scenario in SCENARIOS:
        result["by_scenario"][scenario.scenario_id] = {}
        for arm in ("deterministic", "llm"):
            subset = [row for row in rows if row["scenario_id"] == scenario.scenario_id and row["arm"] == arm]
            if subset:
                result["by_scenario"][scenario.scenario_id][arm] = {
                    "runs": len(subset),
                    "tool_path_exact": sum(row["tool_path_exact"] for row in subset),
                    "action_exact": sum(row["action_exact"] for row in subset),
                    "abstained": sum(row["abstained"] for row in subset),
                    "tool_paths": [row["actual_tools"] for row in subset],
                    "actions": [row["recommended_action"] for row in subset],
                }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    provider = RecordingProvider(configured_provider())
    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        for iteration in range(1, args.iterations + 1):
            deterministic = run_arm(arm="deterministic", scenario=scenario, recording_provider=None)
            deterministic["iteration"] = iteration
            rows.append(deterministic)
            try:
                llm = run_arm(arm="llm", scenario=scenario, recording_provider=provider)
                llm["iteration"] = iteration
                rows.append(llm)
            except Exception as exc:  # keep provider failures explicit in the artifact
                rows.append(
                    {
                        "arm": "llm",
                        "scenario_id": scenario.scenario_id,
                        "iteration": iteration,
                        "engine": "error",
                        "terminal_status": "error",
                        "actual_tools": [],
                        "gold_tools": [tool.value for tool in scenario.gold_tools],
                        "tool_path_exact": False,
                        "unnecessary_tool_calls": 0,
                        "missing_gold_tool_calls": len(scenario.gold_tools),
                        "recommended_action": None,
                        "gold_action": scenario.gold_action.value,
                        "action_exact": False,
                        "abstained": True,
                        "total_latency_seconds": 0.0,
                        "planner_api_calls": 0,
                        "planner_api_latency_seconds": 0.0,
                        "prompt_tokens": None,
                        "completion_tokens": None,
                        "total_tokens": None,
                        "planner_schemas": [],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    artifact = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scope": "3 synthetic manufacturing decision scenarios; deterministic vs structured-LLM planner; not a human-time or live-factory outcome measurement",
        "iterations_per_scenario": args.iterations,
        "provider": provider.name,
        "rows": rows,
        "aggregate": aggregate(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(artifact["aggregate"], ensure_ascii=False, indent=2))
    print(f"RESULT={args.output}")


if __name__ == "__main__":
    main()

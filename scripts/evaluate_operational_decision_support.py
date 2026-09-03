#!/usr/bin/env python3
"""Evaluate deterministic operational decision support implementation."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.mvp.operational_context_contract import OperationalRequestIdentity
from app.mvp.operational_context_ports import (
    FixtureMaintenanceReadinessContextReadPort,
    FixtureProductionDecisionContextReadPort,
    FixtureQualityDeliveryContextReadPort,
)
from app.mvp.operational_decision_agent import (
    BoundedOperationalDecisionAgent,
    OperationalAgentIntent,
    OperationalAgentRequest,
)
from app.mvp.operational_decision_brief import (
    DecisionBriefRole,
    compose_operational_decision_brief,
)
from app.mvp.operational_impact_simulation import (
    ImpactOption,
    ImpactSimulationAssumptions,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "data" / "fixtures" / "operation_context"
RETRIEVED_AT = datetime(2026, 9, 2, 2, tzinfo=timezone.utc)
IDENTITY = OperationalRequestIdentity(
    organization_id="ORG-001",
    project_id="manufacturing-demo-project",
    workspace_id="manufacturing-demo",
    asset_id="CNC-S04-L02-03",
    evidence_snapshot_id="ARTIFACT-GS-004",
    decision_as_of=datetime(2026, 9, 2, 1, tzinfo=timezone.utc),
)
ASSUMPTIONS = ImpactSimulationAssumptions(
    policy_version="operational-impact-demo-v1",
    primary_capacity_units={
        ImpactOption.STOP_NOW: 0,
        ImpactOption.PLANNED_MAINTENANCE: 120,
        ImpactOption.CONTINUE_OPERATION: 200,
    },
    alternative_capacity_allowed={
        ImpactOption.STOP_NOW: True,
        ImpactOption.PLANNED_MAINTENANCE: True,
        ImpactOption.CONTINUE_OPERATION: False,
    },
    source_refs=("policy:operational-impact-demo-v1",),
)


def evaluate(candidate_sha: str) -> dict[str, Any]:
    scenarios = [
        _scenario("ready", maintenance_ready=True, quality_released=True),
        _scenario("part_blocked", maintenance_ready=False, quality_released=True),
        _scenario("quality_hold", maintenance_ready=True, quality_released=False),
    ]
    external_api_fallback = _external_api_fallback_scenarios()
    role_briefs = _role_briefs()
    truth_fields = [
        "why_now",
        "relationships",
        "option_comparison",
        "source_refs",
    ]
    baseline = role_briefs[0]
    role_truth_consistent = all(
        all(getattr(item, field) == getattr(baseline, field) for field in truth_fields)
        for item in role_briefs[1:]
    )
    relation_source_complete = all(
        relation.source_refs
        and relation.source_version
        and relation.as_of
        for scenario in scenarios
        for relation in (
            scenario["result"].relation_context.relationships
            if scenario["result"].relation_context is not None
            else ()
        )
    )
    summary = {
        "evaluation_schema_version": "operational-decision-smoke-v1.0",
        "evaluation_mode": "deterministic_synthetic_smoke",
        "candidate_sha": candidate_sha,
        "live_llm_evaluation": False,
        "actual_mes_cmms_wms_qms_evaluation": False,
        "scenario_count": len(scenarios),
        "terminal_states": {
            item["name"]: item["result"].terminal_state.value
            for item in scenarios
        },
        "temporal_validation_pass_count": sum(
            item["result"].temporal_validation.get("valid") is True
            for item in scenarios
        ),
        "mutation_attempt_count": sum(
            item["result"].mutation_attempted for item in scenarios
        ),
        "recommendation_count": sum(
            compose_operational_decision_brief(
                request=item["request"],
                result=item["result"],
            ).recommendation
            is not None
            for item in scenarios
        ),
        "role_truth_consistent": role_truth_consistent,
        "relation_source_metadata_complete": relation_source_complete,
        "quality_hold_not_calculable": all(
            option.state.value == "not_calculable"
            for option in scenarios[2]["result"].impact_simulation.options
        ),
        "part_blocked_planned_maintenance_not_calculable": next(
            option
            for option in scenarios[1]["result"].impact_simulation.options
            if option.option is ImpactOption.PLANNED_MAINTENANCE
        ).state.value
        == "not_calculable",
        "external_api_status": external_api_fallback["external_api_status"],
        "external_api_fallback_reason": external_api_fallback[
            "external_api_fallback_reason"
        ],
        "external_api_fallback_isolation_pass": external_api_fallback[
            "fallback_isolation_pass"
        ],
        "limitations": [
            "Synthetic deterministic smoke; not production effectiveness evidence.",
            "Does not compare B1/B2/B3 live LLM quality.",
            "Does not claim actual MES/CMMS/WMS/QMS connectivity.",
        ],
    }
    summary["passed"] = all(
        [
            summary["temporal_validation_pass_count"] == len(scenarios),
            summary["mutation_attempt_count"] == 0,
            summary["recommendation_count"] == 0,
            summary["role_truth_consistent"],
            summary["relation_source_metadata_complete"],
            summary["quality_hold_not_calculable"],
            summary["part_blocked_planned_maintenance_not_calculable"],
            summary["external_api_fallback_isolation_pass"],
        ]
    )
    return summary


def _scenario(
    name: str,
    *,
    maintenance_ready: bool,
    quality_released: bool,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    maintenance = _load("maintenance-readiness-context-v1.json")
    if maintenance_ready:
        maintenance["inventory_snapshots"][0]["reserved_quantity"] = 0
        maintenance["inventory_snapshots"][0]["available_quantity"] = 2
    quality = _load("quality-delivery-context-v1.json")
    if quality_released:
        quality["quality_lots"][1]["quality_state"] = "released"
        quality["quality_lots"][1]["release_required"] = False
    ports = {
        "production": FixtureProductionDecisionContextReadPort(
            context=_load("operational-decision-context-v1.json"),
            source_ref="fixture:production",
        ),
        "maintenance_readiness": FixtureMaintenanceReadinessContextReadPort(
            context=maintenance,
            source_ref="fixture:maintenance",
        ),
        "quality_delivery": FixtureQualityDeliveryContextReadPort(
            context=quality,
            source_ref="fixture:quality",
        ),
    }
    if overrides:
        ports.update(overrides)
    request = OperationalAgentRequest(
        identity=IDENTITY,
        actor_role=DecisionBriefRole.PROCESS_MANAGER.value,
        intent=OperationalAgentIntent.MAINTENANCE_TIMING_DECISION,
        risk_status="critical",
    )
    result = BoundedOperationalDecisionAgent(
        ports=ports,
        impact_assumptions=ASSUMPTIONS,
    ).run(
        request=request,
        retrieved_at=RETRIEVED_AT,
        validated_at=RETRIEVED_AT + timedelta(seconds=3),
    )
    return {"name": name, "request": request, "result": result}


def _role_briefs():
    ready = _scenario(
        "role_consistency",
        maintenance_ready=True,
        quality_released=True,
    )
    briefs = []
    for role in DecisionBriefRole:
        request = ready["request"].model_copy(update={"actor_role": role.value})
        briefs.append(
            compose_operational_decision_brief(
                request=request,
                result=ready["result"],
            )
        )
    return briefs


@dataclass
class FailingExternalContextPort:
    owner_domain: str
    exc: BaseException

    def lookup(self, *, identity, retrieved_at):
        raise self.exc


def _external_api_fallback_scenarios() -> dict[str, Any]:
    cases = {
        "timeout": (
            "production",
            TimeoutError("external production API timed out"),
            "external_api_timeout",
        ),
        "malformed_response": (
            "quality_delivery",
            ValueError("missing source_version"),
            "external_api_malformed_response",
        ),
    }
    statuses: dict[str, str] = {}
    reasons: dict[str, str] = {}
    isolated: list[bool] = []
    for name, (domain, exc, expected_reason) in cases.items():
        scenario = _scenario(
            f"external_api_{name}",
            maintenance_ready=True,
            quality_released=True,
            overrides={
                domain: FailingExternalContextPort(
                    owner_domain=domain,
                    exc=exc,
                )
            },
        )
        result = scenario["result"]
        gap = next(
            item for item in result.gaps if item.get("domain") == domain
        )
        statuses[name] = str(gap.get("status") or "")
        reasons[name] = str(gap.get("fallback_reason") or "")
        isolated.append(
            statuses[name] == "failed"
            and reasons[name] == expected_reason
            and domain not in result.contexts
            and all(fact["owner_domain"] != domain for fact in result.facts)
        )
    return {
        "external_api_status": statuses,
        "external_api_fallback_reason": reasons,
        "fallback_isolation_pass": all(isolated),
    }


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.candidate_sha)
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

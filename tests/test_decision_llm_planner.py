from datetime import datetime, timezone

import pytest

from app.operations.decision_llm_planner import (
    DecisionPlannerError,
    StructuredLLMDecisionPlanner,
)
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


class FakeProvider:
    name = "fake"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def generate_json(self, system_prompt, payload, *, response_schema=None, response_schema_name="structured_response"):
        self.calls.append((response_schema_name, payload))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def packet(identity=IDENTITY):
    return {
        "asset_id": identity.asset_id,
        "snapshot_basis": {"artifact_id": identity.evidence_snapshot_id, "observed_at": identity.decision_as_of.isoformat()},
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.82},
        "model_expression_context": {"top_factors": [{"feature": "tool_wear_min", "value": 230}]},
        "inspection_targets": [{"component_id": "tooling"}],
        "sop_guidance": [{"sop_id": "SOP-1"}],
        "maintenance_history_summary": {"inspection_results": [], "work_orders": []},
        "source_refs": ["artifact:ART-001"],
        "evidence_gaps": [],
    }


class Port:
    def __init__(self, domain, data):
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
            freshness=FreshnessMetadata(policy_version="test", max_age_seconds=60, state=FreshnessState.FRESH),
            source_refs=(f"source:{self.owner_domain}",),
            data=self.data,
        )


def tools():
    return ManufacturingDecisionTools(
        packet_loader=packet,
        operational_ports={
            "production": Port("production", {"event_impact": {"estimated_downtime_minutes": 120}}),
            "maintenance_readiness": Port(
                "maintenance_readiness",
                {
                    "maintenance_windows": [{"expected_duration_minutes": 180}],
                    "concurrent_work_checks": [],
                    "part_requirements": [],
                    "inventory_snapshots": [],
                    "technician_readiness": [],
                },
            ),
        },
    )


def test_structured_planner_rejects_tool_outside_allowlist():
    planner = StructuredLLMDecisionPlanner(FakeProvider([
        {"next_tool": "get_resource_readiness", "reason": "need readiness"}
    ]))
    with pytest.raises(DecisionPlannerError, match="outside_allowlist"):
        planner.select_next_tool(
            policy_facts=DecisionPolicyFacts(risk_status="warning"),
            allowed_actions=(DecisionAction.REQUEST_INSPECTION,),
            available_tools=(DecisionToolName.GET_ASSET_CONDITION,),
            results={},
        )


def test_structured_planner_rejects_action_outside_policy():
    planner = StructuredLLMDecisionPlanner(FakeProvider([
        {
            "recommended_action": "REQUEST_MAINTENANCE",
            "alternative_actions": [],
            "confidence": "medium",
            "reasoning_summary": "maintenance",
            "abstain_reason": None,
        }
    ]))
    with pytest.raises(DecisionPlannerError, match="outside_policy"):
        planner.rank_actions(
            policy_facts=DecisionPolicyFacts(risk_status="warning"),
            allowed_actions=(DecisionAction.REQUEST_INSPECTION,),
            results={},
        )


def test_agent_uses_llm_selected_tool_path_and_policy_bounded_ranking():
    provider = FakeProvider([
        {"next_tool": "get_asset_condition", "reason": "confirm current anomaly"},
        {"next_tool": "get_inspection_context", "reason": "check SOP and inspection status"},
        {
            "recommended_action": "REQUEST_ADDITIONAL_DIAGNOSIS",
            "alternative_actions": ["REQUEST_INSPECTION"],
            "confidence": "medium",
            "reasoning_summary": "현장 점검 전 추가 진단으로 최근 변화를 보강하는 편이 적절합니다.",
            "abstain_reason": None,
        },
    ])
    planner = StructuredLLMDecisionPlanner(provider)
    agent = ManufacturingDecisionAgent(tools=tools(), planner=planner, sleep=lambda _: None)
    result = agent.run(DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_engineer",
        policy_facts=DecisionPolicyFacts(
            risk_status="warning",
            inspection_result_available=False,
            maintenance_recommended=False,
        ),
    ))

    assert result.engine == "langgraph+llm"
    assert [call.tool_name for call in result.session.tool_calls] == [
        DecisionToolName.GET_ASSET_CONDITION.value,
        DecisionToolName.GET_INSPECTION_CONTEXT.value,
    ]
    assert result.session.proposal.recommended_action is DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS
    assert result.session.proposal.alternative_actions == (DecisionAction.REQUEST_INSPECTION,)
    assert result.session.proposal.human_approval_required is True


def test_agent_falls_back_to_deterministic_planner_when_llm_selection_fails():
    planner = StructuredLLMDecisionPlanner(FakeProvider([
        RuntimeError("provider unavailable"),
        RuntimeError("provider unavailable"),
        RuntimeError("provider unavailable"),
    ]))
    result = ManufacturingDecisionAgent(
        tools=tools(), planner=planner, sleep=lambda _: None
    ).run(DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_engineer",
        policy_facts=DecisionPolicyFacts(
            risk_status="attention",
            inspection_result_available=True,
            maintenance_recommended=False,
        ),
    ))
    assert result.session.proposal.recommended_action is DecisionAction.MONITOR
    assert [call.tool_name for call in result.session.tool_calls] == [DecisionToolName.GET_ASSET_CONDITION.value]

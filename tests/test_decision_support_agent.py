from datetime import datetime, timezone

from app.operations.decision_policy import DecisionPolicyFacts
from app.operations.decision_support_agent import DecisionAgentRequest, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionAction, DecisionSessionStatus
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


def packet(identity=IDENTITY):
    return {
        "asset_id": identity.asset_id,
        "snapshot_basis": {"artifact_id": identity.evidence_snapshot_id, "observed_at": identity.decision_as_of.isoformat()},
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.82},
        "model_expression_context": {"top_factors": [{"feature": "tool_wear_min", "value": 230}]},
        "inspection_targets": [{"component_id": "tooling"}],
        "sop_guidance": [{"sop_id": "SOP-1"}],
        "maintenance_history_summary": {"inspection_results": [], "work_orders": [], "maintenance_actions": [], "maintenance_events": []},
        "source_refs": ["artifact:ART-001"],
        "evidence_gaps": [],
    }


class Port:
    def __init__(self, domain, data):
        self.owner_domain = domain
        self.data = data
        self.calls = 0

    def lookup(self, *, identity, retrieved_at):
        self.calls += 1
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
            limitations=(),
        )


def make_agent():
    production = Port("production", {
        "event_impact": {"estimated_downtime_minutes": 120, "estimated_lost_units": 25},
        "production_orders": [{"order_id": "PO-1"}],
    })
    maintenance = Port("maintenance_readiness", {
        "maintenance_windows": [{"window_id": "MW-1", "expected_duration_minutes": 180}],
        "concurrent_work_checks": [],
        "part_requirements": [{"part_requirement_id": "PR-1"}],
        "inventory_snapshots": [{"part_id": "P-1", "available_quantity": 1}],
        "technician_readiness": [{"technician_id": "T-1"}],
    })
    tools = ManufacturingDecisionTools(packet_loader=packet, operational_ports={
        "production": production,
        "maintenance_readiness": maintenance,
    })
    return ManufacturingDecisionAgent(tools=tools, sleep=lambda _seconds: None), production, maintenance


def tool_names(result):
    return [call.tool_name for call in result.session.tool_calls if call.status != "failed"]


def test_scenario_1_warning_routes_only_to_condition_and_inspection_tools():
    agent, production, maintenance = make_agent()
    result = agent.run(DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_engineer",
        policy_facts=DecisionPolicyFacts(
            risk_status="warning",
            inspection_result_available=False,
            maintenance_recommended=False,
        ),
    ))
    assert result.engine == "langgraph"
    assert result.session.status is DecisionSessionStatus.READY_FOR_REVIEW
    assert result.session.proposal.recommended_action is DecisionAction.REQUEST_INSPECTION
    assert result.session.proposal.alternative_actions == (DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS,)
    assert tool_names(result) == [
        DecisionToolName.GET_ASSET_CONDITION.value,
        DecisionToolName.GET_INSPECTION_CONTEXT.value,
    ]
    assert production.calls == 0
    assert maintenance.calls == 0


def test_scenario_2_maintenance_routes_to_maintenance_production_and_readiness_only():
    agent, production, maintenance = make_agent()
    result = agent.run(DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_manager",
        policy_facts=DecisionPolicyFacts(
            risk_status="warning",
            inspection_result_available=True,
            maintenance_recommended=True,
            production_impact_known=True,
            maintenance_window_known=True,
            resource_readiness_known=True,
        ),
    ))
    assert result.session.status is DecisionSessionStatus.READY_FOR_REVIEW
    assert result.session.proposal.recommended_action is DecisionAction.REVIEW_PLANNED_MAINTENANCE
    assert result.session.proposal.alternative_actions == (DecisionAction.REQUEST_MAINTENANCE,)
    assert tool_names(result) == [
        DecisionToolName.GET_MAINTENANCE_CONTEXT.value,
        DecisionToolName.GET_PRODUCTION_CONTEXT.value,
        DecisionToolName.GET_RESOURCE_READINESS.value,
    ]
    assert result.session.proposal.conflicts[0].conflict_type == "downtime_assumption_mismatch"
    assert production.calls == 1
    assert maintenance.calls == 2


def test_scenario_3_attention_stops_after_asset_context_and_recommends_monitoring():
    agent, production, maintenance = make_agent()
    result = agent.run(DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_engineer",
        policy_facts=DecisionPolicyFacts(
            risk_status="attention",
            inspection_result_available=True,
            maintenance_recommended=False,
        ),
    ))
    assert result.session.proposal.recommended_action is DecisionAction.MONITOR
    assert tool_names(result) == [DecisionToolName.GET_ASSET_CONDITION.value]
    assert production.calls == 0
    assert maintenance.calls == 0


def test_snapshot_mismatch_marks_session_stale_and_abstains():
    def wrong(identity):
        value = packet(identity)
        value["snapshot_basis"]["artifact_id"] = "OTHER"
        return value

    tools = ManufacturingDecisionTools(packet_loader=wrong, operational_ports={})
    result = ManufacturingDecisionAgent(tools=tools, sleep=lambda _seconds: None).run(DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_engineer",
        policy_facts=DecisionPolicyFacts(risk_status="warning"),
    ))
    assert result.session.status is DecisionSessionStatus.STALE
    assert result.session.proposal.recommended_action is None
    assert "new DecisionSession" in result.session.proposal.abstain_reason


def test_policy_blocks_all_recommendations_before_agent_tool_calls_when_snapshot_invalid():
    agent, production, maintenance = make_agent()
    result = agent.run(DecisionAgentRequest(
        identity=IDENTITY,
        actor_role="process_manager",
        policy_facts=DecisionPolicyFacts(snapshot_valid=False, risk_status="critical"),
    ))
    assert result.engine == "policy-only"
    assert result.session.status is DecisionSessionStatus.ABSTAINED
    assert result.session.tool_calls == ()
    assert production.calls == 0 and maintenance.calls == 0

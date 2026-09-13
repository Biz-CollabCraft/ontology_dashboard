from datetime import datetime, timezone

from app.operations.decision_session_service import DecisionSessionApplicationService
from app.operations.decision_support_agent import ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionAction
from app.operations.decision_tools import ManufacturingDecisionTools
from app.operations.operational_context_contract import OperationalRequestIdentity

NOW = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
IDENTITY = OperationalRequestIdentity(
    organization_id="ORG-001",
    project_id="manufacturing-demo-project",
    workspace_id="manufacturing-demo",
    asset_id="CNC-01",
    evidence_snapshot_id="ART-001",
    decision_as_of=NOW,
)


def packet(identity):
    return {
        "asset_id": identity.asset_id,
        "snapshot_basis": {
            "artifact_id": identity.evidence_snapshot_id,
            "observed_at": identity.decision_as_of.isoformat(),
        },
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.8},
        "review_draft": {"priority_label": "high"},
        "model_expression_context": {"top_factors": []},
        "inspection_targets": [],
        "sop_guidance": [],
        "maintenance_history_summary": {
            "inspection_results": [],
            "work_orders": [],
            "activities": [],
        },
        "operation_context_summary": {
            "estimated_downtime_minutes": 120,
            "estimated_lost_units": 25,
        },
        "source_refs": ["artifact:ART-001"],
    }


def agent_factory(identity):
    tools = ManufacturingDecisionTools(packet_loader=packet, operational_ports={})
    return ManufacturingDecisionAgent(tools=tools, sleep=lambda _seconds: None)


def test_session_service_derives_policy_server_side_and_reuses_identity_for_read():
    service = DecisionSessionApplicationService(packet_loader=packet, agent_factory=agent_factory)
    result = service.create(identity=IDENTITY, actor_role="process_engineer")
    assert result.session.proposal.recommended_action is DecisionAction.REQUEST_INSPECTION
    loaded = service.get(decision_session_id=result.session.decision_session_id, identity=IDENTITY)
    assert loaded == result.session


def test_session_service_does_not_return_session_for_different_scope():
    service = DecisionSessionApplicationService(packet_loader=packet, agent_factory=agent_factory)
    result = service.create(identity=IDENTITY, actor_role="process_engineer")
    other = IDENTITY.model_copy(update={"workspace_id": "other"})
    assert service.get(decision_session_id=result.session.decision_session_id, identity=other) is None

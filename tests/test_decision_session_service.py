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


def test_jev_contract_separates_execution_parse_check_completeness_and_provenance():
    service = DecisionSessionApplicationService(packet_loader=packet, agent_factory=agent_factory)
    result = service.create(identity=IDENTITY, actor_role="process_engineer")
    session = result.session.model_copy(update={
        "job_state": "completed",
        "parse_state": "parsed",
        "check_state": "failed",
        "completeness": "complete",
        "provenance": ("artifact:ART-001",),
    })
    assert session.job_state == "completed"
    assert session.parse_state == "parsed"
    assert session.check_state == "failed"
    assert session.completeness == "complete"
    assert session.provenance == ("artifact:ART-001",)


def test_jev_contract_exposes_incomplete_evidence_without_calling_it_success():
    service = DecisionSessionApplicationService(packet_loader=packet, agent_factory=agent_factory)
    result = service.create(identity=IDENTITY, actor_role="process_engineer")
    session = result.session.model_copy(update={
        "job_state": "completed",
        "parse_state": "partial",
        "check_state": "abstained",
        "completeness": "incomplete",
        "provenance": (),
        "proposal": result.session.proposal.model_copy(update={
            "recommended_action": None,
            "abstain_reason": "required_context_incomplete",
        }),
        "status": "abstained",
    })
    assert session.job_state == "completed"
    assert session.parse_state == "partial"
    assert session.check_state == "abstained"
    assert session.completeness == "incomplete"
    assert session.proposal.recommended_action is None


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


def test_session_expires_and_rejects_changed_source_facts():
    import pytest
    from datetime import timedelta
    service = DecisionSessionApplicationService(packet_loader=packet, agent_factory=agent_factory)
    result = service.create(identity=IDENTITY, actor_role="process_engineer")
    sid = result.session.decision_session_id
    assert result.session.snapshot_basis == packet(IDENTITY)["snapshot_basis"]
    def changed(identity):
        value = packet(identity)
        value["maintenance_history_summary"]["work_orders"] = [{"work_order_id":"new"}]
        return value
    service.packet_loader = changed
    with pytest.raises(ValueError, match="context_changed"):
        service.get(decision_session_id=sid,identity=IDENTITY)
    service.packet_loader = packet
    service._sessions[sid] = result.session.model_copy(update={"expires_at":datetime.now(timezone.utc)-timedelta(seconds=1)})
    with pytest.raises(ValueError, match="expired"):
        service.get(decision_session_id=sid,identity=IDENTITY)


def test_session_does_not_publish_if_context_changes_during_exploration():
    import pytest
    count = 0
    def changing(identity):
        nonlocal count
        count += 1
        value = packet(identity)
        if count > 1: value["risk_summary"]["failure_probability"] = 0.1
        return value
    service = DecisionSessionApplicationService(packet_loader=changing,agent_factory=agent_factory)
    with pytest.raises(ValueError,match="context_changed"):
        service.create(identity=IDENTITY,actor_role="process_engineer")
    assert not service._sessions


def test_recommendation_does_not_claim_absent_sop_was_verified():
    service = DecisionSessionApplicationService(packet_loader=packet,agent_factory=agent_factory)
    result=service.create(identity=IDENTITY,actor_role="process_engineer")
    assert "점검 기준을 확인" not in result.session.proposal.reasoning_summary
    assert "제공된 근거" in result.session.proposal.reasoning_summary

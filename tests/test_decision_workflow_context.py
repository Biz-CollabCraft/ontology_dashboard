"""Fixture-backed regression for the production DI and owner workflow overlay."""
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.operations.decision_workflow_context import with_decision_workflow
from app.operations.decision_policy import decision_policy_facts_from_packet
from app.operations.decision_support_agent import ManufacturingDecisionAgent
from app.operations.decision_tools import ManufacturingDecisionTools
from tests.test_decision_session_service import IDENTITY, NOW, packet
from tests.test_decision_llm_planner import tools as fixture_tools


def source():
    result = packet(IDENTITY)
    result["snapshot_basis"]["event_id"] = IDENTITY.evidence_snapshot_id
    return result


def owner(**changes):
    return dict(organization_id=IDENTITY.organization_id, project_id=IDENTITY.project_id,
                workspace_id=IDENTITY.workspace_id, asset_id=IDENTITY.asset_id,
                event_id=IDENTITY.evidence_snapshot_id,
                created_at=(NOW + timedelta(minutes=5)).isoformat(), **changes)


def completed():
    return {
        "work_orders": [owner(work_order_id="WO-1", status="completed")],
        "inspection_results": [owner(inspection_result_id="I-1", work_order_id="WO-1",
            outcome="maintenance_recommended", recorded_at=(NOW + timedelta(minutes=10)).isoformat())],
    }


def test_production_di_advances_recommendation_and_invalidates_old_session(monkeypatch):
    import app.dependencies as deps
    lineage = {}
    calls = []
    def event_lineage(**scope):
        calls.append(scope)
        return deepcopy(lineage)
    monkeypatch.setattr(deps, "get_service", lambda: SimpleNamespace(runtime_agent_review_packet=lambda *a, **k: source()))
    monkeypatch.setattr(deps, "get_maintenance_loop_service", lambda: SimpleNamespace(event_lineage=event_lineage))
    monkeypatch.setattr(deps, "database_target", lambda: "unused")
    monkeypatch.setenv("LLM_PROVIDER", "deterministic")
    deps.get_decision_session_service.cache_clear()
    try:
        service = deps.get_decision_session_service()
        service.agent_factory = lambda identity: ManufacturingDecisionAgent(
            tools=ManufacturingDecisionTools(packet_loader=service.packet_loader, operational_ports=fixture_tools().operational_ports),
            sleep=lambda _: None)
        first = service.create(identity=IDENTITY, actor_role="process_manager")
        assert first.session.proposal.recommended_action == "REQUEST_INSPECTION"
        lineage.update({"work_orders": [owner(work_order_id="WO-1", status="in_progress")]})
        with pytest.raises(ValueError, match="context_changed"):
            service.get(decision_session_id=first.session.decision_session_id, identity=IDENTITY)
        pending = service.create(identity=IDENTITY, actor_role="process_manager")
        assert "REQUEST_INSPECTION" not in pending.session.allowed_actions
        lineage.update(completed())
        result = service.create(identity=IDENTITY, actor_role="process_manager")
        assert result.session.proposal.recommended_action == "REVIEW_PLANNED_MAINTENANCE"
        assert "REQUEST_MAINTENANCE" in result.session.proposal.alternative_actions
        assert result.session.snapshot_basis == source()["snapshot_basis"]
        assert service.get(decision_session_id=result.session.decision_session_id, identity=IDENTITY) == result.session
        assert calls[0] == dict(organization_id=IDENTITY.organization_id, project_id=IDENTITY.project_id,
                               workspace_id=IDENTITY.workspace_id, event_id=IDENTITY.evidence_snapshot_id)
        tool = next(r for r in result.tool_results.values() if r.tool_name == "get_maintenance_context")
        assert tool.as_of == NOW + timedelta(minutes=10)
    finally:
        deps.get_decision_session_service.cache_clear()


@pytest.mark.parametrize("field", ["organization_id", "project_id", "workspace_id", "asset_id", "event_id"])
def test_rejects_cross_scope_records(field):
    lineage = completed()
    lineage["inspection_results"][0][field] = "other"
    with pytest.raises(ValueError, match="scope_mismatch"):
        with_decision_workflow(source(), lineage, IDENTITY)


@pytest.mark.parametrize("stamp", [(NOW + timedelta(days=1)).isoformat(), "invalid", "2026-09-14T01:00:00"])
def test_future_or_invalid_record_cannot_become_a_fact(stamp):
    lineage = completed()
    lineage["inspection_results"][0]["recorded_at"] = stamp
    result = with_decision_workflow(source(), lineage, IDENTITY, now=NOW + timedelta(hours=1))
    assert not decision_policy_facts_from_packet(result).maintenance_recommended
    assert result["maintenance_history_summary"]["inspection_results"] == []
    assert result["maintenance_history_summary"]["excluded_records"]

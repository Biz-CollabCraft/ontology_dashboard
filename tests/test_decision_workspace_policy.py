from unittest.mock import Mock
import pytest
from app.maintenance.decision_context import available_workflow_actions
from app.maintenance.service import MaintenanceLoopService
from app.operations.asset_detail_view_model import compose_closed_loop_read_model
from app.infra.db.asset_detail_read_adapter import PostgreSQLAssetDetailReadAdapter

def test_legacy_payload_has_no_canonical_evidence():
    adapter = PostgreSQLAssetDetailReadAdapter.__new__(PostgreSQLAssetDetailReadAdapter)
    adapter._latest_row = Mock(return_value={"prediction_result_payload": {"prediction": {"score": .8}}})
    adapter.validate_artifact = Mock()
    assert adapter.latest_result_artifact() is None
    adapter.validate_artifact.assert_not_called()

def test_malformed_declared_artifact_still_fails_validation():
    adapter = PostgreSQLAssetDetailReadAdapter.__new__(PostgreSQLAssetDetailReadAdapter)
    adapter._latest_row = Mock(return_value={"prediction_result_payload": {"artifact_id": "broken"}})
    adapter.validate_artifact = Mock(side_effect=ValueError("invalid producer artifact"))
    with pytest.raises(ValueError, match="invalid producer"):
        adapter.latest_result_artifact()

def test_latest_completed_action_does_not_reactivate_older_action():
    actions = available_workflow_actions({"maintenance_actions": [
        {"maintenance_action_id": "old", "status": "planned"},
        {"maintenance_action_id": "new", "status": "completed"},
    ]}, roles={"maintenance_technician"}, permissions={"field.tasks.update"}, actor_id="tech")
    assert actions == []

def test_replay_requires_matching_latest_event_and_no_restart():
    lineage = {"maintenance_actions": [{"maintenance_action_id": "new", "status": "completed"}],
               "maintenance_events": [{"maintenance_action_id": "new", "maintenance_event_id": "event"}]}
    args = dict(roles={"maintenance_technician"}, permissions={"field.tasks.update"}, actor_id="tech")
    assert available_workflow_actions(lineage, **args)[0]["action_id"] == "request_maintenance_replay"
    lineage["runtime_status"] = "ready"
    assert available_workflow_actions(lineage, **args) == []


@pytest.mark.parametrize("status,assigned,role,permission,enabled", [
    ("requested", None, "process_engineer", "field.tasks.update", True),
    ("approved", "engineer", "process_engineer", "field.tasks.update", True),
    ("approved", "other", "process_engineer", "field.tasks.update", False),
    ("in_progress", "other", "process_engineer", "field.tasks.update", False),
    ("requested", None, "system_admin", "field.tasks.update", False),
    ("requested", None, "process_engineer", "events.read", False),
])
def test_inspection_transition_policy(status, assigned, role, permission, enabled):
    actions = available_workflow_actions(
        {"work_orders": [{"work_order_id": "wo1", "work_type": "inspection",
                          "status": status, "assigned_to": assigned}]},
        roles={role}, permissions={permission}, actor_id="engineer",
    )
    assert len(actions) == 1
    assert actions[0]["target_id"] == "wo1"
    assert (actions[0]["disabled_reason"] is None) is enabled

def test_empty_lineage_still_exposes_evidence_phase():
    context = compose_closed_loop_read_model({}, prediction_available=True, evidence_available=True)
    assert context["lifecycle_summary"]["current_step"] == "evidence"
    assert context["available_actions"] == []

def test_invalid_snapshot_does_not_authorize_request():
    service = MaintenanceLoopService(Mock(), event_evidence_query=Mock())
    service.event_lineage = Mock(return_value={"work_orders": []})
    service.recommendation_input = Mock(side_effect=ValueError("snapshot mismatch"))
    result = service.decision_context(organization_id="org", project_id="p",
        workspace_id="w", event_id="e", snapshot_basis={}, roles={"process_manager"},
        permissions={"events.decision"}, actor_id="manager")
    assert result["available_actions"][0]["disabled_reason"]

def test_scope_error_is_not_suppressed():
    service = MaintenanceLoopService(Mock(), event_evidence_query=Mock())
    service.event_lineage = Mock(side_effect=ValueError("organization_id scope mismatch"))
    with pytest.raises(ValueError, match="scope mismatch"):
        service.decision_context(organization_id="org", project_id="p",
            workspace_id="w", event_id="e", snapshot_basis={}, roles={"process_manager"},
            permissions={"events.decision"}, actor_id="manager")

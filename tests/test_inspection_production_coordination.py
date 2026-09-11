import pytest
from app.maintenance.api_schema import InspectionCoordinationRequest, InspectionCoordinationResponse, InspectionExecutionRequest
from app.maintenance.maintenance_domain import InvalidTransition, IdempotencyConflict
from app.maintenance.maintenance_schema import WorkOrderStatus
from test_maintenance_loop_application import service, inspection_request, inspection_result
from test_maintenance_loop_router import client_for, BASE

SCOPE = dict(organization_id="org-1", project_id="project-1", workspace_id="workspace-1")
REQUEST = dict(work_summary="베어링 점검", downtime_minutes=30, affected_items="품목 A", note="교대 시간 협의")

@pytest.fixture
def accepted(tmp_path):
    loop = service(tmp_path)
    result = loop.request_inspection(**SCOPE, payload=inspection_request(), actor_id="engineer", actor_display_name="엔지니어", idempotency_key="create-order-001")
    wid = result["work_order_id"]
    loop.transition_inspection(**SCOPE, work_order_id=wid, target=WorkOrderStatus.APPROVED, actor_id="tech", actor_display_name="보전팀", idempotency_key="accept-order-001")
    loop.transition_inspection(**SCOPE, work_order_id=wid, target=WorkOrderStatus.IN_PROGRESS, actor_id="tech", actor_display_name="보전팀", idempotency_key="inspect-start-001")
    loop.complete_inspection(**SCOPE, work_order_id=wid, payload=inspection_result(), actor_id="tech", actor_display_name="보전팀", idempotency_key="inspect-result-001")
    return loop, wid

def request(loop, wid, key="coord-request-001", **overrides):
    return loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="request",
        payload=InspectionCoordinationRequest(**{**REQUEST, **overrides}), actor_id="tech", actor_display_name="보전팀", idempotency_key=key)

def reply(loop, wid, rid, decision="confirmed", key="coord-response-001"):
    return loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="response",
        payload=InspectionCoordinationResponse(request_id=rid, decision=decision, scheduled_window="9월 8일 14:00~14:30", production_response="품목 A 선행 생산 후 점검"),
        actor_id="manager", actor_display_name="생산관리자", idempotency_key=key)

def start(loop, wid):
    return loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="execution", payload=InspectionExecutionRequest(action="start"),
        actor_id="tech", actor_display_name="보전팀", idempotency_key="start-order-001")

def test_inspection_save_is_separate_from_approval_request(accepted, tmp_path):
    loop, wid = accepted
    assert loop.list_inspection_coordination(**SCOPE)["items"] == []
    saved = service(tmp_path).list_open_inspection_work_orders(**SCOPE)["items"][0]
    assert saved["inspection_result"]["outcome"] == "maintenance_recommended"
    with pytest.raises(PermissionError):
        loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="request",
            payload=InspectionCoordinationRequest(**REQUEST), actor_id="other-tech",
            actor_display_name="다른 담당자", idempotency_key="rejected-request-001")
    assert loop.list_inspection_coordination(**SCOPE)["items"] == []
    assert service(tmp_path).list_open_inspection_work_orders(**SCOPE)["items"][0]["inspection_result"] == saved["inspection_result"]
    req = request(loop, wid)
    assert request(loop, wid)["request_id"] == req["request_id"]
    assert len(loop.list_inspection_coordination(**SCOPE)["items"]) == 1


@pytest.mark.parametrize("outcome", ["maintenance_recommended", "no_action_required"])
def test_inspection_save_retry_after_lost_response(tmp_path, outcome):
    loop = service(tmp_path)
    wid = loop.request_inspection(**SCOPE, payload=inspection_request(), actor_id="engineer",
        actor_display_name="엔지니어", idempotency_key="create-order-001")["work_order_id"]
    for target, key in [(WorkOrderStatus.APPROVED, "accept-order-001"), (WorkOrderStatus.IN_PROGRESS, "inspect-start-001")]:
        loop.transition_inspection(**SCOPE, work_order_id=wid, target=target, actor_id="tech",
            actor_display_name="보전팀", idempotency_key=key)
    args = dict(**SCOPE, work_order_id=wid, payload=inspection_result(outcome), actor_id="tech",
        actor_display_name="보전팀", idempotency_key="inspect-result-001")
    first = loop.complete_inspection(**args)
    retried = service(tmp_path).complete_inspection(**args)
    assert retried["inspection_result_id"] == first["inspection_result_id"]
    assert retried["work_order_status"] == first["work_order_status"]
    assert retried["replayed"] is True
    assert loop.list_inspection_coordination(**SCOPE)["items"] == []


def test_request_creation_timestamp_is_preserved_in_queue_and_consultation(accepted):
    loop, wid = accepted
    order = loop.list_open_inspection_work_orders(**SCOPE)["items"][0]
    assert order["created_at"]
    from datetime import datetime
    assert datetime.fromisoformat(order["created_at"]) <= datetime.fromisoformat(order["assigned_at"])
    request(loop, wid)
    coordination = loop.list_inspection_coordination(**SCOPE)["items"][0]
    assert datetime.fromisoformat(coordination["work_order_created_at"]) == datetime.fromisoformat(order["created_at"])

def test_consultation_gates_start_and_survives_completion_and_reload(accepted, tmp_path):
    loop, wid = accepted
    with pytest.raises(InvalidTransition):
        start(loop, wid)
    req = request(loop, wid)
    with pytest.raises(InvalidTransition):
        start(loop, wid)
    reply(loop, wid, req["request_id"])
    start(loop, wid)
    loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="execution", payload=InspectionExecutionRequest(action="complete", note="정비 완료"), actor_id="tech", actor_display_name="보전팀", idempotency_key="complete-order-001")
    # A new repository/service instance reads the committed state, not browser memory.
    state = service(tmp_path).list_inspection_coordination(**SCOPE)["items"][0]
    assert state["status"] == "confirmed"
    assert state["work_order_status"] == "completed"
    assert state["responded_by_name"] == "생산관리자"
    assert state["inspection_result"]["findings"]
    assert len(state["history"]) == 2

def test_reconsultation_invalidates_previous_confirmation(accepted):
    loop, wid = accepted
    first = request(loop, wid)
    reply(loop, wid, first["request_id"])
    second = request(loop, wid, key="coord-request-002", downtime_minutes=45)
    assert second["request_id"] != first["request_id"]
    with pytest.raises(InvalidTransition):
        start(loop, wid)
    with pytest.raises(InvalidTransition):
        reply(loop, wid, first["request_id"], key="stale-response-001")
    reply(loop, wid, second["request_id"], key="coord-response-002")
    start(loop, wid)
    with pytest.raises(InvalidTransition):
        request(loop, wid, key="late-request-001")

def test_changes_requested_retries_and_ownership(accepted):
    loop, wid = accepted
    first = request(loop, wid)
    assert request(loop, wid)["request_id"] == first["request_id"]
    with pytest.raises(IdempotencyConflict):
        request(loop, wid, downtime_minutes=31)
    reply(loop, wid, first["request_id"], decision="changes_requested")
    with pytest.raises(InvalidTransition):
        start(loop, wid)
    with pytest.raises(PermissionError):
        loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="request", payload=InspectionCoordinationRequest(**REQUEST), actor_id="other-tech", actor_display_name="다른 담당자", idempotency_key="other-technician-001")
    assert len(loop.list_inspection_coordination(**SCOPE)["items"][0]["history"]) == 2

@pytest.mark.parametrize("role,phase,expected", [
    ("maintenance_technician", "production-consultation", 200),
    ("process_manager", "production-response", 200),
    ("process_engineer", "production-consultation", 403),
    ("maintenance_technician", "production-response", 403),
    ("process_manager", "production-consultation", 403),
])
def test_coordination_route_roles(role, phase, expected):
    client, stub = client_for(role)
    stub.coordinate_inspection = lambda **kwargs: {"status": kwargs["phase"]}
    payload = REQUEST if phase == "production-consultation" else dict(request_id="req-1", decision="confirmed", scheduled_window="내일 14시", production_response="일정 확보")
    response = client.post(f"{BASE}/inspection-work-orders/WO-1/{phase}", json=payload, headers={"Idempotency-Key": "role-test-001"})
    assert response.status_code == expected

def test_inspection_start_does_not_require_production_confirmation():
    client, stub = client_for("maintenance_technician")
    response = client.post(f"{BASE}/inspection-work-orders/WO-1/start", headers={"Idempotency-Key": "start-test-001"})
    assert response.status_code == 200
    assert stub.calls[0][1]["require_production_confirmation"] is False

def test_whitespace_and_negative_downtime_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        InspectionCoordinationRequest(**{**REQUEST, "work_summary": "  "})
    with pytest.raises(ValidationError):
        InspectionCoordinationRequest(**{**REQUEST, "downtime_minutes": -1})

def test_inspection_can_start_without_approval_and_no_action_closes(tmp_path):
    loop = service(tmp_path)
    result = loop.request_inspection(**SCOPE, payload=inspection_request(), actor_id="engineer", actor_display_name="엔지니어", idempotency_key="new-create-001")
    wid = result["work_order_id"]
    loop.transition_inspection(**SCOPE, work_order_id=wid, target=WorkOrderStatus.APPROVED, actor_id="tech", actor_display_name="보전팀", idempotency_key="new-accept-001")
    with pytest.raises(InvalidTransition):
        request(loop, wid)
    loop.transition_inspection(**SCOPE, work_order_id=wid, target=WorkOrderStatus.IN_PROGRESS, actor_id="tech", actor_display_name="보전팀", idempotency_key="new-start-001")
    loop.complete_inspection(**SCOPE, work_order_id=wid, payload=inspection_result("no_action_required"), actor_id="tech", actor_display_name="보전팀", idempotency_key="new-result-001")
    assert loop.list_open_inspection_work_orders(**SCOPE)["items"] == []

def test_inspection_result_retained_and_execution_cannot_bypass_approval(accepted):
    loop, wid = accepted
    assert loop.list_open_inspection_work_orders(**SCOPE)["items"][0]["inspection_result"]["outcome"] == "maintenance_recommended"
    with pytest.raises(InvalidTransition):
        loop.transition_inspection(**SCOPE, work_order_id=wid, target=WorkOrderStatus.IN_PROGRESS, actor_id="tech", actor_display_name="보전팀", idempotency_key="bypass-start-001")
    req = request(loop, wid)
    reply(loop, wid, req["request_id"])
    with pytest.raises(PermissionError):
        loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="execution", payload=InspectionExecutionRequest(action="start"), actor_id="other", actor_display_name="다른 사용자", idempotency_key="other-start-001")
    start(loop, wid)
    with pytest.raises(InvalidTransition):
        loop.coordinate_inspection(**SCOPE, work_order_id=wid, phase="execution", payload=InspectionExecutionRequest(action="complete"), actor_id="tech", actor_display_name="보전팀", idempotency_key="empty-result-001")

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.identity import AuthError, Principal
from app.maintenance.maintenance_router import create_maintenance_router


class Identity:
    @staticmethod
    def require_project(principal, project_id: str) -> None:
        if project_id not in principal.project_scopes:
            raise AuthError("project_scope_denied", "project denied")

    @staticmethod
    def require_workspace(principal, workspace_id: str) -> None:
        if workspace_id not in principal.workspace_scopes:
            raise AuthError("workspace_scope_denied", "workspace denied")


class Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def request_inspection(self, **values):
        self.calls.append(("request", values))
        return {"work_order_id": "INSPECTION-WO-1", "work_type": "inspection"}

    def transition_inspection(self, **values):
        self.calls.append(("transition", values))
        return {
            "work_order_id": values["work_order_id"],
            "work_order_status": values["target"].value,
        }

    def complete_inspection(self, **values):
        self.calls.append(("complete", values))
        return {
            "work_order_id": values["work_order_id"],
            "inspection_result_id": "INSPECTION-RESULT-1",
            "maintenance_event_id": None,
        }

    def create_manual_recommendation(self, **values):
        self.calls.append(("manual", values))
        return {"recommendation_id": "REC-1"}

    def decide_manual_recommendation(self, **values):
        self.calls.append(("decision", values))
        return {"decision_id": "DECISION-1", "work_order_id": "MAINTENANCE-WO-1"}

    def approve_maintenance_work_order(self, **values):
        self.calls.append(("maintenance_approve", values))
        return {"maintenance_action_id": "MAINTENANCE-ACTION-1"}

    def start_maintenance(self, **values):
        self.calls.append(("maintenance_start", values))
        return {"status": "in_progress"}

    def complete_maintenance(self, **values):
        self.calls.append(("maintenance_complete", values))
        return {"maintenance_event_id": "MAINTENANCE-EVENT-1"}

    def request_maintenance_replay(self, **values):
        self.calls.append(("maintenance_replay", values))
        return {"status": "replay_requested"}

    def event_lineage(self, **values):
        self.calls.append(("lineage", values))
        return {"event_id": values["event_id"], "activities": []}


def principal(role: str) -> Principal:
    permissions = {
        "process_manager": ["events.read", "events.decision"],
        "process_engineer": ["events.read", "field.tasks.update"],
        "maintenance_technician": ["events.read", "field.tasks.update"],
    }[role]
    return Principal(
        user_id=f"user-{role}",
        organization_id="org-1",
        email=f"{role}@example.test",
        display_name=role,
        status="active",
        roles=[role],
        permissions=permissions,
        workspace_scopes=["workspace-1"],
        project_scopes=["project-1"],
        project_roles={"project-1": [role]},
        active_project_id="project-1",
        active_project_roles=[role],
        is_admin=False,
        default_path="/",
        landing_key=role,
    )


def client_for(role: str) -> tuple[TestClient, Service]:
    actor = principal(role)
    service = Service()
    identity = Identity()

    def require_permission(permission: str):
        def dependency():
            if permission not in actor.permissions:
                raise AuthError("permission_denied", "permission denied")
            return actor

        return dependency

    app = FastAPI()

    @app.exception_handler(AuthError)
    async def auth_error_handler(_: Request, exc: AuthError):
        return JSONResponse(
            status_code=403,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    app.include_router(
        create_maintenance_router(
            require_permission=require_permission,
            get_identity_service=lambda: identity,
            get_maintenance_service=lambda: service,
            require_csrf=lambda: None,
        )
    )
    return TestClient(app), service


BASE = "/api/projects/project-1/workspaces/workspace-1/maintenance"
INSPECTION = {
    "event_id": "EVT-1",
}
RESULT = {
    "outcome": "maintenance_recommended",
    "checklist": [{"item_id": "tool", "status": "fail", "note": "worn"}],
    "measurements": [{"name": "tool_wear_min", "value": 220, "unit": "min"}],
    "findings": ["tool worn"],
    "note": "replacement candidate",
}


def test_manager_can_request_and_decide_but_idempotency_header_is_required() -> None:
    client, service = client_for("process_manager")

    missing = client.post(f"{BASE}/inspection-work-orders", json=INSPECTION)
    requested = client.post(
        f"{BASE}/inspection-work-orders",
        json=INSPECTION,
        headers={"Idempotency-Key": "inspection-request-001"},
    )
    decided = client.post(
        f"{BASE}/recommendations/REC-1/decisions",
        json={"disposition": "accept", "note": "approved"},
        headers={"Idempotency-Key": "recommendation-decision-001"},
    )

    assert missing.status_code == 422
    assert requested.status_code == 200
    assert decided.status_code == 200
    assert [name for name, _ in service.calls] == ["request", "decision"]


def test_inspection_request_rejects_caller_supplied_authorization_lineage() -> None:
    client, service = client_for("process_manager")
    forged = {
        **INSPECTION,
        "operational_decision_kind": "review_shutdown",
        "source_product_result_id": "FORGED-RESULT",
    }

    response = client.post(
        f"{BASE}/inspection-work-orders",
        json=forged,
        headers={"Idempotency-Key": "inspection-request-001"},
    )

    assert response.status_code == 422
    assert service.calls == []


def test_process_engineer_can_record_inspection_result() -> None:
    client, service = client_for("process_engineer")

    started = client.post(
        f"{BASE}/inspection-work-orders/INSPECTION-WO-1/start",
        headers={"Idempotency-Key": "inspection-start-001"},
    )
    completed = client.post(
        f"{BASE}/inspection-work-orders/INSPECTION-WO-1/complete",
        json=RESULT,
        headers={"Idempotency-Key": "inspection-complete-001"},
    )

    assert started.status_code == 200
    assert completed.status_code == 200
    assert completed.json()["maintenance_event_id"] is None
    assert [name for name, _ in service.calls] == ["transition", "complete"]


def test_maintenance_technician_cannot_take_process_engineer_inspection_action() -> None:
    client, service = client_for("maintenance_technician")

    response = client.post(
        f"{BASE}/inspection-work-orders/INSPECTION-WO-1/complete",
        json=RESULT,
        headers={"Idempotency-Key": "inspection-complete-001"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "role_context_denied"
    assert service.calls == []


def test_manager_approves_maintenance_but_cannot_execute_it() -> None:
    client, service = client_for("process_manager")

    missing_idempotency = client.post(
        f"{BASE}/maintenance-work-orders/MAINTENANCE-WO-1/approve",
        json={"simulation_session_id": "SIMULATION-SESSION-001"},
    )
    approved = client.post(
        f"{BASE}/maintenance-work-orders/MAINTENANCE-WO-1/approve",
        json={"simulation_session_id": "SIMULATION-SESSION-001"},
        headers={"Idempotency-Key": "maintenance-approve-001"},
    )
    denied = client.post(
        f"{BASE}/maintenance-actions/MAINTENANCE-ACTION-1/start",
        json={},
        headers={"Idempotency-Key": "maintenance-start-001"},
    )

    assert missing_idempotency.status_code == 422
    assert approved.status_code == 200
    assert denied.status_code == 403
    assert [name for name, _ in service.calls] == ["maintenance_approve"]


def test_technician_executes_and_requests_replay_without_caller_lineage() -> None:
    client, service = client_for("maintenance_technician")

    denied_approval = client.post(
        f"{BASE}/maintenance-work-orders/MAINTENANCE-WO-1/approve",
        json={"simulation_session_id": "SIMULATION-SESSION-001"},
        headers={"Idempotency-Key": "maintenance-approve-001"},
    )
    started = client.post(
        f"{BASE}/maintenance-actions/MAINTENANCE-ACTION-1/start",
        json={},
        headers={"Idempotency-Key": "maintenance-start-001"},
    )
    completed = client.post(
        f"{BASE}/maintenance-actions/MAINTENANCE-ACTION-1/complete",
        json={"outcome": "tool replaced"},
        headers={"Idempotency-Key": "maintenance-complete-001"},
    )
    replay = client.post(
        f"{BASE}/maintenance-events/MAINTENANCE-EVENT-1/replay",
        json={"restart_at": "2026-08-24T09:35:00Z"},
        headers={"Idempotency-Key": "maintenance-replay-001"},
    )

    assert denied_approval.status_code == 403
    assert started.status_code == 200
    assert completed.status_code == 200
    assert replay.status_code == 200
    assert [name for name, _ in service.calls] == [
        "maintenance_start",
        "maintenance_complete",
        "maintenance_replay",
    ]


def test_maintenance_commands_reject_caller_supplied_canonical_lineage() -> None:
    client, service = client_for("maintenance_technician")

    forged = client.post(
        f"{BASE}/maintenance-actions/MAINTENANCE-ACTION-1/complete",
        json={
            "outcome": "tool replaced",
            "source_product_result_id": "FORGED-RESULT",
            "equipment_id": "FORGED-EQUIPMENT",
            "state_patch": {"tool_wear_min": 999},
        },
        headers={"Idempotency-Key": "maintenance-complete-001"},
    )

    assert forged.status_code == 422
    assert service.calls == []

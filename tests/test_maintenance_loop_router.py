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
    "asset_id": "CNC-1",
    "equipment_id": "CNC-1",
    "asset_type": "cnc",
    "operational_decision_kind": "request_inspection",
    "source_product_result_id": "RESULT-1",
    "source_evidence_id": "EVIDENCE-1",
    "source_action_id": "ACTION-1",
    "source_schema_version": "product-result-artifact-v1",
    "source_policy_version": "recommendation-policy-v1",
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

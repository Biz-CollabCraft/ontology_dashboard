from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    build_manufacturing_service,
    get_decision_session_service,
    get_identity_service,
    get_service,
)
from app.identity import CSRF_COOKIE, IdentityService
from app.main import app
from app.operations.decision_session_service import DecisionSessionApplicationService
from app.operations.decision_support_agent import ManufacturingDecisionAgent
from app.operations.decision_tools import ManufacturingDecisionTools
from identity_test_support import build_identity_service

ROOT = Path(__file__).resolve().parents[1]
ASSET_ID = "CNC-S04-L02-03"
PARAMS = {
    "project_id": "manufacturing-demo-project",
    "workspace_id": "manufacturing-demo",
    "evidence_snapshot_id": "RESULT#CNC-S04-L02-03#2026-08-01T00:00:00+09:00",
    "decision_as_of": "2026-08-01T00:00:00+09:00",
    "role": "process_manager",
}


@pytest.fixture()
def api_client(tmp_path: Path):
    database_path = tmp_path / "decision-session-api.db"
    identity: IdentityService = build_identity_service(database_path, app_env="test", seed_demo=True)
    manufacturing = build_manufacturing_service(database_path, root=ROOT)

    def packet_loader(request_identity):
        return manufacturing.agent_review_packet(request_identity.asset_id, request_identity.project_id)

    def agent_factory(_identity):
        return ManufacturingDecisionAgent(
            tools=ManufacturingDecisionTools(packet_loader=packet_loader, operational_ports={}),
            sleep=lambda _seconds: None,
        )

    sessions = DecisionSessionApplicationService(packet_loader=packet_loader, agent_factory=agent_factory)
    app.dependency_overrides[get_service] = lambda: manufacturing
    app.dependency_overrides[get_identity_service] = lambda: identity
    app.dependency_overrides[get_decision_session_service] = lambda: sessions
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def login(client: TestClient):
    response = client.post("/api/auth/login", json={"email": "manager@ontology.local", "password": "Manager!2026"})
    assert response.status_code == 200, response.text


def csrf(client: TestClient):
    return {"X-CSRF-Token": str(client.cookies.get(CSRF_COOKIE))}


def test_create_and_read_decision_session_is_read_only_and_policy_bounded(api_client):
    client = api_client
    login(client)
    url = f"/api/objects/{ASSET_ID}/decision-sessions"
    created = client.post(url, params=PARAMS, headers=csrf(client))
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["engine"] == "langgraph"
    assert body["session"]["mutation_attempted"] is False
    assert body["session"]["proposal"]["human_approval_required"] is True
    assert body["session"]["proposal"]["recommended_action"] in body["session"]["allowed_actions"]
    session_id = body["session"]["decision_session_id"]

    read = client.get(
        f"/api/objects/{ASSET_ID}/decision-sessions/{session_id}",
        params={key: value for key, value in PARAMS.items() if key != "role"},
    )
    assert read.status_code == 200, read.text
    assert read.json()["session"]["decision_session_id"] == session_id


def test_decision_session_requires_csrf_for_creation(api_client):
    client = api_client
    login(client)
    response = client.post(f"/api/objects/{ASSET_ID}/decision-sessions", params=PARAMS)
    assert response.status_code == 403


def test_role_parameter_cannot_grant_manager_persona(api_client):
    from app.identity.identity_schema import DEMO_ACCOUNTS
    account = next(a for a in DEMO_ACCOUNTS if a["roles"] == ["process_engineer"])
    response = api_client.post("/api/auth/login",json={k:account[k] for k in ("email","password")})
    assert response.status_code == 200
    response = api_client.post(f"/api/objects/{ASSET_ID}/decision-sessions",params=PARAMS,headers=csrf(api_client))
    assert response.status_code == 403


def test_session_rejects_wrong_evidence_and_future_basis(api_client):
    login(api_client)
    for change in ({"evidence_snapshot_id":"wrong"},{"decision_as_of":"2026-07-01T00:00:00Z"}):
        response=api_client.post(f"/api/objects/{ASSET_ID}/decision-sessions",params={**PARAMS,**change},headers=csrf(api_client))
        assert response.status_code == 409

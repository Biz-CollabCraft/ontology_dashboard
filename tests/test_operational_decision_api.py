from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import (
    build_manufacturing_service,
    get_identity_service,
    get_operational_decision_support_service,
    get_service,
)
from app.identity import CSRF_COOKIE, IdentityService
from app.main import app
from app.mvp.operational_decision_support_service import (
    OperationalDecisionSupportService,
)
from identity_test_support import build_identity_service


ROOT = Path(__file__).resolve().parents[1]
ASSET_ID = "CNC-S04-L02-03"
PARAMS = {
    "project_id": "manufacturing-demo-project",
    "workspace_id": "manufacturing-demo",
    "evidence_snapshot_id": "ARTIFACT-GS-004",
    "decision_as_of": "2026-08-01T00:00:00+09:00",
    "role": "process_manager",
}


@pytest.fixture()
def api_client(tmp_path: Path):
    database_path = tmp_path / "decision-support-api.db"
    identity: IdentityService = build_identity_service(
        database_path,
        app_env="test",
        seed_demo=True,
    )
    service = build_manufacturing_service(database_path, root=ROOT)
    decision_support = OperationalDecisionSupportService(ROOT, database_path)
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_identity_service] = lambda: identity
    app.dependency_overrides[get_operational_decision_support_service] = (
        lambda: decision_support
    )
    with TestClient(app) as client:
        yield client, decision_support
    app.dependency_overrides.clear()


def login(client: TestClient, email: str, password: str) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": str(client.cookies.get(CSRF_COOKIE))}


def test_get_is_cache_only_then_manager_materializes_and_reuses(api_client) -> None:
    client, decision_support = api_client
    login(client, "manager@ontology.local", "Manager!2026")
    url = f"/api/objects/{ASSET_ID}/decision-support-brief"

    empty = client.get(url, params=PARAMS)
    assert empty.status_code == 202
    assert empty.json()["brief"] is None
    assert decision_support.workflow_runs(
        project_id="manufacturing-demo-project",
        asset_id=ASSET_ID,
        status=None,
        limit=20,
    ) == []

    created = client.post(url, params=PARAMS, headers=csrf(client))
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["brief"]["mutation_available"] is False
    assert body["brief"]["recommendation"] is None
    assert body["trace"]["reused"] is False
    assert body["trace"]["temporal_validation"] == "passed"

    cached = client.get(url, params=PARAMS)
    assert cached.status_code == 200
    assert cached.json()["brief"] == body["brief"]
    assert cached.json()["trace"]["reused"] is True

    reused = client.post(url, params=PARAMS, headers=csrf(client))
    assert reused.status_code == 200
    assert reused.json()["trace"]["reused"] is True
    assert len(decision_support.workflow_runs(
        project_id="manufacturing-demo-project",
        asset_id=ASSET_ID,
        status=None,
        limit=20,
    )) == 1
    restarted = OperationalDecisionSupportService(ROOT, decision_support.database_path)
    assert len(restarted.workflow_runs(
        project_id="manufacturing-demo-project",
        asset_id=ASSET_ID,
        status=None,
        limit=20,
    )) == 1


def test_materialize_requires_csrf_and_permission(api_client) -> None:
    client, _ = api_client
    login(client, "manager@ontology.local", "Manager!2026")
    url = f"/api/objects/{ASSET_ID}/decision-support-brief"
    assert client.post(url, params=PARAMS).status_code == 403

    login(client, "engineer@ontology.local", "Engineer!2026")
    denied = client.post(url, params=PARAMS, headers=csrf(client))
    assert denied.status_code == 403


def test_audit_runs_are_admin_only_and_read_only(api_client) -> None:
    client, _ = api_client
    login(client, "manager@ontology.local", "Manager!2026")
    url = f"/api/objects/{ASSET_ID}/decision-support-brief"
    assert client.post(url, params=PARAMS, headers=csrf(client)).status_code == 200

    denied = client.get(
        "/api/projects/manufacturing-demo-project/decision-support-workflow-runs"
    )
    assert denied.status_code == 403

    login(client, "admin@ontology.local", "OntologyAdmin!2026")
    response = client.get(
        "/api/projects/manufacturing-demo-project/decision-support-workflow-runs",
        params={"asset_id": ASSET_ID},
    )
    assert response.status_code == 200
    rows = response.json()["items"]
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert all(
        key not in rows[0]
        for key in ("recommendation", "work_order", "maintenance_action")
    )


def test_scope_and_future_timestamp_are_rejected(api_client) -> None:
    client, _ = api_client
    login(client, "manager@ontology.local", "Manager!2026")
    url = f"/api/objects/{ASSET_ID}/decision-support-brief"
    bad_scope = client.get(url, params={**PARAMS, "workspace_id": "other"})
    assert bad_scope.status_code == 403
    future = client.get(
        url,
        params={**PARAMS, "decision_as_of": "2099-01-01T00:00:00Z"},
    )
    assert future.status_code == 422

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from systems.backend.app.system_operations.e2e_router import build_e2e_router


class FakeE2EService:
    def list_runs(self, *, organization_id, limit):
        return {"items": [{"run_id": "run-1", "status": "succeeded"}], "count": 1, "organization": organization_id}

    def get_run(self, run_id, *, organization_id):
        if run_id == "missing": raise KeyError(run_id)
        return {"run_id": run_id, "status": "succeeded"}

    def timeline(self, run_id, *, organization_id):
        return {"run": self.get_run(run_id, organization_id=organization_id), "events": []}

    def get_event(self, event_id, *, organization_id):
        if event_id == "missing": raise KeyError(event_id)
        return {"timeline_event_id": event_id, "run_id": "run-1"}

    def list_alerts(self, *, organization_id, limit):
        return {"items": [], "count": 0}


def _client():
    app = FastAPI()
    principal = SimpleNamespace(organization_id="org-1")

    def require_permission(permission):
        assert permission == "system.e2e.read"
        return lambda: principal

    app.include_router(build_e2e_router(get_service=lambda: FakeE2EService(), require_permission=require_permission))
    return TestClient(app)


def test_e2e_routes_are_reachable_and_scoped():
    client = _client()
    assert client.get("/api/system/e2e-runs").json()["count"] == 1
    assert client.get("/api/system/e2e-runs/run-1/timeline").json()["run"]["run_id"] == "run-1"
    assert client.get("/api/system/e2e-events/event-1").status_code == 200
    assert client.get("/api/system/alerts").json() == {"items": [], "count": 0}


def test_e2e_missing_resources_are_404():
    client = _client()
    assert client.get("/api/system/e2e-runs/missing").status_code == 404
    assert client.get("/api/system/e2e-events/missing").status_code == 404

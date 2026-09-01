from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.system_operations.mapping_draft_router import build_mapping_draft_router


class StubService:
    def list(self): return []
    def get(self, draft_id): return {"draft_id": draft_id, "revision": 1}
    def create(self, mapping_id, target_version, base_version, actor): return {"draft_id": "draft-1", "mapping_id": mapping_id, "target_version": target_version, "base_version": base_version, "created_by": actor}
    def update(self, draft_id, revision, payload, actor): return {"draft_id": draft_id, "revision": revision + 1, "payload": payload, "updated_by": actor}
    def diff(self, draft_id): return {"draft_id": draft_id, "summary": {"added": 0, "removed": 0, "changed": 0}, "changes": []}
    def validate(self, draft_id, actor): return {"draft_id": draft_id, "status": "validated", "updated_by": actor}
    def publish(self, draft_id, revision, actor): return {"draft": {"draft_id": draft_id, "status": "published"}, "registry_reconciled": True}


def _client() -> TestClient:
    app = FastAPI()
    principal = SimpleNamespace(user_id="system-operator")
    app.include_router(build_mapping_draft_router(
        get_service=lambda: StubService(),
        require_permission=lambda _: (lambda: principal),
        require_csrf=lambda: None,
    ))
    return TestClient(app)


def test_mapping_draft_create_update_validate_publish_routes():
    client = _client()
    created = client.post("/api/system/mapping-drafts", json={"mapping_id": "mapping-a", "target_version": "v2", "base_version": "v1"})
    assert created.status_code == 200
    draft_id = created.json()["draft_id"]
    updated = client.put(f"/api/system/mapping-drafts/{draft_id}", json={"expected_revision": 1, "payload": {"mapping_id": "mapping-a"}})
    assert updated.json()["revision"] == 2
    assert client.post(f"/api/system/mapping-drafts/{draft_id}/validate").json()["status"] == "validated"
    published = client.post(f"/api/system/mapping-drafts/{draft_id}/publish", json={"expected_revision": 2})
    assert published.json()["draft"]["status"] == "published"

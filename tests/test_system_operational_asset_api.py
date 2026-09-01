from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.infra.db.migrations import migrate
from app.infra.db.operational_asset_repository import OperationalAssetRepository
from app.system_operations.system_operation_router import build_system_operation_router
from app.system_operations.system_operation_service import SystemOperationService

import json


def _snapshot() -> dict:
    root = Path(__file__).resolve().parents[1]
    path = root / "contracts/examples/generator-operational-assets/inventory-v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _client(tmp_path: Path) -> tuple[TestClient, SystemOperationService]:
    database = tmp_path / "registry.db"
    migrate(str(database))
    service = SystemOperationService(OperationalAssetRepository(database))
    service.reconcile(_snapshot())
    app = FastAPI()

    def require_permission(_: str):
        def allowed():
            return {"permission": "system.assets.read"}
        return allowed

    app.include_router(build_system_operation_router(get_service=lambda: service, require_permission=require_permission))
    return TestClient(app), service


def test_asset_list_exposes_representative_version(tmp_path: Path):
    client, _ = _client(tmp_path)
    response = client.get("/api/system/assets", params={"asset_type": "static_mapping", "active": "true"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["current_version"] == "v1"
    assert payload["items"][0]["validation_status"] == "valid"
    assert payload["items"][0]["active"] is True


def test_asset_detail_versions_and_latest_reconciliation(tmp_path: Path):
    client, service = _client(tmp_path)
    asset_id = service.list_assets()["items"][0]["id"]
    assert client.get(f"/api/system/assets/{asset_id}").json()["versions"][0]["version"] == "v1"
    assert client.get(f"/api/system/assets/{asset_id}/versions").json()["items"][0]["version"] == "v1"
    assert client.get("/api/system/assets/reconciliation/latest").json()["status"] == "succeeded"


def test_asset_list_rejects_unknown_status(tmp_path: Path):
    client, _ = _client(tmp_path)
    response = client.get("/api/system/assets", params={"registry_status": "invented"})
    assert response.status_code == 422

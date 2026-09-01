import json
from pathlib import Path

from app.infra.db.migrations import migrate
from app.infra.db.operational_asset_repository import OperationalAssetRepository
from app.system_operations.system_operation_service import SystemOperationService


def _snapshot() -> dict:
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "contracts/examples/generator-operational-assets/inventory-v1.json").read_text(encoding="utf-8"))


def test_reconciliation_is_idempotent(tmp_path: Path):
    database = tmp_path / "registry.db"
    migrate(str(database))
    service = SystemOperationService(OperationalAssetRepository(database))
    first = service.reconcile(_snapshot())
    second = service.reconcile(_snapshot())
    assert first["id"] == second["id"]
    assert len(service.list_assets()["items"]) == 1


def test_reconciliation_marks_checksum_change_as_drift(tmp_path: Path):
    database = tmp_path / "registry.db"
    migrate(str(database))
    service = SystemOperationService(OperationalAssetRepository(database))
    snapshot = _snapshot()
    service.reconcile(snapshot)
    snapshot["generated_at"] = "2026-09-01T01:00:00Z"
    snapshot["assets"][0]["sha256"] = "2" * 64
    service.reconcile(snapshot)
    asset = service.list_assets()["items"][0]
    versions = service.get_asset(asset["id"])["versions"]
    assert versions[0]["registry_status"] == "drifted"


def test_missing_asset_becomes_unavailable_without_deletion(tmp_path: Path):
    database = tmp_path / "registry.db"
    migrate(str(database))
    service = SystemOperationService(OperationalAssetRepository(database))
    snapshot = _snapshot()
    service.reconcile(snapshot)
    snapshot["generated_at"] = "2026-09-01T02:00:00Z"
    snapshot["assets"] = []
    service.reconcile(snapshot)
    asset = service.list_assets()["items"][0]
    versions = service.get_asset(asset["id"])["versions"]
    assert versions[0]["registry_status"] == "unavailable"


def test_list_assets_includes_representative_version_and_filters(tmp_path: Path):
    database = tmp_path / "registry.db"
    migrate(str(database))
    service = SystemOperationService(OperationalAssetRepository(database))
    service.reconcile(_snapshot())
    result = service.list_assets(asset_type="static_mapping", validation_status="valid", active=True)
    assert result["total"] == 1
    assert result["items"][0]["current_version"] == "v1"
    assert result["items"][0]["registry_status"] == "verified"
    assert result["items"][0]["validation_status"] == "valid"
    assert result["items"][0]["active"] is True


def test_latest_reconciliation_is_available(tmp_path: Path):
    database = tmp_path / "registry.db"
    migrate(str(database))
    service = SystemOperationService(OperationalAssetRepository(database))
    expected = service.reconcile(_snapshot())
    assert service.latest_reconciliation()["snapshot_sha256"] == expected["snapshot_sha256"]

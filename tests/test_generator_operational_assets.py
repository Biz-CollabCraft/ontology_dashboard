import json
from pathlib import Path

from fastapi.testclient import TestClient

from systems.generator.app.main import create_app
from systems.generator.app.operational_assets.operational_asset_service import OperationalAssetInventoryService
from systems.generator.generator_config import PATHS


def test_inventory_endpoint_is_fail_closed_without_token(monkeypatch):
    monkeypatch.delenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", raising=False)
    response = TestClient(create_app()).get("/internal/operational-assets")
    assert response.status_code == 503


def test_inventory_endpoint_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("SYSTEM_OPERATIONS_SERVICE_TOKEN", "expected-secret")
    response = TestClient(create_app()).get(
        "/internal/operational-assets",
        headers={"X-System-Operations-Token": "wrong-secret"},
    )
    assert response.status_code == 401


def test_mapping_inventory_uses_logical_uri_and_checksum(monkeypatch, tmp_path: Path):
    ontology = tmp_path / "ontology"
    mapping_root = ontology / "mappings"
    mapping_root.mkdir(parents=True)
    mapping = mapping_root / "mapping.json"
    example_path = (
        Path(__file__).resolve().parents[1]
        / "contracts"
        / "examples"
        / "generator-protocol-extraction"
        / "static-mapping-table.json"
    )
    mapping_payload = json.loads(example_path.read_text(encoding="utf-8"))
    mapping_payload["mapping_id"] = "mapping-a"
    mapping_payload["mapping_version"] = "v1"
    mapping.write_text(json.dumps(mapping_payload), encoding="utf-8")
    monkeypatch.setattr(PATHS, "ontology", ontology)
    monkeypatch.setattr(PATHS, "mapping_root", mapping_root)
    monkeypatch.setattr(PATHS, "models_store", tmp_path / "models_store")
    monkeypatch.setattr(PATHS, "data_dir", tmp_path / "data")
    monkeypatch.setattr(PATHS, "data_preprocessed", tmp_path / "data_preprocessed")
    monkeypatch.setattr(PATHS, "extraction_mapping_id", "mapping-a")
    monkeypatch.setattr(PATHS, "extraction_mapping_version", "v1")
    inventory = OperationalAssetInventoryService().build_inventory()
    mapping_items = [item for item in inventory.assets if item.asset_type == "static_mapping"]
    assert len(mapping_items) == 1
    item = mapping_items[0]
    assert item.logical_uri == "ontology/mappings/mapping.json"
    assert len(item.sha256) == 64
    assert item.active is True
    assert item.validation.status == "valid"
    assert str(tmp_path) not in item.logical_uri

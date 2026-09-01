import json
from pathlib import Path

import pytest

from systems.generator.app.operational_assets.mapping_management_service import MappingManagementError, MappingManagementService
from systems.generator.generator_config import PATHS


def _mapping() -> dict:
    root = Path(__file__).resolve().parents[1]
    return json.loads((root / "contracts/examples/generator-protocol-extraction/static-mapping-table.json").read_text(encoding="utf-8"))


def test_mapping_publish_is_immutable_and_idempotent(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(PATHS, "mapping_root", tmp_path / "mappings")
    service = MappingManagementService()
    payload = _mapping()
    normalized, checksum = service.validate("mapping-a", "v2", payload)
    first = service.publish("mapping-a", "v2", normalized, checksum)
    second = service.publish("mapping-a", "v2", normalized, checksum)
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    published = json.loads((tmp_path / "mappings/mapping-a/v2/mapping.json").read_text(encoding="utf-8"))
    assert published["status"] == "approved"
    assert published["mapping_sha256"] == checksum


def test_mapping_publish_rejects_different_content_for_same_version(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(PATHS, "mapping_root", tmp_path / "mappings")
    service = MappingManagementService()
    payload = _mapping()
    normalized, checksum = service.validate("mapping-a", "v2", payload)
    service.publish("mapping-a", "v2", normalized, checksum)
    payload["description"] = "different"
    changed, changed_sha = service.validate("mapping-a", "v2", payload)
    with pytest.raises(MappingManagementError) as error:
        service.publish("mapping-a", "v2", changed, changed_sha)
    assert error.value.code == "MAPPING_PUBLISH_CONFLICT"

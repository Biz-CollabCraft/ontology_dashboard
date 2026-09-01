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


def test_mapping_activation_is_atomic_and_idempotent(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(PATHS, "mapping_root", tmp_path / "mappings")
    monkeypatch.setattr(PATHS, "data_preprocessed", tmp_path / "preprocessed")
    service = MappingManagementService()
    normalized, checksum = service.validate("mapping-a", "v2", _mapping())
    service.publish("mapping-a", "v2", normalized, checksum)
    replay = tmp_path / "preprocessed/extraction_replays" / checksum / "checkpoints"
    replay.mkdir(parents=True)
    (replay / "source-a.json").write_text(json.dumps({"mapping_sha256": checksum}), encoding="utf-8")
    active_checkpoint = tmp_path / "preprocessed/extraction_state/gen_data/checkpoints"
    active_checkpoint.mkdir(parents=True)
    (active_checkpoint / "source-a.json").write_text(json.dumps({"mapping_sha256": "2" * 64}), encoding="utf-8")

    first = service.activate("mapping-a", "v2", checksum, "job-1")
    second = service.activate("mapping-a", "v2", checksum, "job-2")

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["activated_by_job_id"] == "job-1"
    assert service.read_active("mapping-a")["mapping_sha256"] == checksum
    assert json.loads((active_checkpoint / "source-a.json").read_text(encoding="utf-8"))["mapping_sha256"] == checksum
    assert (tmp_path / "preprocessed/extraction_state/gen_data/checkpoint_archive" / ("2" * 64) / "source-a.json").is_file()


def test_mapping_activation_keeps_existing_pointer_on_checksum_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(PATHS, "mapping_root", tmp_path / "mappings")
    monkeypatch.setattr(PATHS, "data_preprocessed", tmp_path / "preprocessed")
    service = MappingManagementService()
    normalized, checksum = service.validate("mapping-a", "v2", _mapping())
    service.publish("mapping-a", "v2", normalized, checksum)
    replay = tmp_path / "preprocessed/extraction_replays" / checksum / "checkpoints"
    replay.mkdir(parents=True)
    (replay / "source-a.json").write_text(json.dumps({"mapping_sha256": checksum}), encoding="utf-8")
    service.activate("mapping-a", "v2", checksum, "job-1")

    with pytest.raises(MappingManagementError) as error:
        service.activate("mapping-a", "v2", "f" * 64, "job-2")

    assert error.value.code == "MAPPING_ACTIVATION_CHECKSUM_MISMATCH"
    assert service.read_active("mapping-a")["activated_by_job_id"] == "job-1"

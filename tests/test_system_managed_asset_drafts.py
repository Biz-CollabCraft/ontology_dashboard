from pathlib import Path

import pytest

from app.infra.db.managed_asset_draft_repository import ManagedAssetDraftRepository
from app.infra.db.migrations import migrate
from app.system_operations.managed_asset_schema import (
    ManagedAssetDraftCreate,
    ManagedAssetDraftPublish,
    ManagedAssetDraftUpdate,
)
from app.system_operations.managed_asset_service import ManagedAssetService
from app.system_operations.system_operation_exception import SystemOperationError


class Generator:
    def __init__(self):
        self.versions = {}

    def read(self, asset_type, asset_id, version):
        return self.versions[(asset_type, asset_id, version)]

    def publish(self, asset_type, asset_id, version, checksum, payload):
        key = (asset_type, asset_id, version)
        if key in self.versions:
            raise RuntimeError("version exists")
        self.versions[key] = payload
        return {"asset_type": asset_type, "asset_id": asset_id, "version": version, "sha256": checksum}


def _service(tmp_path: Path):
    database = tmp_path / "managed-assets.db"
    migrate(str(database))
    generator = Generator()
    return ManagedAssetService(ManagedAssetDraftRepository(database), generator), generator


def test_managed_asset_draft_revision_validation_and_publish(tmp_path: Path):
    service, generator = _service(tmp_path)
    draft = service.create(
        ManagedAssetDraftCreate(asset_type="label_schema", asset_id="pdm-label", target_version="pdm-label-v4"),
        "operator",
    )
    payload = dict(draft["payload"])
    payload["prediction_horizon_hours"] = 48
    updated = service.update(
        draft["draft_id"],
        ManagedAssetDraftUpdate(expected_revision=1, payload=payload, reason="change horizon"),
        "operator",
    )
    validation = service.validate(draft["draft_id"], "operator")
    assert validation["validation_status"] == "valid"
    result = service.publish(
        draft["draft_id"],
        ManagedAssetDraftPublish(expected_revision=updated["revision"], expected_payload_sha256=validation["payload_sha256"], reason="approved"),
        "operator",
    )
    assert result["draft"]["status"] == "published"
    assert generator.versions[("label_schema", "pdm-label", "pdm-label-v4")]["prediction_horizon_hours"] == 48


def test_managed_asset_published_draft_is_immutable(tmp_path: Path):
    service, _ = _service(tmp_path)
    draft = service.create(
        ManagedAssetDraftCreate(asset_type="history_requirement", asset_id="pdm-history", target_version="pdm-history-v2"),
        "operator",
    )
    validation = service.validate(draft["draft_id"], "operator")
    service.publish(
        draft["draft_id"],
        ManagedAssetDraftPublish(expected_revision=1, expected_payload_sha256=validation["payload_sha256"], reason="approved"),
        "operator",
    )
    with pytest.raises(SystemOperationError) as exc:
        service.update(
            draft["draft_id"],
            ManagedAssetDraftUpdate(expected_revision=1, payload=draft["payload"], reason="mutate"),
            "operator",
        )
    assert exc.value.code == "SYSTEM_CONTRACT_DRAFT_IMMUTABLE"


def test_training_config_semantic_validation_is_fail_closed(tmp_path: Path):
    service, _ = _service(tmp_path)
    draft = service.create(
        ManagedAssetDraftCreate(asset_type="training_config", asset_id="pdm-training", target_version="training-config-v2"),
        "operator",
    )
    payload = dict(draft["payload"])
    payload["split_ratio"] = {"train": 0.9, "validation": 0.2, "test": 0.1}
    service.update(draft["draft_id"], ManagedAssetDraftUpdate(expected_revision=1, payload=payload, reason="invalid split"), "operator")
    result = service.validate(draft["draft_id"], "operator")
    assert result["validation_status"] == "invalid"
    assert result["errors"][0]["code"] == "SYSTEM_CONTRACT_SPLIT_INVALID"

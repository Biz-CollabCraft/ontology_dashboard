import hashlib
import json
from pathlib import Path

import pytest

from systems.generator.app.operational_assets.managed_contract_service import (
    ManagedContractError,
    ManagedContractService,
    canonical_bytes,
)
from systems.generator.generator_config import PATHS


def test_managed_contract_publish_is_immutable_and_readable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(PATHS, "models_store", tmp_path / "models_store")
    payload = {
        "feature_schema_id": "pdm-feature",
        "feature_schema_version": "pdm-feature-v3",
        "feature_executor_version": "pdm-feature-executor-v1",
        "features": [],
    }
    checksum = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    service = ManagedContractService()

    result = service.publish("feature_schema", "pdm-feature", "pdm-feature-v3", checksum, payload)

    assert result["sha256"] == checksum
    assert result["logical_uri"] == "models_store/schemas/features/pdm-feature-v3.json"
    assert service.read("feature_schema", "pdm-feature", "pdm-feature-v3") == payload
    with pytest.raises(ManagedContractError) as exc:
        service.publish("feature_schema", "pdm-feature", "pdm-feature-v3", checksum, payload)
    assert exc.value.code == "SYSTEM_CONTRACT_VERSION_EXISTS"


def test_preprocessing_plan_uses_dataset_scoped_canonical_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(PATHS, "models_store", tmp_path / "models_store")
    payload = {
        "preprocessing_plan_id": "pp-managed",
        "preprocessing_plan_version": "pp-v2",
        "dataset_id": "dataset-a",
        "dataset_version": "window-v2",
        "id_column": "asset_id",
        "time_column": "time",
    }
    checksum = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    result = ManagedContractService().publish(
        "preprocessing_plan", "pp-managed", "pp-v2", checksum, payload
    )
    path = tmp_path / "models_store" / "cache" / "preprocessing_plans" / "dataset-a" / "window-v2" / "pp-managed.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert result["logical_uri"].endswith("dataset-a/window-v2/pp-managed.json")


def test_checksum_mismatch_does_not_create_file(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(PATHS, "models_store", tmp_path / "models_store")
    payload = {
        "label_schema_id": "pdm-label",
        "label_schema_version": "pdm-label-v4",
        "prediction_horizon_hours": 24,
    }
    with pytest.raises(ManagedContractError) as exc:
        ManagedContractService().publish("label_schema", "pdm-label", "pdm-label-v4", "1" * 64, payload)
    assert exc.value.code == "SYSTEM_CONTRACT_INTEGRITY_ERROR"
    assert not (tmp_path / "models_store" / "schemas" / "labels" / "pdm-label-v4.json").exists()

"""Comprehensive test suite for Generator Training API (/train, /train/{base_model}, and /models)."""

import json
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

from systems.generator.app.main import app
from systems.generator.app.training.training_schema import TrainingRequest, TrainingResponse
from systems.generator.app.training.training_exception import (
    TrainingError,
    FeatureDatasetNotFoundError,
    ModelNotRegisteredError,
    TrainingAlreadyRunningError,
    ModelArtifactConflictError,
    FeatureDatasetIntegrityError,
    FeatureSchemaMismatchError,
    LabelSchemaMismatchError,
    TrainingSplitMetadataMissingError,
    InsufficientTrainingDataError,
    ModelTrainingFailedError,
    ModelArtifactPublishFailedError,
    ModelArtifactNotFoundError,
    ModelArtifactIntegrityError,
    ActiveModelNotFoundError,
)
from systems.generator.app.training.training_repository import TrainingRepository, ALLOWED_FEATURE_BUNDLE_FILES
from systems.generator.app.training.training_service import (
    TrainingService,
    REGISTERED_MODELS,
    _training_lock,
)
from systems.generator.model.model_registry import validate_model_artifact_directory


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_feature_bundle(tmp_path, monkeypatch):
    """Create a fully valid Feature Bundle and wire PATHS to tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)
    data_preprocessed = tmp_path / "data_preprocessed"
    data_preprocessed.mkdir(parents=True, exist_ok=True)
    features_cache = data_preprocessed / "features"
    features_cache.mkdir(parents=True, exist_ok=True)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)
    monkeypatch.setattr(PATHS, "data_preprocessed", data_preprocessed)

    # 1. Create telemetry CSV
    telemetry_file = data_dir / "telem.csv"
    timestamps = pd.date_range("2026-01-01 00:00:00", periods=20, freq="h")
    records = []
    for m in ["M001", "M002"]:
        for i, ts in enumerate(timestamps):
            records.append({
                "asset_id": m,
                "timestamp": str(ts),
                "voltage": 220.0 + (i % 5) * 2.0,
                "rotation": 1500.0 + (i % 7) * 10.0,
            })
    pd.DataFrame(records).to_csv(telemetry_file, index=False)

    # 2. Create failure events CSV with version in path
    failure_file = data_dir / "failures" / "v1.0.csv"
    failure_file.parent.mkdir(parents=True, exist_ok=True)
    failures = pd.DataFrame([
        {"asset_id": "M001", "observed_at": "2026-01-01 10:00:00", "failure_type": "Overheat"},
        {"asset_id": "M002", "observed_at": "2026-01-01 15:00:00", "failure_type": "Power"},
    ])
    failures.to_csv(failure_file, index=False)

    # 3. Run extraction and feature endpoints to generate genuine feature bundle
    c = TestClient(app)
    ext_res = c.post("/extraction", json={
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "source_uri": "telem.csv",
        "force_reanalyze": True,
    })
    assert ext_res.status_code == 200
    ext_data = ext_res.json()
    p_ver = ext_data["extraction_plan_version"]
    m_ver = ext_data["result"]["mapping_version"]

    feat_res = c.post("/feature", json={
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "failure_dataset_id": "failures",
        "failure_dataset_version": "v1.0",
        "extraction_plan_version": p_ver,
        "mapping_version": m_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert feat_res.status_code == 200
    feat_data = feat_res.json()
    fver = feat_data["outputs"]["feature_dataset_version"]

    return {
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "feature_dataset_version": fver,
        "models_store": models_store,
        "features_cache": features_cache,
    }


def test_train_method_not_allowed(client):
    """GET /train and GET /train/lightgbm return 405 METHOD_NOT_ALLOWED in ErrorEnvelope."""
    res1 = client.get("/train")
    assert res1.status_code == 405
    err1 = res1.json()["error"]
    assert err1["code"] == "METHOD_NOT_ALLOWED"
    assert "request_id" in err1
    assert "error_id" in err1

    res2 = client.put("/train/lightgbm", json={"feature_dataset_version": "feature-dataset-1234567812345678"})
    assert res2.status_code == 405
    err2 = res2.json()["error"]
    assert err2["code"] == "METHOD_NOT_ALLOWED"


def test_train_request_validation_missing_or_bad_format(client):
    """Invalid feature_dataset_version format returns 422 REQUEST_VALIDATION_ERROR."""
    res1 = client.post("/train", json={})
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"

    res2 = client.post("/train", json={"feature_dataset_version": "bad_version_string"})
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_train_feature_dataset_not_found(client, sample_feature_bundle):
    """Non-existent feature_dataset_version returns 404 FEATURE_DATASET_NOT_FOUND."""
    res = client.post("/train", json={
        "feature_dataset_version": "feature-dataset-0000000000000000",
    })
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "FEATURE_DATASET_NOT_FOUND"


def test_train_unregistered_model_returns_404(client, sample_feature_bundle):
    """POST /train/unsupported_algo returns 404 MODEL_NOT_REGISTERED."""
    fver = sample_feature_bundle["feature_dataset_version"]
    res = client.post("/train/deep_neural_net_v9", json={
        "feature_dataset_version": fver,
    })
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "MODEL_NOT_REGISTERED"


def test_train_all_models_success_and_artifact_validation(client, sample_feature_bundle):
    """POST /train trains all registered models and atomically publishes valid Model Artifact packages."""
    fver = sample_feature_bundle["feature_dataset_version"]
    res = client.post("/train", json={"feature_dataset_version": fver})
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "succeeded"
    assert data["feature_dataset_version"] == fver
    assert "request_id" in data
    assert "run_id" in data
    assert len(data["results"]) == len(REGISTERED_MODELS)
    assert len(data["failed_models"]) == 0

    base_models_succeeded = [r["base_model"] for r in data["results"]]
    for expected_model in ("lightgbm", "xgboost", "random_forest"):
        assert expected_model in base_models_succeeded

    models_store = sample_feature_bundle["models_store"]
    for result_item in data["results"]:
        model_id = result_item["model_id"]
        model_ver = result_item["model_version"]
        assert result_item["activation_status"] == "activated"
        assert result_item["active_model_version"] == model_ver

        artifact_path = models_store / "artifacts" / model_id / model_ver
        assert artifact_path.exists()

        # Validate all 6 files exist
        assert (artifact_path / "manifest.json").is_file()
        assert (artifact_path / "model.joblib").is_file()
        assert (artifact_path / "feature_schema.json").is_file()
        assert (artifact_path / "label_schema.json").is_file()
        assert (artifact_path / "history_requirement.json").is_file()
        assert (artifact_path / "metrics.json").is_file()

        # Validate artifact package conformance
        validate_model_artifact_directory(artifact_path)

        with open(artifact_path / "manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)
            assert manifest["artifact_type"] == "predictive_maintenance_model"
            assert manifest["artifact_schema_version"] == "model-artifact-v1.0"
            assert manifest["model_id"] == model_id
            assert manifest["model_version"] == model_ver
            assert len(manifest["artifact_files"]) >= 5


def test_train_activation_policy_manual(client, sample_feature_bundle):
    """POST /train with activation_policy='manual' publishes artifacts without updating latest.json pointer."""
    fver = sample_feature_bundle["feature_dataset_version"]
    models_store = sample_feature_bundle["models_store"]

    res = client.post("/train/lightgbm", json={
        "feature_dataset_version": fver,
        "activation_policy": "manual",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "succeeded"
    result_item = data["results"][0]
    assert result_item["activation_status"] == "published_only"
    assert result_item["active_model_version"] is None

    # latest.json pointer must NOT exist
    pointer_file = models_store / "artifacts" / "lightgbm" / "latest.json"
    assert not pointer_file.exists()


def test_train_activation_policy_invalid_returns_422(client, sample_feature_bundle):
    """POST /train with invalid activation_policy returns 422 REQUEST_VALIDATION_ERROR."""
    fver = sample_feature_bundle["feature_dataset_version"]
    res = client.post("/train", json={
        "feature_dataset_version": fver,
        "activation_policy": "invalid_policy",
    })
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_train_provenance_propagation(client, sample_feature_bundle):
    """Model Artifact manifest provenance contains source_dataset and failure_dataset from feature metadata."""
    fver = sample_feature_bundle["feature_dataset_version"]
    res = client.post("/train/xgboost", json={"feature_dataset_version": fver})
    assert res.status_code == 200
    result_item = res.json()["results"][0]

    models_store = sample_feature_bundle["models_store"]
    manifest_path = models_store / "artifacts" / "xgboost" / result_item["model_version"] / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    training_provenance = manifest["provenance"]["training"]
    assert "source_dataset" in training_provenance
    assert "failure_dataset" in training_provenance
    assert training_provenance["source_dataset"]["dataset_id"] == "telem"
    assert training_provenance["failure_dataset"]["dataset_id"] == "failures"
    assert "sha256" in training_provenance["source_dataset"]
    assert "sha256" in training_provenance["failure_dataset"]


def test_models_manual_activation_and_active_query_api(client, sample_feature_bundle):
    """Test POST /models/{base_model}/activate/{model_version} and GET /models/{base_model}/active."""
    fver = sample_feature_bundle["feature_dataset_version"]

    # 1. Train model with manual activation policy (v1 published, no pointer)
    res_train1 = client.post("/train/lightgbm", json={
        "feature_dataset_version": fver,
        "activation_policy": "manual",
    })
    assert res_train1.status_code == 200
    v1 = res_train1.json()["results"][0]["model_version"]

    # 2. Query active model before activation -> 404 ACTIVE_MODEL_NOT_FOUND
    res_active0 = client.get("/models/lightgbm/active")
    assert res_active0.status_code == 404
    assert res_active0.json()["error"]["code"] == "ACTIVE_MODEL_NOT_FOUND"

    # 3. Manually activate v1 -> 200 OK
    res_act1 = client.post(f"/models/lightgbm/activate/{v1}")
    assert res_act1.status_code == 200
    act_data1 = res_act1.json()
    assert act_data1["base_model"] == "lightgbm"
    assert act_data1["previous_model_version"] is None
    assert act_data1["active_model_version"] == v1
    assert act_data1["status"] == "activated"

    # 4. Query active model -> returns v1
    res_active1 = client.get("/models/lightgbm/active")
    assert res_active1.status_code == 200
    assert res_active1.json()["active_model_version"] == v1

    # 5. Train second version v2 with manual policy
    res_train2 = client.post("/train/lightgbm", json={
        "feature_dataset_version": fver,
        "activation_policy": "manual",
    })
    assert res_train2.status_code == 200
    v2 = res_train2.json()["results"][0]["model_version"]
    assert v1 != v2

    # 6. Activate v2 -> previous is v1, active is v2
    res_act2 = client.post(f"/models/lightgbm/activate/{v2}")
    assert res_act2.status_code == 200
    assert res_act2.json()["previous_model_version"] == v1
    assert res_act2.json()["active_model_version"] == v2

    # 7. Rollback to v1
    res_rollback = client.post(f"/models/lightgbm/activate/{v1}")
    assert res_rollback.status_code == 200
    assert res_rollback.json()["previous_model_version"] == v2
    assert res_rollback.json()["active_model_version"] == v1

    # 8. Activating non-existent version -> 404 MODEL_ARTIFACT_NOT_FOUND
    res_act_missing = client.post("/models/lightgbm/activate/v999")
    assert res_act_missing.status_code == 404
    assert res_act_missing.json()["error"]["code"] == "MODEL_ARTIFACT_NOT_FOUND"

    # 9. Activating corrupted artifact -> 422 MODEL_ARTIFACT_INTEGRITY_ERROR
    models_store = sample_feature_bundle["models_store"]
    manifest_file = models_store / "artifacts" / "lightgbm" / v1 / "manifest.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    manifest_data["model_id"] = "corrupted_model_id"
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f)

    res_act_corrupt = client.post(f"/models/lightgbm/activate/{v1}")
    assert res_act_corrupt.status_code == 422
    assert res_act_corrupt.json()["error"]["code"] == "MODEL_ARTIFACT_INTEGRITY_ERROR"


def test_train_single_model_success(client, sample_feature_bundle):
    """POST /train/{base_model} trains only the specified model."""
    fver = sample_feature_bundle["feature_dataset_version"]
    res = client.post("/train/lightgbm", json={"feature_dataset_version": fver})
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "succeeded"
    assert len(data["results"]) == 1
    assert data["results"][0]["base_model"] == "lightgbm"
    assert len(data["failed_models"]) == 0


def test_train_partial_success_isolates_model_failure(client, sample_feature_bundle, monkeypatch):
    """In POST /train, one model failure does not stop other models and returns partially_succeeded."""
    fver = sample_feature_bundle["feature_dataset_version"]

    from systems.generator.model.lightgbm import LightGBMModel
    def mock_train_fail(self, *args, **kwargs):
        raise RuntimeError("Simulated lightgbm algorithm failure")

    monkeypatch.setattr(LightGBMModel, "train", mock_train_fail)

    res = client.post("/train", json={"feature_dataset_version": fver})
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "partially_succeeded"
    succeeded_names = [r["base_model"] for r in data["results"]]
    assert "lightgbm" not in succeeded_names
    assert "xgboost" in succeeded_names
    assert "random_forest" in succeeded_names

    assert len(data["failed_models"]) == 1
    failed_item = data["failed_models"][0]
    assert failed_item["base_model"] == "lightgbm"
    assert failed_item["code"] == "MODEL_TRAINING_FAILED"
    assert failed_item["error_id"].startswith("err-")


def test_train_single_model_failure_returns_500(client, sample_feature_bundle, monkeypatch):
    """In POST /train/{base_model}, single model failure returns 500 MODEL_TRAINING_FAILED."""
    fver = sample_feature_bundle["feature_dataset_version"]

    from systems.generator.model.lightgbm import LightGBMModel
    def mock_train_fail(self, *args, **kwargs):
        raise RuntimeError("Simulated lightgbm algorithm failure")

    monkeypatch.setattr(LightGBMModel, "train", mock_train_fail)

    res = client.post("/train/lightgbm", json={"feature_dataset_version": fver})
    assert res.status_code == 500
    err = res.json()["error"]
    assert err["code"] == "MODEL_TRAINING_FAILED"
    assert "error_id" in err


def test_train_concurrency_lock_returns_409(client, sample_feature_bundle):
    """Concurrent training request while lock is held returns 409 TRAINING_ALREADY_RUNNING."""
    fver = sample_feature_bundle["feature_dataset_version"]

    # Acquire lock manually to simulate concurrent training in progress
    acquired = _training_lock.acquire(blocking=False)
    assert acquired is True

    try:
        res = client.post("/train", json={"feature_dataset_version": fver})
        assert res.status_code == 409
        err = res.json()["error"]
        assert err["code"] == "TRAINING_ALREADY_RUNNING"
    finally:
        _training_lock.release()

    # After lock is released, next request succeeds
    res_after = client.post("/train/random_forest", json={"feature_dataset_version": fver})
    assert res_after.status_code == 200


def test_train_feature_bundle_integrity_violations(tmp_path, monkeypatch):
    """Training repository strictly rejects corrupted Feature Bundles with FEATURE_DATASET_INTEGRITY_ERROR."""
    import hashlib
    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    cache_dir = tmp_path / "features_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    repo = TrainingRepository(features_base_dir=cache_dir)
    bundle_dir = cache_dir / "ds1-v1-feature-dataset-7739990fb1d3be02"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    contract = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "failure_dataset_id": "f1",
        "failure_dataset_version": "v1",
        "extraction_plan_version": "extraction-plan-1111222233334444",
        "mapping_version": "ontology-mapping-1111222233334444",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
    }
    cols = ["col1", "col2"]
    X = np.ones((6, 2), dtype=np.float64)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.int64)

    np.save(bundle_dir / "features.npy", X)
    np.save(bundle_dir / "labels.npy", y)
    with open(bundle_dir / "feature_columns.json", "w", encoding="utf-8") as f:
        json.dump(cols, f)

    row_metadata = {
        "asset_ids": ["M1", "M1", "M1", "M1", "M1", "M1"],
        "timestamps": ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 02:00:00", "2026-01-01 03:00:00", "2026-01-01 04:00:00", "2026-01-01 05:00:00"],
    }
    with open(bundle_dir / "row_metadata.json", "w", encoding="utf-8") as f:
        json.dump(row_metadata, f)

    checksum = {
        "algorithm": "sha256",
        "files": {
            "features.npy": sha(bundle_dir / "features.npy"),
            "labels.npy": sha(bundle_dir / "labels.npy"),
            "feature_columns.json": sha(bundle_dir / "feature_columns.json"),
            "row_metadata.json": sha(bundle_dir / "row_metadata.json"),
        },
    }

    meta = {
        "contract": contract,
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "feature_dataset_version": "feature-dataset-7739990fb1d3be02",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "feature_columns": cols,
        "row_count": 6,
        "feature_count": 2,
        "checksum": checksum,
        "split_indices": {"train": [0, 1, 2, 3], "val": [4], "test": [5]},
    }
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)

    # 1. Normal load succeeds
    loaded_X, loaded_y, loaded_cols, loaded_meta, _ = repo.load_feature_bundle("feature-dataset-7739990fb1d3be02")
    assert loaded_X.shape == (6, 2)

    # 2. Corrupt features.npy with modified bytes (checksum mismatch)
    X_mod = np.copy(X)
    X_mod[0, 0] = 999.0
    np.save(bundle_dir / "features.npy", X_mod)
    with pytest.raises(FeatureDatasetIntegrityError, match="체크섬이 일치하지 않습니다"):
        repo.load_feature_bundle("feature-dataset-7739990fb1d3be02")
    np.save(bundle_dir / "features.npy", X)

    # 3. Missing checksum in metadata
    meta_no_cs = meta.copy()
    meta_no_cs.pop("checksum")
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_no_cs, f)
    with pytest.raises(FeatureDatasetIntegrityError, match="필수 필드가 누락되었습니다"):
        repo.load_feature_bundle("feature-dataset-7739990fb1d3be02")
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)

    # 4. Missing mandatory field (feature_schema_version)
    meta_no_ver = meta.copy()
    meta_no_ver.pop("feature_schema_version")
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_no_ver, f)
    with pytest.raises(FeatureDatasetIntegrityError, match="필수 필드가 누락되었습니다"):
        repo.load_feature_bundle("feature-dataset-7739990fb1d3be02")
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f)


def test_train_split_metadata_missing_raises_error(tmp_path, sample_feature_bundle, monkeypatch):
    """Missing chronological split metadata in feature bundle raises TRAINING_SPLIT_METADATA_MISSING."""
    import hashlib
    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    fver = sample_feature_bundle["feature_dataset_version"]
    repo = TrainingRepository()
    bundle_dir = repo.find_feature_bundle_dir(fver)
    meta_file = bundle_dir / "feature_metadata.json"

    # Remove split_indices from metadata
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta.pop("split_indices", None)

    row_meta_file = bundle_dir / "row_metadata.json"
    if row_meta_file.exists():
        row_meta_file.unlink()
    if "row_metadata.json" in meta.get("checksum", {}).get("files", {}):
        meta["checksum"]["files"].pop("row_metadata.json")

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    c = TestClient(app)
    res = c.post("/train/random_forest", json={"feature_dataset_version": fver})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "TRAINING_SPLIT_METADATA_MISSING" or err["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"


def test_split_indices_validation_rules():
    """Test strict split indices validation rules: disjoint, complete, in-bounds, and chronological."""
    from systems.generator.app.training.training_service import validate_split_indices

    # 1. Valid split
    validate_split_indices(
        split_indices={"train": [0, 1, 2], "val": [3], "test": [4]},
        total_rows=5,
        asset_ids=["M1", "M1", "M1", "M1", "M1"],
        timestamps=["2026-01-01 01:00:00", "2026-01-01 02:00:00", "2026-01-01 03:00:00", "2026-01-01 04:00:00", "2026-01-01 05:00:00"],
    )

    # 2. Overlapping split
    with pytest.raises(TrainingSplitMetadataMissingError, match="overlap"):
        validate_split_indices(
            split_indices={"train": [0, 1, 2], "val": [2, 3], "test": [4]},
            total_rows=5,
        )

    # 3. Duplicate within split
    with pytest.raises(TrainingSplitMetadataMissingError, match="duplicate"):
        validate_split_indices(
            split_indices={"train": [0, 1, 1], "val": [2, 3], "test": [4]},
            total_rows=5,
        )

    # 4. Incomplete union (missing row 4)
    with pytest.raises(TrainingSplitMetadataMissingError, match="cover all rows"):
        validate_split_indices(
            split_indices={"train": [0, 1], "val": [2], "test": [3]},
            total_rows=5,
        )

    # 5. Out of bounds index
    with pytest.raises(TrainingSplitMetadataMissingError, match="out of bounds"):
        validate_split_indices(
            split_indices={"train": [0, 1, 2], "val": [3], "test": [10]},
            total_rows=5,
        )

    # 6. Chronological violation (train time > val time for same asset)
    with pytest.raises(TrainingSplitMetadataMissingError, match="train timestamp"):
        validate_split_indices(
            split_indices={"train": [2], "val": [0], "test": [1]},
            total_rows=3,
            asset_ids=["M1", "M1", "M1"],
            timestamps=["2026-01-01 01:00:00", "2026-01-01 05:00:00", "2026-01-01 10:00:00"],
        )


def test_feature_schema_exact_order_check(client, sample_feature_bundle, monkeypatch):
    """If feature columns are in different order than declared in Feature Schema, reject with FEATURE_SCHEMA_MISMATCH."""
    fver = sample_feature_bundle["feature_dataset_version"]
    repo = TrainingRepository()
    bundle_dir = repo.find_feature_bundle_dir(fver)
    cols_file = bundle_dir / "feature_columns.json"
    meta_file = bundle_dir / "feature_metadata.json"

    with open(cols_file, "r", encoding="utf-8") as f:
        cols = json.load(f)
    # Reverse column order
    reversed_cols = list(reversed(cols))
    with open(cols_file, "w", encoding="utf-8") as f:
        json.dump(reversed_cols, f)

    # Update metadata and checksum
    import hashlib
    def sha(p):
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            while chunk := fh.read(65536):
                h.update(chunk)
        return h.hexdigest()

    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["feature_columns"] = reversed_cols
    meta["checksum"]["files"]["feature_columns.json"] = sha(cols_file)
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    res = client.post("/train/random_forest", json={"feature_dataset_version": fver})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "FEATURE_SCHEMA_MISMATCH"


def test_latest_pointer_and_registry_updated_on_success(client, sample_feature_bundle):
    """When a model is trained successfully, its latest.json pointer is atomically updated."""
    fver = sample_feature_bundle["feature_dataset_version"]
    res = client.post("/train/random_forest", json={"feature_dataset_version": fver})
    assert res.status_code == 200
    data = res.json()
    model_version = data["results"][0]["model_version"]

    models_store = sample_feature_bundle["models_store"]
    latest_file = models_store / "artifacts" / "random_forest" / "latest.json"
    assert latest_file.is_file()

    with open(latest_file, "r", encoding="utf-8") as f:
        pointer = json.load(f)
    assert pointer["model_id"] == "random_forest"
    assert pointer["latest_version"] == model_version
    assert "artifact_uri" in pointer
    assert "updated_at" in pointer


def test_canonical_and_legacy_lock_sharing(sample_feature_bundle):
    """Holding _training_lock prevents both canonical /train and legacy /internal/train."""
    from systems.generator.generator_main import app as legacy_app
    from fastapi.testclient import TestClient

    fver = sample_feature_bundle["feature_dataset_version"]
    c_canonical = TestClient(app)
    c_legacy = TestClient(legacy_app)

    acquired = _training_lock.acquire(blocking=False)
    assert acquired is True

    try:
        # Canonical returns 409
        res_canon = c_canonical.post("/train", json={"feature_dataset_version": fver})
        assert res_canon.status_code == 409
        assert res_canon.json()["error"]["code"] == "TRAINING_ALREADY_RUNNING"

        # Legacy returns 409
        res_leg = c_legacy.post("/internal/train", json={})
        assert res_leg.status_code == 409
        assert "이미 진행 중" in res_leg.json()["detail"]
    finally:
        _training_lock.release()


def test_history_requirement_calculation():
    """Test dynamic history requirement inference from telemetry and feature names."""
    from systems.generator.model.model_training import infer_history_requirement

    df = pd.DataFrame({
        "asset_id": ["A", "A", "A", "A", "B", "B", "B", "B"],
        "timestamp": [
            "2026-01-01 00:00:00",
            "2026-01-01 01:00:00",
            "2026-01-01 02:00:00",
            "2026-01-01 03:00:00",
            "2026-01-01 00:00:00",
            "2026-01-01 01:00:00",
            "2026-01-01 02:00:00",
            "2026-01-01 03:00:00",
        ],
    })
    req = infer_history_requirement(
        df,
        id_col="asset_id",
        time_col="timestamp",
        feature_names=[
            "voltage__Voltage__rolling_mean__window_5",
            "rotation__Rotation__ema__span_10",
        ],
    )
    assert req["expected_sampling_interval_seconds"] == 3600
    assert req["minimum_history_rows"] == 10
    assert req["maximum_lookback_hours"] == 9

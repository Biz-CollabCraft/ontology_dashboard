"""Comprehensive test suite for Generator Training API (/train and /train/{base_model})."""

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
)
from systems.generator.app.training.training_repository import TrainingRepository
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

    # 2. Create failure events CSV
    failure_file = data_dir / "failures.csv"
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
    repo = TrainingRepository(features_base_dir=tmp_path / "features_cache")
    bundle_dir = tmp_path / "features_cache" / "ds1" / "v1" / "feature-dataset-7739990fb1d3be02"
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
    meta = {
        "contract": contract,
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "feature_dataset_version": "feature-dataset-7739990fb1d3be02",
        "feature_columns": cols,
        "row_count": 6,
        "feature_count": 2,
        "split_indices": {"train": [0, 1, 2, 3], "val": [4], "test": [5]},
    }
    X = np.ones((6, 2), dtype=np.float64)
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.int64)

    np.save(bundle_dir / "features.npy", X)
    np.save(bundle_dir / "labels.npy", y)
    with open(bundle_dir / "feature_columns.json", "w") as f:
        json.dump(cols, f)
    with open(bundle_dir / "feature_metadata.json", "w") as f:
        json.dump(meta, f)

    # 1. Normal load succeeds
    loaded_X, loaded_y, loaded_cols, loaded_meta, _ = repo.load_feature_bundle("feature-dataset-7739990fb1d3be02")
    assert loaded_X.shape == (6, 2)

    # 2. Corrupt features.npy with NaN
    X_nan = np.copy(X)
    X_nan[0, 0] = np.nan
    np.save(bundle_dir / "features.npy", X_nan)
    with pytest.raises(FeatureDatasetIntegrityError, match="NaN 또는 무한대"):
        repo.load_feature_bundle("feature-dataset-7739990fb1d3be02")
    np.save(bundle_dir / "features.npy", X)

    # 3. Single-class label (only 0s)
    np.save(bundle_dir / "labels.npy", np.zeros(6, dtype=np.int64))
    with pytest.raises(InsufficientTrainingDataError, match="Positive 및 Negative"):
        repo.load_feature_bundle("feature-dataset-7739990fb1d3be02")
    np.save(bundle_dir / "labels.npy", y)


def test_train_split_metadata_missing_raises_error(tmp_path, sample_feature_bundle, monkeypatch):
    """Missing chronological split metadata in feature bundle raises TRAINING_SPLIT_METADATA_MISSING."""
    fver = sample_feature_bundle["feature_dataset_version"]
    repo = TrainingRepository()
    bundle_dir = repo.find_feature_bundle_dir(fver)
    meta_file = bundle_dir / "feature_metadata.json"

    # Remove split_indices from metadata and remove row_metadata.json if present
    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta.pop("split_indices", None)
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(meta, f)

    row_meta_file = bundle_dir / "row_metadata.json"
    if row_meta_file.exists():
        row_meta_file.unlink()

    c = TestClient(app)
    res = c.post("/train/random_forest", json={"feature_dataset_version": fver})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "TRAINING_SPLIT_METADATA_MISSING"

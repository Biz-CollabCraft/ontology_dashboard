"""Tests for Generator domain Feature API (/feature)."""

import json
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from fastapi.testclient import TestClient

from systems.generator.app.main import app
from systems.generator.app.extraction.extraction_repository import ExtractionRepository
from systems.generator.app.feature.feature_schema import FeatureRequest, FeatureResponse
from systems.generator.app.feature.feature_exception import (
    FeatureError,
    ExtractionPlanNotReadyError,
    ExtractionPlanVersionMismatchError,
    NpyValidationError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_dataset(tmp_path, monkeypatch):
    """Create a sample dataset and wire PATHS to use tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    # 1. Create telemetry CSV
    telemetry_file = data_dir / "telemetry_sample.csv"
    # Create 2 machines, 10 timestamps each
    timestamps = pd.date_range("2026-01-01 00:00:00", periods=10, freq="h")
    records = []
    for m in ["M001", "M002"]:
        for i, ts in enumerate(timestamps):
            records.append({
                "asset_id": m,
                "timestamp": str(ts),
                "temperature": 50.0 + i * 2.0,
                "vibration": 0.1 + (i % 3) * 0.05,
                "voltage": 220.0 + i * 1.5,
            })
    pd.DataFrame(records).to_csv(telemetry_file, index=False)

    # 2. Patch Generator PATHS
    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    return {
        "dataset_id": "telemetry_sample",
        "dataset_version": "v1.0",
        "csv_path": str(telemetry_file),
        "data_dir": data_dir,
        "models_store": models_store,
    }


def test_feature_method_not_allowed(client):
    """GET /feature returns 405 METHOD_NOT_ALLOWED."""
    res = client.get("/feature")
    assert res.status_code == 405
    err = res.json()["error"]
    assert err["code"] == "METHOD_NOT_ALLOWED"
    assert "request_id" in err


def test_feature_extraction_plan_not_ready(client):
    """POST /feature without an existing Extraction Plan returns 404 EXTRACTION_PLAN_NOT_READY."""
    payload = {
        "dataset_id": "unextracted_dataset",
        "dataset_version": "v1.0",
        "extraction_plan_version": "extraction-plan-unextracted_dataset-v1.0",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res = client.post("/feature", json=payload)
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "EXTRACTION_PLAN_NOT_READY"
    assert "먼저 POST /extraction을 실행해 주세요" in err["message"]


def test_feature_extraction_plan_version_mismatch(client, sample_dataset):
    """POST /feature with mismatched extraction_plan_version returns 422 EXTRACTION_PLAN_VERSION_MISMATCH."""
    # First publish extraction plan
    ext_repo = ExtractionRepository()
    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "temperature", "vibration", "voltage"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
    }
    ext_repo.publish_plan(sample_dataset["dataset_id"], sample_dataset["dataset_version"], plan_data, overwrite=True)

    payload = {
        "dataset_id": sample_dataset["dataset_id"],
        "dataset_version": sample_dataset["dataset_version"],
        "extraction_plan_version": "extraction-plan-wrong-version-xyz",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res = client.post("/feature", json=payload)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "EXTRACTION_PLAN_VERSION_MISMATCH"


def test_feature_request_validation_errors(client):
    """Validation errors for horizon <= 0 and rebuild_npy=False return 422 REQUEST_VALIDATION_ERROR."""
    # horizon <= 0
    payload_bad_horizon = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "extraction_plan_version": "extraction-plan-ds1-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 0,
        "rebuild_npy": True,
    }
    res1 = client.post("/feature", json=payload_bad_horizon)
    assert res1.status_code == 422
    err1 = res1.json()["error"]
    assert err1["code"] == "REQUEST_VALIDATION_ERROR"

    # rebuild_npy = False
    payload_bad_rebuild = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "extraction_plan_version": "extraction-plan-ds1-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": False,
    }
    res2 = client.post("/feature", json=payload_bad_rebuild)
    assert res2.status_code == 422
    err2 = res2.json()["error"]
    assert err2["code"] == "REQUEST_VALIDATION_ERROR"


def test_feature_end_to_end_success(client, sample_dataset):
    """POST /extraction -> POST /feature succeeds end-to-end with atomic NPY artifacts."""
    dataset_id = sample_dataset["dataset_id"]
    dataset_version = sample_dataset["dataset_version"]

    # 1. Execute Extraction
    ext_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset["csv_path"],
        "force_reanalyze": True,
    }
    ext_res = client.post("/extraction", json=ext_payload)
    assert ext_res.status_code == 200
    ext_data = ext_res.json()
    plan_ver = ext_data["extraction_plan_version"]

    # 2. Execute Feature generation
    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": plan_ver,
        "feature_schema_version": "pdm-feature-v2",
        "label_schema_version": "pdm-label-v3",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
        "force": True,
    }
    feat_res = client.post("/feature", json=feat_payload)
    assert feat_res.status_code == 200
    feat_data = feat_res.json()

    assert feat_data["status"] == "succeeded"
    assert feat_data["dataset_id"] == dataset_id
    assert feat_data["dataset_version"] == dataset_version
    assert "outputs" in feat_data

    outputs = feat_data["outputs"]
    assert outputs["row_count"] > 0
    assert outputs["feature_count"] > 0
    assert "features_uri" in outputs
    assert "labels_uri" in outputs
    assert "metadata_uri" in outputs

    # Verify physical artifacts
    from systems.generator.generator_config import PATHS
    repo_root = PATHS.models_store.parent
    features_path = repo_root / outputs["features_uri"]
    labels_path = repo_root / outputs["labels_uri"]
    meta_path = repo_root / outputs["metadata_uri"]

    assert features_path.exists()
    assert labels_path.exists()
    assert meta_path.exists()

    X = np.load(features_path)
    y = np.load(labels_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    assert X.shape[0] == y.shape[0] == outputs["row_count"]
    assert X.shape[1] == outputs["feature_count"]
    assert len(meta["feature_columns"]) == outputs["feature_count"]

    # Ensure metadata columns (asset_id, timestamp, label) are NOT in features matrix
    for col in meta["feature_columns"]:
        assert col not in ("asset_id", "timestamp", "datetime", "label")


def test_feature_force_false_reuses_existing_outputs(client, sample_dataset):
    """POST /feature with force=False reuses previously published feature bundle."""
    dataset_id = sample_dataset["dataset_id"]
    dataset_version = sample_dataset["dataset_version"]

    # First run extraction
    client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset["csv_path"],
        "force_reanalyze": True,
    })

    plan_ver = f"extraction-plan-{dataset_id}-{dataset_version}"
    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": plan_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
        "force": False,
    }

    # Run 1
    res1 = client.post("/feature", json=feat_payload)
    assert res1.status_code == 200
    data1 = res1.json()

    # Run 2 with force=False
    res2 = client.post("/feature", json=feat_payload)
    assert res2.status_code == 200
    data2 = res2.json()

    assert data1["outputs"]["feature_dataset_version"] == data2["outputs"]["feature_dataset_version"]
    assert data1["outputs"]["row_count"] == data2["outputs"]["row_count"]


def test_repository_atomic_publish_and_validation(tmp_path):
    """FeatureRepository validates arrays and cleans up staging on error."""
    repo = FeatureRepository(base_dir=tmp_path / "features_cache")

    # 1. Successful publish
    X = np.ones((10, 5), dtype=np.float64)
    y = np.zeros(10, dtype=np.int64)
    cols = [f"f_{i}" for i in range(5)]
    meta = {"test": 123}

    uris = repo.publish_feature_bundle("ds1", "v1", "fver1", X, y, cols, meta)
    assert (tmp_path / "features_cache" / "ds1-v1-fver1" / "features.npy").exists()

    # 2. Row count mismatch fails validation
    y_bad = np.zeros(8, dtype=np.int64)
    with pytest.raises(NpyValidationError, match="does not match y count"):
        repo.publish_feature_bundle("ds1", "v1", "fver2", X, y_bad, cols, meta)

    # 3. NaN in X fails validation
    X_nan = X.copy()
    X_nan[0, 0] = np.nan
    with pytest.raises(NpyValidationError, match="contains NaN"):
        repo.publish_feature_bundle("ds1", "v1", "fver3", X_nan, y, cols, meta)

    # Staging temp directories should be cleaned up
    temp_dirs = list((tmp_path / "features_cache").glob(".tmp_*"))
    assert len(temp_dirs) == 0

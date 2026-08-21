"""Comprehensive test suite for Generator Feature domain (POST /feature) and Feature Dataset Bundle."""

from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from systems.generator.app.main import app
from systems.generator.app.feature.feature_schema import FeatureRequest, FeatureResponse
from systems.generator.app.feature.feature_exception import (
    FeatureError,
    FeatureInputNotFoundError,
    FeatureContractError,
    FeatureSchemaMismatchError,
    FeatureLabelAlignmentError,
    FeatureDatasetIntegrityError,
    FeaturePublishConflictError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository, compute_file_sha256
from systems.generator.app.preprocessing.preprocessing_repository import PreprocessingRepository
from systems.generator.generator_config import PATHS


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_feature_environment(tmp_path, monkeypatch):
    """Set up isolated test data and model store cache directories."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "data_preprocessed", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    # 1. Create Telemetry observation dataset
    telem_df = pd.DataFrame({
        "asset_id": ["A1", "A1", "A1", "A2", "A2", "A2"],
        "timestamp": [
            "2026-01-01 00:00:00",
            "2026-01-01 01:00:00",
            "2026-01-01 02:00:00",
            "2026-01-01 00:00:00",
            "2026-01-01 01:00:00",
            "2026-01-01 02:00:00",
        ],
        "voltage": [220.0, 222.0, 225.0, 221.0, 224.0, 228.0],
        "rotation": [1500.0, 1510.0, 1520.0, 1505.0, 1515.0, 1525.0],
    })
    telem_file = data_dir / "telem_ds" / "v1.0.csv"
    telem_file.parent.mkdir(parents=True, exist_ok=True)
    telem_df.to_csv(telem_file, index=False)

    # 2. Create Failure dataset
    fail_df = pd.DataFrame([{
        "asset_id": "A1",
        "observed_at": "2026-01-01 02:30:00",
        "failure_type": "Overheat",
    }])
    fail_file = data_dir / "fail_ds" / "v1.0.csv"
    fail_file.parent.mkdir(parents=True, exist_ok=True)
    fail_df.to_csv(fail_file, index=False)

    # 3. Create Preprocessing Plan in repository
    prep_repo = PreprocessingRepository(base_dir=models_store / "cache" / "preprocessing_plans")
    plan_dict = {
        "structure_type": "tabular_column_as_attribute",
        "id_column": "asset_id",
        "time_column": "timestamp",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "duplicate_policy": "error",
    }
    prep_repo.publish_plan("telem_ds", "v1.0", plan_dict)

    # 4. Create Ontology Mapping in cache
    map_dir = models_store / "cache" / "mappings"
    map_dir.mkdir(parents=True, exist_ok=True)
    mapping_data = {
        "voltage": "Voltage",
        "rotation": "Rotation",
    }
    with open(map_dir / "ontology-mapping-v1.json", "w", encoding="utf-8") as f:
        json.dump(mapping_data, f)

    return {
        "data_dir": data_dir,
        "models_store": models_store,
        "prep_repo": prep_repo,
    }


def test_feature_api_success_and_5_files_bundle(client, sample_feature_environment):
    """POST /feature successfully generates 5 bundle files, row_metadata, and deterministic version."""
    payload = {
        "dataset_id": "telem_ds",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail_ds",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": False,
    }

    res = client.post("/feature", json=payload, headers={"X-Request-ID": "test-feat-001"})
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == "test-feat-001"

    data = res.json()
    assert data["status"] == "succeeded"
    assert data["dataset_id"] == "telem_ds"
    assert data["dataset_version"] == "v1.0"
    assert data["failure_dataset_id"] == "fail_ds"
    assert data["failure_dataset_version"] == "v1.0"

    outputs = data["outputs"]
    fver = outputs["feature_dataset_version"]
    assert fver.startswith("feature-dataset-")
    assert outputs["row_count"] > 0
    assert outputs["feature_count"] == 4

    # Verify physical files on disk
    models_store = sample_feature_environment["models_store"]
    repo_root = models_store.parent
    features_path = repo_root / outputs["features_uri"]
    labels_path = repo_root / outputs["labels_uri"]
    meta_path = repo_root / outputs["metadata_uri"]
    bundle_dir = features_path.parent

    cols_path = bundle_dir / "feature_columns.json"
    row_meta_path = bundle_dir / "row_metadata.json"

    assert features_path.is_file()
    assert labels_path.is_file()
    assert cols_path.is_file()
    assert row_meta_path.is_file()
    assert meta_path.is_file()

    # Load arrays with allow_pickle=False
    X = np.load(features_path, allow_pickle=False)
    y = np.load(labels_path, allow_pickle=False)
    with open(cols_path, "r", encoding="utf-8") as f:
        cols = json.load(f)
    with open(row_meta_path, "r", encoding="utf-8") as f:
        row_meta = json.load(f)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Verify Invariants
    assert X.shape[0] == y.shape[0] == len(row_meta) == outputs["row_count"]
    assert X.shape[1] == len(cols) == outputs["feature_count"]
    assert X.dtype == np.float64
    assert y.dtype == np.int64
    assert set(np.unique(y)).issubset({0, 1})
    assert np.isfinite(X).all()
    assert np.isfinite(y).all()

    # Verify self-referential checksum is NOT present in metadata
    artifact_files = meta.get("artifact_files", [])
    roles = [a["role"] for a in artifact_files]
    assert set(roles) == {"features", "labels", "feature_columns", "row_metadata"}
    assert "feature_metadata" not in roles


def test_feature_api_http_method_not_allowed(client):
    """GET and PUT /feature should return 405 Method Not Allowed."""
    res_get = client.get("/feature")
    assert res_get.status_code == 405

    res_put = client.put("/feature", json={})
    assert res_put.status_code == 405


def test_feature_api_request_validation_rejections(client):
    """POST /feature rejects invalid parameters (horizon <= 0, path traversal, empty fields)."""
    # 1. Horizon <= 0
    res_horizon = client.post("/feature", json={
        "dataset_id": "ds",
        "dataset_version": "v1",
        "failure_dataset_id": "fail_ds",
        "failure_dataset_version": "v1",
        "preprocessing_plan_version": "p1",
        "mapping_version": "m1",
        "feature_schema_version": "f1",
        "label_schema_version": "l1",
        "prediction_horizon_hours": 0,
    })
    assert res_horizon.status_code == 422
    assert res_horizon.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"

    # 2. Path traversal in dataset_id
    res_traversal = client.post("/feature", json={
        "dataset_id": "../../../etc/passwd",
        "dataset_version": "v1",
        "failure_dataset_id": "fail_ds",
        "failure_dataset_version": "v1",
        "preprocessing_plan_version": "p1",
        "mapping_version": "m1",
        "feature_schema_version": "f1",
        "label_schema_version": "l1",
        "prediction_horizon_hours": 24,
    })
    assert res_traversal.status_code == 422
    assert res_traversal.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_feature_api_input_artifacts_not_found(client, sample_feature_environment):
    """POST /feature returns 404 when input observation dataset, failure dataset, or plan is missing."""
    # Missing observation dataset
    res_missing_obs = client.post("/feature", json={
        "dataset_id": "non_existent_telemetry",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail_ds",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
    })
    assert res_missing_obs.status_code == 404
    assert res_missing_obs.json()["error"]["code"] == "FEATURE_INPUT_NOT_FOUND"

    # Missing failure dataset
    res_missing_fail = client.post("/feature", json={
        "dataset_id": "telem_ds",
        "dataset_version": "v1.0",
        "failure_dataset_id": "non_existent_failure",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
    })
    assert res_missing_fail.status_code == 404
    assert res_missing_fail.json()["error"]["code"] == "FEATURE_INPUT_NOT_FOUND"


def test_deterministic_version_and_bundle_reuse(client, sample_feature_environment):
    """Same inputs produce identical feature_dataset_version; changing failure dataset changes version."""
    payload = {
        "dataset_id": "telem_ds",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail_ds",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": False,
    }

    # 1. First run
    res1 = client.post("/feature", json=payload)
    assert res1.status_code == 200
    fver1 = res1.json()["outputs"]["feature_dataset_version"]

    # 2. Second run with same parameters -> reuses bundle
    res2 = client.post("/feature", json=payload)
    assert res2.status_code == 200
    fver2 = res2.json()["outputs"]["feature_dataset_version"]
    assert fver1 == fver2

    # 3. Create second failure dataset v2 with different content
    data_dir = sample_feature_environment["data_dir"]
    fail_df_v2 = pd.DataFrame([{
        "asset_id": "A2",
        "observed_at": "2026-01-01 02:30:00",
        "failure_type": "Electrical",
    }])
    fail_file_v2 = data_dir / "fail_ds_v2" / "v1.0.csv"
    fail_file_v2.parent.mkdir(parents=True, exist_ok=True)
    fail_df_v2.to_csv(fail_file_v2, index=False)

    payload_v2 = {**payload, "failure_dataset_id": "fail_ds_v2"}
    res3 = client.post("/feature", json=payload_v2)
    assert res3.status_code == 200
    fver3 = res3.json()["outputs"]["feature_dataset_version"]
    assert fver3 != fver1


def test_tampered_bundle_fails_integrity_check(client, sample_feature_environment):
    """Tampered bundle file fails integrity validation with 422 FEATURE_DATASET_INTEGRITY_ERROR."""
    payload = {
        "dataset_id": "telem_ds",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail_ds",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": False,
    }

    res1 = client.post("/feature", json=payload)
    assert res1.status_code == 200
    features_uri = res1.json()["outputs"]["features_uri"]

    models_store = sample_feature_environment["models_store"]
    repo_root = models_store.parent
    features_file = repo_root / features_uri

    # Tamper with the features.npy file on disk
    with open(features_file, "wb") as f:
        f.write(b"tampered invalid content")

    # Next call with rebuild_npy=False should detect checksum corruption
    res_tampered = client.post("/feature", json=payload)
    assert res_tampered.status_code == 422
    assert res_tampered.json()["error"]["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"


def test_feature_label_alignment_fail_fast_incompatible_asset_ids(client, sample_feature_environment):
    """Failure dataset with incompatible asset IDs raises 422 FEATURE_LABEL_ALIGNMENT_ERROR."""
    data_dir = sample_feature_environment["data_dir"]
    incompat_fail = pd.DataFrame([{
        "asset_id": "COMPRESSOR_999",
        "observed_at": "2026-01-01 02:00:00",
        "failure_type": "Bearing",
    }])
    incompat_file = data_dir / "fail_incompat" / "v1.0.csv"
    incompat_file.parent.mkdir(parents=True, exist_ok=True)
    incompat_fail.to_csv(incompat_file, index=False)

    payload = {
        "dataset_id": "telem_ds",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail_incompat",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
    }

    res = client.post("/feature", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "FEATURE_LABEL_ALIGNMENT_ERROR"


def test_feature_schema_mismatch_horizon_rejection(client, sample_feature_environment):
    """Requesting horizon (12h) that does not match Label Schema horizon (24h) raises 422 FEATURE_SCHEMA_MISMATCH_ERROR."""
    payload = {
        "dataset_id": "telem_ds",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail_ds",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",  # expects 24h
        "prediction_horizon_hours": 12,  # mismatch!
    }

    res = client.post("/feature", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "FEATURE_SCHEMA_MISMATCH_ERROR"


def test_healthy_dataset_all_zero_labels_allowed(client, sample_feature_environment):
    """Dataset with no positive failure points generates valid all-zero label bundle."""
    data_dir = sample_feature_environment["data_dir"]
    empty_fail = pd.DataFrame(columns=["asset_id", "observed_at", "failure_type"])
    empty_fail_file = data_dir / "fail_empty" / "v1.0.csv"
    empty_fail_file.parent.mkdir(parents=True, exist_ok=True)
    # Add dummy row with anchor far in future or empty
    empty_fail_df = pd.DataFrame([{
        "asset_id": "A1",
        "observed_at": "2099-01-01 00:00:00",
        "failure_type": "None",
    }])
    empty_fail_df.to_csv(empty_fail_file, index=False)

    payload = {
        "dataset_id": "telem_ds",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail_empty",
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_version": "preprocessing-plan-telem_ds-v1.0",
        "mapping_version": "ontology-mapping-v1",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
    }

    res = client.post("/feature", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "succeeded"


def test_feature_repository_validation_exhaustive(tmp_path):
    """Exhaustive test for validate_feature_bundle checking all integrity violations."""
    repo = FeatureRepository(base_dir=tmp_path / "features_cache")

    inputs_meta = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "dataset_checksum": "aaa",
        "failure_dataset_id": "f1",
        "failure_dataset_version": "v1",
        "failure_dataset_checksum": "bbb",
        "preprocessing_plan_version": "p1",
        "preprocessing_plan_checksum": "ccc",
        "mapping_version": "m1",
        "mapping_checksum": "ddd",
        "feature_schema_version": "pdm-feature-v1",
        "feature_schema_checksum": "eee",
        "label_schema_version": "pdm-label-v1",
        "label_schema_checksum": "fff",
    }
    pred_contract = {"prediction_horizon_hours": 24}
    fver = "feature-dataset-1234567890abcdef"
    target_dir = repo.get_feature_dir("ds1", "v1", fver)

    X = np.ones((5, 2), dtype=np.float64)
    y = np.array([0, 1, 0, 1, 0], dtype=np.int64)
    cols = ["col1", "col2"]
    row_meta = [{"row_index": i, "asset_id": "A1", "timestamp": "2026-01-01"} for i in range(5)]

    # 1. Normal publish
    repo.publish_feature_bundle(
        dataset_id="ds1",
        dataset_version="v1",
        feature_dataset_version=fver,
        X=X,
        y=y,
        feature_names=cols,
        row_metadata=row_meta,
        inputs_metadata=inputs_meta,
        prediction_contract=pred_contract,
        run_id="run-1",
        created_at="2026-01-01T00:00:00Z",
    )
    validated = repo.validate_feature_bundle("ds1", "v1", fver, expected_inputs=inputs_meta, expected_horizon=24)
    assert validated["shape"]["row_count"] == 5

    # 2. Missing labels.npy
    (target_dir / "labels.npy").unlink()
    with pytest.raises(FeatureDatasetIntegrityError, match="누락되었습니다"):
        repo.validate_feature_bundle("ds1", "v1", fver)
    np.save(target_dir / "labels.npy", y, allow_pickle=False)

    # 3. Shape mismatch (X rows != y rows)
    np.save(target_dir / "labels.npy", np.array([0, 1], dtype=np.int64), allow_pickle=False)
    with pytest.raises(FeatureDatasetIntegrityError):
        repo.validate_feature_bundle("ds1", "v1", fver)
    np.save(target_dir / "labels.npy", y, allow_pickle=False)

    # 4. Checksum mismatch when file is rewritten
    np.save(target_dir / "labels.npy", np.array([1, 1, 1, 1, 1], dtype=np.int64), allow_pickle=False)
    with pytest.raises(FeatureDatasetIntegrityError, match="체크섬 불일치"):
        repo.validate_feature_bundle("ds1", "v1", fver)

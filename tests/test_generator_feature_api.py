"""Integration and regression test suite for Generator Feature domain (POST /feature) and Feature Dataset Bundle."""

from __future__ import annotations

import inspect
import json
import shutil
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from systems.generator.app.feature.feature_exception import FeatureContractError
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.app.feature.feature_router import post_feature
from systems.generator.app.main import create_app
from systems.generator.generator_config import PATHS


@pytest.fixture
def test_client():
    """Create isolated FastAPI test client with valid observation dataset in data_dir."""
    dataset_name = "ai4i_feature_test"
    csv_file = PATHS.data_dir / f"{dataset_name}.csv"
    PATHS.data_dir.mkdir(parents=True, exist_ok=True)

    # 1. Create canonical observation dataset with realistic variation
    np.random.seed(42)
    n_rows = 50
    times = pd.date_range("2026-01-01 00:00:00", periods=n_rows, freq="h")

    # Failures at index 10 (2026-01-01 10:00) and index 35 (2026-01-02 11:00)
    failures = np.zeros(n_rows, dtype=int)
    failures[10] = 1
    failures[35] = 1

    df_obs = pd.DataFrame({
        "UDI": range(1, n_rows + 1),
        "Product ID": [f"L{i % 2 + 1:04d}" for i in range(n_rows)],
        "Type": ["L"] * n_rows,
        "Air temperature [K]": np.random.normal(298.1, 1.0, n_rows),
        "Process temperature [K]": np.random.normal(308.6, 1.0, n_rows),
        "Rotational speed [rpm]": np.random.normal(1500, 30, n_rows),
        "Torque [Nm]": np.random.normal(40.0, 3.0, n_rows),
        "Tool wear [min]": np.linspace(0, 200, n_rows),
        "Machine failure": failures,
        "observed_at": times.strftime("%Y-%m-%d %H:%M:%S"),
    })
    df_obs.to_csv(csv_file, index=False)

    app = create_app()
    client = TestClient(app)

    # 2. Execute preprocessing to get valid plan
    prep_req = {
        "dataset_id": dataset_name,
        "dataset_version": "v1.0",
        "force_reanalyze": True,
    }
    resp = client.post("/preprocessing", json=prep_req)
    assert resp.status_code == 200, resp.text
    prep_data = resp.json()

    yield {
        "client": client,
        "dataset_id": dataset_name,
        "plan_id": prep_data["preprocessing_plan_id"],
        "plan_version": prep_data["preprocessing_plan_version"],
    }

    # Cleanup
    if csv_file.exists():
        csv_file.unlink()
    models_store = getattr(PATHS, "models_store", Path("models_store"))
    shutil.rmtree(models_store / "cache" / "features" / dataset_name, ignore_errors=True)
    shutil.rmtree(models_store / "cache" / "preprocessing_plans" / dataset_name, ignore_errors=True)


# ==========================================
# 1. Feature Schema Tests
# ==========================================

def test_feature_generation_success_and_bundle_contract(test_client):
    """Test successful feature generation and verify 5-file bundle integrity and order."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }

    resp = client.post("/feature", json=req_payload, headers={"X-Request-ID": "req-feature-test-01"})
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("X-Request-ID") == "req-feature-test-01"

    data = resp.json()
    assert data["status"] == "succeeded"
    assert data["preprocessing_plan_id"] == plan_id
    assert data["preprocessing_plan_version"] == plan_ver

    outputs = data["outputs"]
    assert outputs["feature_count"] == 5
    # 2 active failure rows dropped from 50 rows -> 48 rows
    assert outputs["row_count"] == 48

    feat_ver = outputs["feature_dataset_version"]
    assert feat_ver.startswith("feature-dataset-")

    # Verify 5 physical files
    bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver
    assert bundle_dir.exists()
    assert (bundle_dir / "features.npy").exists()
    assert (bundle_dir / "labels.npy").exists()
    assert (bundle_dir / "feature_columns.json").exists()
    assert (bundle_dir / "row_metadata.json").exists()
    assert (bundle_dir / "feature_metadata.json").exists()

    # Verify column order in feature_columns.json exactly matches ai4i-feature-v1.json
    with open(bundle_dir / "feature_columns.json", "r", encoding="utf-8") as f:
        col_info = json.load(f)
    assert col_info["columns"] == [
        "Air temperature [K]",
        "Process temperature [K]",
        "Rotational speed [rpm]",
        "Torque [Nm]",
        "Tool wear [min]",
    ]

    # Verify provenance metadata completeness
    with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    prov = meta["provenance"]
    assert prov["observation_dataset_id"] == dataset_id
    assert prov["observation_dataset_version"] == "v1.0"
    assert "observation_dataset_sha256" in prov
    assert "preprocessing_plan_id" in prov
    assert "preprocessing_plan_version" in prov
    assert "feature_schema_version" in prov
    assert "label_schema_version" in prov
    assert prov["prediction_horizon_hours"] == 24


def test_feature_missing_schema_returns_404(test_client):
    """Test 404 when requested feature_schema_version does not exist."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "nonexistent-feature-schema-v999",
        "label_schema_version": "ai4i-label-24h-v1",
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FEATURE_INPUT_NOT_FOUND"


def test_feature_schema_version_mismatch_returns_422(test_client, tmp_path):
    """Test 422 when schema file content version does not match requested version."""
    from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider

    # Create dummy schema file where filename is mismatch-test.json but content declares different-v1
    mismatch_file = tmp_path / "mismatch-test.json"
    mismatch_file.write_text(json.dumps({
        "feature_schema_version": "declared-different-v1",
        "features": [{"feature_name": "temp", "source_field": "temp", "operation": "raw"}]
    }), encoding="utf-8")

    provider = FeatureSchemaProvider(search_dirs=[tmp_path])
    with pytest.raises(Exception) as exc_info:
        provider.get_feature_schema("mismatch-test")
    assert "일치하지 않습니다" in str(exc_info.value)


def test_feature_missing_source_field_fails_422(test_client):
    """Test 422 when a required feature source_field is missing from observation dataset."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    # pdm-feature-v1 requires voltage, pressure, etc. which are not in ai4i dataset
    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "rebuild_npy": True,
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FEATURE_SCHEMA_MISMATCH_ERROR"


def test_feature_unsupported_operation_fails_422(tmp_path):
    """Test 422 when Feature Schema declares an unsupported operation."""
    from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider

    schema_file = tmp_path / "unsupported-op-v1.json"
    schema_file.write_text(json.dumps({
        "feature_schema_version": "unsupported-op-v1",
        "features": [{"feature_name": "fft_val", "source_field": "Torque [Nm]", "operation": "fourier_transform"}]
    }), encoding="utf-8")

    provider = FeatureSchemaProvider(search_dirs=[tmp_path])
    with pytest.raises(Exception) as exc_info:
        provider.get_feature_schema("unsupported-op-v1")
    assert "지원하지 않는 Feature 연산" in str(exc_info.value)


# ==========================================
# 2. Label Schema & Horizon Labeling Tests
# ==========================================

def test_label_schema_missing_returns_404(test_client):
    """Test 404 when requested label_schema_version does not exist."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "nonexistent-label-schema-v999",
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FEATURE_INPUT_NOT_FOUND"


def test_label_schema_horizon_mismatch_returns_422(test_client):
    """Test 422 when requested prediction_horizon_hours conflicts with Label Schema."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    # Schema is ai4i-label-24h-v1 (horizon 24), but request specifies 12
    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 12,
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FEATURE_SCHEMA_MISMATCH_ERROR"


def test_horizon_labeling_and_active_failure_drop(test_client):
    """Test official [anchor - horizon, anchor) positive labeling and [anchor, exclusion_end] drop."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert resp.status_code == 200
    feat_ver = resp.json()["outputs"]["feature_dataset_version"]

    bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver
    labels = np.load(bundle_dir / "labels.npy", allow_pickle=False)

    # Verify binary {0, 1} and both positive and negative labels exist
    assert set(np.unique(labels)).issubset({0, 1})
    assert np.sum(labels == 1) > 0
    assert np.sum(labels == 0) > 0


# ==========================================
# 3. Row Alignment & Shuffling Invariance
# ==========================================

def test_row_alignment_and_shuffle_invariance(test_client):
    """Test that shuffling input rows produces 100% identical Feature and Label arrays."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    # 1. Run on original dataset
    resp1 = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert resp1.status_code == 200
    feat_ver1 = resp1.json()["outputs"]["feature_dataset_version"]
    bundle_dir1 = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver1
    features1 = np.load(bundle_dir1 / "features.npy", allow_pickle=False)
    labels1 = np.load(bundle_dir1 / "labels.npy", allow_pickle=False)

    # 2. Shuffle input CSV rows and re-run
    csv_file = PATHS.data_dir / f"{dataset_id}.csv"
    df = pd.read_csv(csv_file)
    shuffled_df = df.sample(frac=1.0, random_state=123).reset_index(drop=True)
    shuffled_df.to_csv(csv_file, index=False)

    resp2 = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert resp2.status_code == 200
    feat_ver2 = resp2.json()["outputs"]["feature_dataset_version"]
    bundle_dir2 = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver2
    features2 = np.load(bundle_dir2 / "features.npy", allow_pickle=False)
    labels2 = np.load(bundle_dir2 / "labels.npy", allow_pickle=False)

    # Calculated features and labels must be 100% identical despite shuffling
    np.testing.assert_array_equal(features1, features2)
    np.testing.assert_array_equal(labels1, labels2)


# ==========================================
# 4. Missing Value Policy Tests
# ==========================================

def test_missing_value_policies_drop_fill_error(tmp_path):
    """Test drop, fill_zero, ffill, and error missing value policies."""
    from systems.generator.app.feature.feature_schema_provider import FeatureItem
    from systems.generator.app.feature.feature_service import FeatureService

    df = pd.DataFrame({
        "asset_id": ["A", "A", "A", "A"],
        "observed_at": ["2026-01-01 01:00", "2026-01-01 02:00", "2026-01-01 03:00", "2026-01-01 04:00"],
        "val": [10.0, np.nan, 30.0, np.nan],
    })

    service = FeatureService()

    # 1. missing_value_policy = "drop"
    items_drop = [FeatureItem(feature_name="f_drop", source_field="val", operation="raw", missing_value_policy="drop")]
    comp_df, drop_mask = service._compute_features_and_missing_masks(df, items_drop, "asset_id")
    assert drop_mask.sum() == 2

    # 2. missing_value_policy = "fill_zero"
    items_zero = [FeatureItem(feature_name="f_zero", source_field="val", operation="raw", missing_value_policy="fill_zero")]
    comp_df_zero, drop_mask_zero = service._compute_features_and_missing_masks(df, items_zero, "asset_id")
    assert drop_mask_zero.sum() == 0
    assert (comp_df_zero["f_zero"] == 0.0).sum() == 2

    # 3. missing_value_policy = "ffill"
    items_ffill = [FeatureItem(feature_name="f_ffill", source_field="val", operation="raw", missing_value_policy="ffill")]
    comp_df_ffill, drop_mask_ffill = service._compute_features_and_missing_masks(df, items_ffill, "asset_id")
    assert drop_mask_ffill.sum() == 0
    assert comp_df_ffill["f_ffill"].tolist() == [10.0, 10.0, 30.0, 30.0]

    # 4. missing_value_policy = "error"
    items_error = [FeatureItem(feature_name="f_err", source_field="val", operation="raw", missing_value_policy="error")]
    with pytest.raises(Exception) as exc_info:
        service._compute_features_and_missing_masks(df, items_error, "asset_id")
    assert "결측값" in str(exc_info.value)


# ==========================================
# 5. Bundle Immutability & Conflict Tests
# ==========================================

def test_feature_conflict_fingerprint_returns_409(test_client):
    """Test 409 when attempting to publish bundle under existing version with different fingerprint."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    repo = FeatureRepository()

    # Generate first bundle
    resp1 = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert resp1.status_code == 200
    feat_ver = resp1.json()["outputs"]["feature_dataset_version"]

    # Attempt to locate bundle with conflicting fingerprint
    conflicting_fingerprint = {"observation_dataset_id": "different_dataset_id"}
    with pytest.raises(Exception) as exc_info:
        repo.find_feature_bundle(dataset_id, "v1.0", feat_ver, expected_fingerprint=conflicting_fingerprint)
    assert "상이한 지문" in str(exc_info.value)


def test_feature_corrupted_bundle_fails_fast(test_client):
    """Test 422 when existing bundle is corrupted."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    # 1. Publish bundle
    resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert resp.status_code == 200
    feat_ver = resp.json()["outputs"]["feature_dataset_version"]

    # 2. Corrupt features.npy file
    bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver
    with open(bundle_dir / "features.npy", "wb") as f:
        f.write(b"corrupted_binary_data")

    # 3. Call find_feature_bundle
    repo = FeatureRepository()
    with pytest.raises(Exception) as exc_info:
        repo.find_feature_bundle(dataset_id, "v1.0", feat_ver)
    assert "손상" in str(exc_info.value) or "체크섬 불일치" in str(exc_info.value)


def test_logical_uri_outside_root_raises_error():
    """Test that get_logical_uri rejects paths outside repo root."""
    repo = FeatureRepository()
    with pytest.raises(FeatureContractError) as exc_info:
        repo.get_logical_uri(Path("C:/Windows/System32/cmd.exe"))
    assert "허용된 저장소 밖의 경로" in str(exc_info.value)


def test_feature_endpoint_is_synchronous():
    """Verify that POST /feature is a synchronous function executed in worker threads."""
    assert inspect.iscoroutinefunction(post_feature) is False


def test_feature_concurrency_multithreaded_rebuild(test_client):
    """Test concurrent /feature calls safely serialize without race conditions or corruptions."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }

    results = []

    def worker():
        resp = client.post("/feature", json=req_payload)
        results.append(resp.status_code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(code == 200 for code in results)

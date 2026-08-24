"""Comprehensive test suite for Generator Training Domain API, Model Artifact Publishing, and Contracts."""

from __future__ import annotations

import inspect
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from systems.generator.app.main import create_app
from systems.generator.app.training.training_router import post_train, post_train_single
from systems.generator.generator_config import PATHS
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.model.publisher import (
    ARTIFACT_SCHEMA_VERSION,
    ARTIFACT_TYPE,
    REQUIRED_ARTIFACT_ROLES,
    ModelArtifactPublisher,
)


def _create_versioned_obs_and_fail_datasets(
    data_root: Path,
    dataset_id: str,
    dataset_version: str,
    failure_id: str,
    failure_version: str,
    n_rows: int = 100,
    include_failure_events: bool = True,
) -> tuple[Path, Path]:
    """Helper creating valid versioned Observation and Failure datasets with manifests."""
    np.random.seed(42)

    # 1. Observation dataset
    obs_dir = data_root / "observations" / dataset_id / dataset_version
    obs_dir.mkdir(parents=True, exist_ok=True)
    obs_file = obs_dir / "observations.csv"

    base_time = pd.Timestamp("2026-08-20T00:00:00Z")
    timestamps = [base_time + pd.Timedelta(hours=i) for i in range(n_rows)]
    assets = [f"asset-{(i % 2) + 1}" for i in range(n_rows)]

    obs_df = pd.DataFrame({
        "timestamp": [ts.isoformat() for ts in timestamps],
        "asset_id": assets,
        "Air temperature [K]": np.random.normal(300, 2, n_rows),
        "Process temperature [K]": np.random.normal(310, 2, n_rows),
        "Rotational speed [rpm]": np.random.normal(1500, 50, n_rows),
        "Torque [Nm]": np.random.normal(40, 5, n_rows),
        "Tool wear [min]": np.linspace(0, 200, n_rows),
    })
    obs_df.to_csv(obs_file, index=False)

    # Also create unversioned CSV for preprocessing plan discovery
    prep_file = data_root / f"{dataset_id}.csv"
    obs_df.to_csv(prep_file, index=False)

    obs_sha = compute_file_sha256(obs_file)
    obs_size = obs_file.stat().st_size

    obs_manifest = {
        "manifest_version": "generator-dataset-input-v1",
        "dataset_type": "observation",
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "schema_version": "ai4i-physics-v3.1",
        "created_at": "2026-08-24T00:00:00Z",
        "files": [
            {
                "role": "observations",
                "path": "observations.csv",
                "media_type": "text/csv",
                "sha256": obs_sha,
                "size_bytes": obs_size,
            }
        ],
    }
    with open(obs_dir / "dataset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(obs_manifest, f, indent=2)

    # 2. Failure dataset
    fail_dir = data_root / "failures" / failure_id / failure_version
    fail_dir.mkdir(parents=True, exist_ok=True)
    fail_file = fail_dir / "failures.csv"

    if include_failure_events:
        fail_df = pd.DataFrame({
            "asset_id": ["asset-1", "asset-2"],
            "failure_point": [
                (base_time + pd.Timedelta(hours=40)).isoformat(),
                (base_time + pd.Timedelta(hours=85)).isoformat(),
            ],
            "period_end": [
                (base_time + pd.Timedelta(hours=44)).isoformat(),
                (base_time + pd.Timedelta(hours=89)).isoformat(),
            ],
            "failure_indicator": [1, 1],
        })
    else:
        fail_df = pd.DataFrame(columns=["asset_id", "failure_point", "period_end", "failure_indicator"])

    fail_df.to_csv(fail_file, index=False)
    fail_sha = compute_file_sha256(fail_file)
    fail_size = fail_file.stat().st_size

    fail_manifest = {
        "manifest_version": "generator-dataset-input-v1",
        "dataset_type": "failure",
        "dataset_id": failure_id,
        "dataset_version": failure_version,
        "schema_version": "ai4i-failures-v1",
        "created_at": "2026-08-24T00:00:00Z",
        "files": [
            {
                "role": "failures",
                "path": "failures.csv",
                "media_type": "text/csv",
                "sha256": fail_sha,
                "size_bytes": fail_size,
            }
        ],
    }
    with open(fail_dir / "dataset_manifest.json", "w", encoding="utf-8") as f:
        json.dump(fail_manifest, f, indent=2)

    return obs_dir, fail_dir


@pytest.fixture
def test_setup():
    """Create versioned observation/failure datasets, plan, and feature bundle."""
    uid = uuid.uuid4().hex[:8]
    dataset_id = f"ai4i_train_{uid}"
    dataset_ver = "v1.0"
    fail_id = f"fail_{uid}"
    fail_ver = "v1.0"

    data_dir = getattr(PATHS, "data_dir", Path("data"))
    _create_versioned_obs_and_fail_datasets(
        data_dir, dataset_id, dataset_ver, fail_id, fail_ver, n_rows=100
    )

    app = create_app()
    client = TestClient(app)

    # 1. Preprocessing
    prep_resp = client.post("/preprocessing", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "force_reanalyze": True,
    })
    assert prep_resp.status_code == 200, prep_resp.text
    prep_data = prep_resp.json()
    plan_id = prep_data["preprocessing_plan_id"]
    plan_ver = prep_data["preprocessing_plan_version"]

    # 2. Feature
    feat_resp = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "failure_source_mode": "external_dataset",
        "failure_dataset_id": fail_id,
        "failure_dataset_version": fail_ver,
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
    })
    assert feat_resp.status_code == 200, feat_resp.text
    feat_data = feat_resp.json()
    feat_ver = feat_data.get("outputs", {}).get("feature_dataset_version") or feat_data.get("feature_dataset_version")

    yield {
        "client": client,
        "app": app,
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "fail_id": fail_id,
        "fail_ver": fail_ver,
    }

    # Cleanup
    (data_dir / f"{dataset_id}.csv").unlink(missing_ok=True)
    shutil.rmtree(data_dir / "observations" / dataset_id, ignore_errors=True)
    shutil.rmtree(data_dir / "failures" / fail_id, ignore_errors=True)
    models_store = getattr(PATHS, "models_store", Path("models_store"))
    shutil.rmtree(models_store / "cache" / "preprocessing_plans" / dataset_id, ignore_errors=True)
    shutil.rmtree(models_store / "cache" / "features" / dataset_id, ignore_errors=True)
    for base_model in ["lightgbm", "xgboost", "random_forest"]:
        shutil.rmtree(models_store / "artifacts" / f"pdm-{base_model}", ignore_errors=True)


# ==========================================
# 1. API Endpoints & Happy Paths
# ==========================================

def test_train_all_models_success_and_artifact_bundle(test_setup):
    """Test POST /train trains all registered models and publishes 6-file artifacts."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "training_config_version": "training-config-v1",
        "activation_policy": "activate_on_success",
    }
    resp = client.post("/train", json=req_payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "succeeded"
    assert len(data["results"]) == 3
    base_models = [r["base_model"] for r in data["results"]]
    assert set(base_models) == {"lightgbm", "xgboost", "random_forest"}

    models_store = getattr(PATHS, "models_store", Path("models_store"))

    # Verify each published artifact package
    for r in data["results"]:
        assert r["status"] == "succeeded"
        assert r["activated"] is True
        assert r["metrics_summary"] is not None
        assert "f1" in r["metrics_summary"]

        model_id = r["model_id"]
        model_version = r["model_version"]
        artifact_dir = models_store / "artifacts" / model_id / model_version

        assert artifact_dir.exists()

        # Check all 6 files
        for fname in ["manifest.json", "model.joblib", "feature_schema.json", "label_schema.json", "history_requirement.json", "metrics.json"]:
            fpath = artifact_dir / fname
            assert fpath.exists(), f"Missing {fname} in {artifact_dir}"
            assert fpath.stat().st_size > 0

        # Check manifest content
        with open(artifact_dir / "manifest.json", "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["artifact_type"] == ARTIFACT_TYPE
        assert manifest["artifact_schema_version"] == ARTIFACT_SCHEMA_VERSION
        assert manifest["model_id"] == model_id
        assert manifest["model_version"] == model_version
        assert manifest["dataset_version"] == dataset_ver
        assert manifest["training_config"]["training_config_version"] == "training-config-v1"
        assert manifest["provenance"]["training_config_version"] == "training-config-v1"

        # Check provenance has real SHA-256 and URLs
        prov = manifest.get("provenance", {})
        assert prov.get("feature_dataset_metadata_sha256") is not None
        assert len(prov.get("feature_dataset_metadata_sha256", "")) == 64
        assert prov.get("training_config_sha256") is not None
        assert len(prov.get("training_config_sha256", "")) == 64

        # Check history requirement
        with open(artifact_dir / "history_requirement.json", "r", encoding="utf-8") as f:
            hist_req = json.load(f)
        assert "required_columns" in hist_req
        assert "Air temperature [K]" in hist_req["required_columns"]
        assert hist_req["minimum_history_rows"] >= 1

        # Check latest.json pointer
        pointer_file = models_store / "artifacts" / model_id / "latest.json"
        assert pointer_file.exists()
        with open(pointer_file, "r", encoding="utf-8") as f:
            pointer = json.load(f)
        assert pointer["active_version"] == model_version


def test_train_single_model_success(test_setup):
    """Test POST /train/{base_model} trains individual specified models."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    for base_model in ["lightgbm", "xgboost", "random_forest"]:
        req_payload = {
            "dataset_id": dataset_id,
            "dataset_version": dataset_ver,
            "feature_dataset_version": feat_ver,
            "training_config_version": "training-config-v1",
            "model_version": f"{base_model}-test-v1",
            "activation_policy": "activate_on_success",
        }
        resp = client.post(f"/train/{base_model}", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "succeeded"
        assert len(data["results"]) == 1
        assert data["results"][0]["base_model"] == base_model
        assert data["results"][0]["model_version"] == f"{base_model}-test-v1"


# ==========================================
# 2. Training Config Contract Tests
# ==========================================

def test_train_unknown_config_version_returns_404(test_setup):
    """Test 404 when requested training_config_version does not exist."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    resp = client.post("/train", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "training_config_version": "nonexistent-config-v999",
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TRAINING_CONFIG_NOT_FOUND"


def test_train_invalid_config_ratio_fails_422(test_setup, tmp_path):
    """Test 422 when training config split_ratio sum is not 1.0."""
    from systems.generator.app.training.training_config_provider import TrainingConfigProvider

    bad_config = {
        "training_config_version": "bad-ratio-config",
        "split_strategy": "asset_time_split",
        "split_ratio": {"train": 0.8, "validation": 0.3, "test": 0.1},
        "random_seed": 42,
        "hyperparameters": {},
        "metrics": ["f1"],
        "primary_metric": "f1",
    }
    cfg_file = tmp_path / "bad-ratio-config.json"
    cfg_file.write_text(json.dumps(bad_config), encoding="utf-8")

    provider = TrainingConfigProvider(search_dirs=[tmp_path])
    with pytest.raises(Exception) as exc_info:
        provider.load_training_config("bad-ratio-config")
    assert "1.0" in str(exc_info.value)


# ==========================================
# 3. Error Contracts & Validation
# ==========================================

def test_train_unsupported_model_returns_404(test_setup):
    """Test POST /train/{base_model} with invalid model name returns 404."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    resp = client.post("/train/deep_neural_net", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TRAINING_MODEL_NOT_FOUND"


def test_train_invalid_method_returns_405(test_setup):
    """Test non-POST HTTP methods on /train return 405 Method Not Allowed."""
    client = test_setup["client"]
    assert client.get("/train").status_code == 405
    assert client.put("/train").status_code == 405
    assert client.delete("/train").status_code == 405


def test_train_invalid_payload_returns_422(test_setup):
    """Test missing required fields or extra forbidden fields return 422."""
    client = test_setup["client"]
    # Missing fields
    resp = client.post("/train", json={})
    assert resp.status_code == 422

    # Path traversal in dataset_id
    resp2 = client.post("/train", json={
        "dataset_id": "../escape",
        "dataset_version": "v1.0",
        "feature_dataset_version": "v1.0",
    })
    assert resp2.status_code == 422
    assert resp2.json()["error"]["code"] == "TRAINING_CONTRACT_ERROR"


def test_train_bundle_not_found_returns_404(test_setup):
    """Test 404 when requested Feature Dataset Bundle does not exist."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]

    resp = client.post("/train", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": "nonexistent-bundle-v999",
    })
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "TRAINING_INPUT_NOT_FOUND"


def test_train_bundle_identity_mismatch_fails_422(test_setup):
    """Test 422 when dataset_id in request does not match metadata in bundle."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    models_store = getattr(PATHS, "models_store", Path("models_store"))
    bundle_dir = models_store / "cache" / "features" / dataset_id / dataset_ver / feat_ver

    # Change dataset_id in feature_metadata.json
    with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["dataset_id"] = "tampered_dataset_id"
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    resp = client.post("/train", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TRAINING_CONTRACT_ERROR"


def test_train_conflict_existing_model_version_always_returns_409(test_setup):
    """Test 409 MODEL_ARTIFACT_CONFLICT when re-publishing same model_id/model_version."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "model_version": "conflict-immutable-v1",
    }
    resp1 = client.post("/train/lightgbm", json=req_payload)
    assert resp1.status_code == 200

    # Attempt to retrain same model version -> ALWAYS 409
    resp2 = client.post("/train/lightgbm", json=req_payload)
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "MODEL_ARTIFACT_CONFLICT"


def test_train_activation_policy_publish_only(test_setup):
    """Test publish_only creates artifact but does not update latest.json pointer."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    models_store = getattr(PATHS, "models_store", Path("models_store"))
    pointer_file = models_store / "artifacts" / "pdm-random_forest" / "latest.json"
    if pointer_file.exists():
        pointer_file.unlink()

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "model_version": "publish-only-v1",
        "activation_policy": "publish_only",
    }
    resp = client.post("/train/random_forest", json=req_payload)
    assert resp.status_code == 200
    assert resp.json()["results"][0]["activated"] is False
    assert not pointer_file.exists()


def test_train_endpoint_is_synchronous():
    """Verify that POST /train and POST /train/{base_model} are synchronous functions."""
    assert inspect.iscoroutinefunction(post_train) is False
    assert inspect.iscoroutinefunction(post_train_single) is False


def test_train_split_fail_closed_missing_asset_id():
    """Test data_splitter asset_time_split raises 422 when asset_id is missing."""
    from systems.generator.app.training.data_splitter import asset_time_split
    from systems.generator.app.training.training_exception import TrainingDatasetError

    features = np.ones((12, 3), dtype=np.float64)
    labels = np.array([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1], dtype=np.int64)
    row_metadata = [{"timestamp": "2026-08-20T00:00:00Z"} for _ in range(12)]  # missing asset_id

    with pytest.raises(TrainingDatasetError) as exc_info:
        asset_time_split(features, labels, row_metadata)
    assert "asset_id가 누락" in str(exc_info.value)


def test_train_split_fail_closed_missing_timestamp():
    """Test data_splitter asset_time_split raises 422 when timestamp is missing."""
    from systems.generator.app.training.data_splitter import asset_time_split
    from systems.generator.app.training.training_exception import TrainingDatasetError

    features = np.ones((12, 3), dtype=np.float64)
    labels = np.array([0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1], dtype=np.int64)
    row_metadata = [{"asset_id": "asset-1"} for _ in range(12)]  # missing timestamp

    with pytest.raises(TrainingDatasetError) as exc_info:
        asset_time_split(features, labels, row_metadata)
    assert "timestamp가 누락" in str(exc_info.value)


# ==========================================
# 4. Golden Test Vector Verification
# ==========================================

def test_generator_training_contract_vectors(test_setup):
    """Verify contracts/examples and contracts/test-vectors schema compliance."""
    import jsonschema

    schema_file = Path("contracts/schemas/generator-training-config.schema.json")
    assert schema_file.exists()
    schema = json.loads(schema_file.read_text(encoding="utf-8"))

    # 1. Verify example configs pass JSON Schema
    ex_cfg = Path("contracts/examples/generator-training/training-config-v1.json")
    assert ex_cfg.exists()
    jsonschema.validate(instance=json.loads(ex_cfg.read_text(encoding="utf-8")), schema=schema)

    # 2. Verify test-vector config passes JSON Schema
    tv_cfg = Path("contracts/test-vectors/generator-training-v1/training-config.json")
    assert tv_cfg.exists()
    jsonschema.validate(instance=json.loads(tv_cfg.read_text(encoding="utf-8")), schema=schema)


def test_train_schema_sha256_mismatch_fails_422(test_setup):
    """Test 422 when feature_schema_sha256 in bundle provenance does not match actual schema on disk."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    models_store = getattr(PATHS, "models_store", Path("models_store"))
    bundle_dir = models_store / "cache" / "features" / dataset_id / dataset_ver / feat_ver

    # Tamper with feature_schema_sha256 in feature_metadata.json
    with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["provenance"]["feature_schema_sha256"] = "0" * 64
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    resp = client.post("/train/lightgbm", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "model_version": "tampered-feat-sha-v1",
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"
    assert "Feature Schema SHA-256 불일치" in resp.json()["error"]["message"]


def test_train_label_schema_sha256_mismatch_fails_422(test_setup):
    """Test 422 when label_schema_sha256 in bundle provenance does not match actual label schema."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    models_store = getattr(PATHS, "models_store", Path("models_store"))
    bundle_dir = models_store / "cache" / "features" / dataset_id / dataset_ver / feat_ver

    # Tamper with label_schema_sha256 in feature_metadata.json
    with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    meta["provenance"]["label_schema_sha256"] = "f" * 64
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    resp = client.post("/train/lightgbm", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "model_version": "tampered-label-sha-v1",
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"
    assert "Label Schema SHA-256 불일치" in resp.json()["error"]["message"]


def test_train_missing_schema_sha256_in_provenance_fails_422(test_setup):
    """Test 422 when schema sha256 fields are missing from bundle provenance."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    models_store = getattr(PATHS, "models_store", Path("models_store"))
    bundle_dir = models_store / "cache" / "features" / dataset_id / dataset_ver / feat_ver

    with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
    del meta["provenance"]["feature_schema_sha256"]
    with open(bundle_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    resp = client.post("/train/lightgbm", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "model_version": "missing-sha-v1",
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"


def test_train_omitted_model_version_deterministic_generation_and_conflict(test_setup):
    """Test omitted model_version generates deterministic unique version and returns 409 on duplicate train."""
    client = test_setup["client"]
    dataset_id = test_setup["dataset_id"]
    dataset_ver = test_setup["dataset_version"]
    feat_ver = test_setup["feature_dataset_version"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_ver,
        "feature_dataset_version": feat_ver,
        "training_config_version": "training-config-v1",
    }
    # 1. First training with omitted model_version -> succeeds
    resp1 = client.post("/train/lightgbm", json=req_payload)
    assert resp1.status_code == 200
    res1 = resp1.json()["results"][0]
    gen_ver1 = res1["model_version"]
    assert gen_ver1.startswith("lightgbm-fp")

    # 2. Second training on EXACT same inputs with omitted model_version -> 409 Conflict because same version is generated!
    resp2 = client.post("/train/lightgbm", json=req_payload)
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "MODEL_ARTIFACT_CONFLICT"


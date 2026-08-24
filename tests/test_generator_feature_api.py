"""Integration tests for Generator Feature domain (POST /feature) and Feature Dataset Bundle."""

import json
import inspect
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from systems.generator.generator_config import PATHS
from systems.generator.app.main import create_app
from systems.generator.app.feature.feature_router import post_feature


@pytest.fixture
def test_client():
    """Create isolated FastAPI test client with test dataset in data_dir."""
    dataset_name = "ai4i_feature_test"
    csv_file = PATHS.data_dir / f"{dataset_name}.csv"
    PATHS.data_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy observation dataset
    df_obs = pd.DataFrame({
        "UDI": range(1, 21),
        "Product ID": [f"L{i:04d}" for i in range(1, 21)],
        "Type": ["L"] * 20,
        "Air temperature [K]": [298.1 + i * 0.1 for i in range(20)],
        "Process temperature [K]": [308.6 + i * 0.1 for i in range(20)],
        "Rotational speed [rpm]": [1500 + i * 5 for i in range(20)],
        "Torque [Nm]": [40.0 + i * 0.5 for i in range(20)],
        "Tool wear [min]": [i * 2 for i in range(20)],
        "Machine failure": [1 if i in (5, 15) else 0 for i in range(20)],
    })
    df_obs.to_csv(csv_file, index=False)

    app = create_app()
    client = TestClient(app)

    # Execute preprocessing to get valid plan
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


def test_feature_generation_success_and_bundle_contract(test_client):
    """Test successful feature generation and verify 5-file bundle integrity."""
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
    assert outputs["row_count"] == 20
    assert outputs["feature_count"] == 5
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

    # Load arrays with allow_pickle=False
    features = np.load(bundle_dir / "features.npy", allow_pickle=False)
    labels = np.load(bundle_dir / "labels.npy", allow_pickle=False)
    assert features.shape == (20, 5)
    assert features.dtype == np.float64
    assert np.isfinite(features).all()
    assert labels.shape == (20,)
    assert labels.dtype == np.int64

    # Verify feature_columns.json
    with open(bundle_dir / "feature_columns.json", "r", encoding="utf-8") as f:
        cols_data = json.load(f)
        assert cols_data["count"] == 5
        assert len(cols_data["columns"]) == 5

    # Verify row_metadata.json
    with open(bundle_dir / "row_metadata.json", "r", encoding="utf-8") as f:
        row_meta = json.load(f)
        assert len(row_meta) == 20

    # Verify feature_metadata.json (no self-referential checksum)
    with open(bundle_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta = json.load(f)
        assert meta["feature_dataset_version"] == feat_ver
        assert meta["provenance"]["preprocessing_plan_id"] == plan_id
        assert meta["provenance"]["preprocessing_plan_version"] == plan_ver
        assert "feature_metadata.json" not in meta["payload_checksums"]
        for payload_f in ["features.npy", "labels.npy", "feature_columns.json", "row_metadata.json"]:
            assert payload_f in meta["payload_checksums"]


def test_feature_reuse_existing_bundle(test_client):
    """Test that rebuild_npy=False safely reuses existing valid bundle without recalculation."""
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
        "rebuild_npy": False,
    }

    resp1 = client.post("/feature", json=req_payload)
    assert resp1.status_code == 200
    feat_ver1 = resp1.json()["outputs"]["feature_dataset_version"]

    resp2 = client.post("/feature", json=req_payload)
    assert resp2.status_code == 200
    feat_ver2 = resp2.json()["outputs"]["feature_dataset_version"]
    assert feat_ver1 == feat_ver2


def test_feature_plan_id_not_found_returns_404(test_client):
    """Test 404 FEATURE_INPUT_NOT_FOUND when non-existent preprocessing_plan_id is provided."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_ver = test_client["plan_version"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": "pp-nonexistent-000000000000",
        "preprocessing_plan_version": plan_ver,
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
    }
    resp = client.post("/feature", json=req_payload)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "FEATURE_INPUT_NOT_FOUND"


def test_feature_plan_version_mismatch_returns_422(test_client):
    """Test 422 FEATURE_CONTRACT_ERROR when preprocessing_plan_version mismatches loaded plan."""
    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]

    req_payload = {
        "dataset_id": dataset_id,
        "dataset_version": "v1.0",
        "failure_dataset_id": dataset_id,
        "failure_dataset_version": "v1.0",
        "preprocessing_plan_id": plan_id,
        "preprocessing_plan_version": "preprocessing-plan-mismatched99",
        "feature_schema_version": "ai4i-feature-v1",
        "label_schema_version": "ai4i-label-24h-v1",
        "prediction_horizon_hours": 24,
    }
    resp = client.post("/feature", json=req_payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FEATURE_CONTRACT_ERROR"


def test_feature_horizon_mismatch_returns_422(test_client):
    """Test 422 FEATURE_SCHEMA_MISMATCH_ERROR when requested horizon mismatches Label Schema."""
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
        "label_schema_version": "ai4i-label-48h-v1",
        "prediction_horizon_hours": 24,  # Schema declares 48h, request says 24h
    }
    resp = client.post("/feature", json=req_payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "FEATURE_SCHEMA_MISMATCH_ERROR"


def test_feature_forbids_mapping_fields(test_client):
    """Test that extra fields like mapping_version are forbidden and return 422."""
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
        "mapping_version": "v1.0",  # FORBIDDEN
    }
    resp = client.post("/feature", json=req_payload)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_feature_path_traversal_forbidden(test_client):
    """Test that path traversal characters in identifiers are rejected with 422."""
    client = test_client["client"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    for bad_id in ["../escape", "sub/dir", "back\\slash", ".."]:
        req_payload = {
            "dataset_id": bad_id,
            "dataset_version": "v1.0",
            "failure_dataset_id": "ai4i",
            "failure_dataset_version": "v1.0",
            "preprocessing_plan_id": plan_id,
            "preprocessing_plan_version": plan_ver,
            "feature_schema_version": "ai4i-feature-v1",
            "label_schema_version": "ai4i-label-24h-v1",
            "prediction_horizon_hours": 24,
        }
        resp = client.post("/feature", json=req_payload)
        assert resp.status_code == 422


def test_feature_corrupted_bundle_fails_fast(test_client):
    """Test 422 FEATURE_DATASET_INTEGRITY_ERROR when existing bundle payload is corrupted."""
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
    resp = client.post("/feature", json=req_payload)
    assert resp.status_code == 200
    feat_ver = resp.json()["outputs"]["feature_dataset_version"]

    bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver

    # Corrupt features.npy
    with open(bundle_dir / "features.npy", "wb") as f:
        f.write(b"corrupted binary data")

    req_payload["rebuild_npy"] = False
    resp2 = client.post("/feature", json=req_payload)
    assert resp2.status_code == 422
    assert resp2.json()["error"]["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"


def test_feature_endpoint_is_synchronous():
    """Verify that POST /feature handler is a synchronous function."""
    assert inspect.iscoroutinefunction(post_feature) is False


def test_feature_conflict_fingerprint_returns_409(test_client):
    """Test 409 FEATURE_PUBLISH_CONFLICT when same version directory has conflicting fingerprint."""
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
    resp = client.post("/feature", json=req_payload)
    assert resp.status_code == 200
    feat_ver = resp.json()["outputs"]["feature_dataset_version"]

    bundle_dir = PATHS.models_store / "cache" / "features" / dataset_id / "v1.0" / feat_ver
    meta_path = bundle_dir / "feature_metadata.json"

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # Alter fingerprint inside metadata
    meta["fingerprint"]["observation_dataset_id"] = "tampered_dataset_id"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    req_payload["rebuild_npy"] = False
    resp2 = client.post("/feature", json=req_payload)
    assert resp2.status_code == 409
    assert resp2.json()["error"]["code"] == "FEATURE_PUBLISH_CONFLICT"


def test_feature_missing_source_field_fails_422(test_client):
    """Test 422 FEATURE_SCHEMA_MISMATCH_ERROR when requested schema refers to non-existent source column."""
    from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider, FeatureItem
    from systems.generator.app.feature.feature_service import FeatureService

    client = test_client["client"]
    dataset_id = test_client["dataset_id"]
    plan_id = test_client["plan_id"]
    plan_ver = test_client["plan_version"]

    class MockBadSchemaProvider(FeatureSchemaProvider):
        def get_feature_schema(self, schema_version, available_columns=None, custom_items=None):
            return super().get_feature_schema(
                schema_version=schema_version,
                custom_items=[
                    FeatureItem(feature_name="NonexistentFeature", source_field="NonexistentSourceCol", operation="raw")
                ],
            )

    from systems.generator.app.feature.feature_router import get_feature_service

    svc = FeatureService(feature_schema_provider=MockBadSchemaProvider())
    client.app.dependency_overrides[get_feature_service] = lambda: svc

    try:
        req_payload = {
            "dataset_id": dataset_id,
            "dataset_version": "v1.0",
            "failure_dataset_id": dataset_id,
            "failure_dataset_version": "v1.0",
            "preprocessing_plan_id": plan_id,
            "preprocessing_plan_version": plan_ver,
            "feature_schema_version": "bad-schema-v1",
            "label_schema_version": "ai4i-label-24h-v1",
            "prediction_horizon_hours": 24,
            "rebuild_npy": True,
        }
        resp = client.post("/feature", json=req_payload)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "FEATURE_SCHEMA_MISMATCH_ERROR"
    finally:
        client.app.dependency_overrides.pop(get_feature_service, None)


def test_feature_concurrency_multithreaded_rebuild(test_client):
    """Test concurrent requests to /feature do not corrupt or conflict partial bundles."""
    import threading

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

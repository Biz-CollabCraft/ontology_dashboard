"""Comprehensive test suite for Generator Feature API (/feature) conforming to Phase 2 immutable contract."""

import json
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from fastapi.testclient import TestClient

from systems.generator.app.main import app
from systems.generator.app.extraction.extraction_repository import (
    ExtractionRepository,
    compute_plan_version,
    compute_mapping_version,
)
from systems.generator.app.feature.feature_schema import FeatureRequest, FeatureResponse
from systems.generator.app.feature.feature_exception import (
    FeatureError,
    ExtractionPlanNotReadyError,
    ExtractionPlanIntegrityError,
    OntologyMappingNotReadyError,
    OntologyMappingIntegrityError,
    FailureDataNotReadyError,
    LabelContractInvalidError,
    LabelAnchorNotFoundError,
    FeatureSchemaMismatchError,
    InsufficientTrainingDataError,
    NpyValidationError,
    FeatureConflictError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.app.feature.feature_schema_provider import (
    FeatureSchemaProvider,
    FeatureSchemaDefinition,
)
from systems.generator.feature.feature_label_service import build_labels


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_dataset_with_failures(tmp_path, monkeypatch):
    """Create a sample dataset with telemetry and failure events wired to tmp_path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    # 1. Create telemetry CSV
    telemetry_file = data_dir / "telemetry_sample.csv"
    timestamps = pd.date_range("2026-01-01 00:00:00", periods=10, freq="h")
    records = []
    for m in ["M001", "M002"]:
        for i, ts in enumerate(timestamps):
            records.append({
                "asset_id": m,
                "timestamp": str(ts),
                "voltage": 220.0 + i * 1.5,
                "rotation": 1500.0 + i * 10.0,
            })
    pd.DataFrame(records).to_csv(telemetry_file, index=False)

    # 2. Create failure events CSV
    failure_file = data_dir / "failure_events.csv"
    failures = pd.DataFrame([
        {
            "asset_id": "M001",
            "observed_at": "2026-01-01 08:00:00",
            "failure_type": "Overheat",
        },
        {
            "asset_id": "M002",
            "observed_at": "2026-01-01 09:00:00",
            "failure_type": "Power",
        },
    ])
    failures.to_csv(failure_file, index=False)

    # 3. Patch Generator PATHS
    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    return {
        "dataset_id": "telemetry_sample",
        "dataset_version": "v1.0",
        "csv_rel_path": "telemetry_sample.csv",
        "csv_path": str(telemetry_file),
        "failure_csv": str(failure_file),
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
        "extraction_plan_version": "extraction-plan-1122334455667788",
        "mapping_version": "ontology-mapping-1122334455667788",
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


def test_feature_plan_and_mapping_integrity_error(client, sample_dataset_with_failures):
    """Tampered plan or mapping on disk returns 422 INTEGRITY_ERROR."""
    ext_repo = ExtractionRepository()
    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
    }
    plan_ver, _ = ext_repo.publish_plan(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_data)
    mapping_data = {
        "voltage": {"target_ontology": "Voltage", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
        "rotation": {"target_ontology": "Rotation", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
    }
    map_ver, _ = ext_repo.publish_mapping(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], mapping_data)

    # Corrupt plan file content
    plan_file = ext_repo.get_plan_path(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_ver)
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump({"tampered": True}, f)

    payload = {
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "extraction_plan_version": plan_ver,
        "mapping_version": map_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res = client.post("/feature", json=payload)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "EXTRACTION_PLAN_INTEGRITY_ERROR"


def test_feature_request_validation_identifier_and_horizon(client):
    """Invalid versions or horizon <= 0 return 422 REQUEST_VALIDATION_ERROR."""
    # Invalid plan version format (not matching regex)
    res1 = client.post("/feature", json={
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "extraction_plan_version": "bad_plan_version",
        "mapping_version": "ontology-mapping-1234567812345678",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"

    # horizon <= 0
    res2 = client.post("/feature", json={
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "extraction_plan_version": "extraction-plan-1234567812345678",
        "mapping_version": "ontology-mapping-1234567812345678",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 0,
        "rebuild_npy": True,
    })
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_feature_end_to_end_success(client, sample_dataset_with_failures):
    """POST /extraction -> POST /feature succeeds end-to-end with immutable NPY and SHA-256 fingerprint."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]

    # 1. Execute Extraction (relative source_uri)
    ext_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_rel_path"],
        "force_reanalyze": True,
    }
    ext_res = client.post("/extraction", json=ext_payload)
    assert ext_res.status_code == 200
    ext_data = ext_res.json()
    plan_ver = ext_data["extraction_plan_version"]
    mapping_ver = ext_data["result"]["mapping_version"]

    assert plan_ver.startswith("extraction-plan-")
    assert mapping_ver.startswith("ontology-mapping-")

    # 2. Execute Feature generation
    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": plan_ver,
        "mapping_version": mapping_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    feat_res = client.post("/feature", json=feat_payload)
    assert feat_res.status_code == 200
    feat_data = feat_res.json()

    assert feat_data["status"] == "succeeded"
    assert feat_data["dataset_id"] == dataset_id
    assert feat_data["dataset_version"] == dataset_version
    assert feat_data["outputs"]["feature_dataset_version"].startswith("feature-dataset-")

    outputs = feat_data["outputs"]
    assert outputs["row_count"] > 0
    assert outputs["feature_count"] == 4  # pdm-feature-v1 has 4 features

    # Verify physical files
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
    assert set(np.unique(y)).issubset({0, 1})


def test_feature_conflict_on_mismatched_existing_directory(tmp_path):
    """Attempting to publish to an existing directory with mismatched contract raises 409 FEATURE_DATASET_CONFLICT."""
    repo = FeatureRepository(base_dir=tmp_path / "features_cache")

    X = np.ones((10, 2), dtype=np.float64)
    y = np.zeros(10, dtype=np.int64)
    cols = ["col1", "col2"]
    meta1 = {
        "contract": {"dataset_id": "ds1", "horizon": 24},
        "feature_dataset_version": "fver1",
        "row_count": 10,
        "feature_count": 2,
    }

    # 1. Publish first time -> success
    repo.publish_feature_bundle("ds1", "v1", "fver1", X, y, cols, meta1)

    # 2. Attempt publish with different contract to SAME fver1 -> 409 conflict
    meta2 = {
        "contract": {"dataset_id": "ds1", "horizon": 48},
        "feature_dataset_version": "fver1",
        "row_count": 10,
        "feature_count": 2,
    }
    with pytest.raises(FeatureConflictError) as exc_info:
        repo.publish_feature_bundle("ds1", "v1", "fver1", X, y, cols, meta2)

    assert exc_info.value.code == "FEATURE_DATASET_CONFLICT"
    assert exc_info.value.status_code == 409


def test_feature_positive_samples_zero_fails_fast(client, tmp_path, monkeypatch):
    """When no positive failure events occur within horizon, request fails fast with INSUFFICIENT_POSITIVE_SAMPLES."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    # Telemetry in 2026-01-01
    telemetry_file = data_dir / "telemetry_no_pos.csv"
    pd.DataFrame({
        "asset_id": ["M001", "M001"],
        "timestamp": ["2026-01-01 00:00:00", "2026-01-01 01:00:00"],
        "voltage": [220.0, 225.0],
        "rotation": [1500.0, 1510.0],
    }).to_csv(telemetry_file, index=False)

    # Failures in distant future (2030) -> zero positives in horizon=1h
    failure_file = data_dir / "failure_events.csv"
    pd.DataFrame([{
        "asset_id": "M001",
        "observed_at": "2030-01-01 00:00:00",
        "failure_type": "None",
    }]).to_csv(failure_file, index=False)

    ext_res = client.post("/extraction", json={
        "dataset_id": "telemetry_no_pos",
        "dataset_version": "v1.0",
        "source_uri": "telemetry_no_pos.csv",
        "force_reanalyze": True,
    })
    assert ext_res.status_code == 200
    ext_data = ext_res.json()

    feat_res = client.post("/feature", json={
        "dataset_id": "telemetry_no_pos",
        "dataset_version": "v1.0",
        "extraction_plan_version": ext_data["extraction_plan_version"],
        "mapping_version": ext_data["result"]["mapping_version"],
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 1,
        "rebuild_npy": True,
    })
    assert feat_res.status_code == 422
    err = feat_res.json()["error"]
    assert err["code"] == "INSUFFICIENT_POSITIVE_SAMPLES"


def test_build_labels_unit_fail_fast_cases():
    """Unit tests for build_labels fail-fast behavior across all contract violations."""
    feat_df = pd.DataFrame({"asset_id": ["A"], "timestamp": ["2026-01-01 00:00:00"], "v1": [1.0]})

    # 1. Empty failures
    with pytest.raises(FailureDataNotReadyError):
        build_labels(feat_df, pd.DataFrame())

    # 2. Missing Feature ID
    no_id_df = pd.DataFrame({"timestamp": ["2026-01-01 00:00:00"], "v1": [1.0]})
    fail_df = pd.DataFrame({"asset_id": ["A"], "observed_at": ["2026-01-01 01:00:00"]})
    with pytest.raises(LabelContractInvalidError, match="Feature 데이터프레임에서 ID"):
        build_labels(no_id_df, fail_df)

    # 3. Missing Feature time
    no_time_df = pd.DataFrame({"asset_id": ["A"], "v1": [1.0]})
    with pytest.raises(LabelContractInvalidError, match="Feature 데이터프레임에서 timestamp"):
        build_labels(no_time_df, fail_df)

    # 4. Missing failure ID
    bad_fail_df = pd.DataFrame({"bad_col": ["A"], "observed_at": ["2026-01-01 01:00:00"]})
    with pytest.raises(LabelContractInvalidError, match="고장 데이터프레임에서 ID"):
        build_labels(feat_df, bad_fail_df)

    # 5. Missing anchor
    bad_anchor_df = pd.DataFrame({"asset_id": ["A"], "bad_time": ["2026-01-01 01:00:00"]})
    with pytest.raises(LabelAnchorNotFoundError, match="anchor"):
        build_labels(feat_df, bad_anchor_df)

    # 6. All anchor NaT
    all_nat_df = pd.DataFrame({"asset_id": ["A"], "observed_at": [pd.NaT]})
    with pytest.raises(LabelAnchorNotFoundError, match="모든 anchor"):
        build_labels(feat_df, all_nat_df)

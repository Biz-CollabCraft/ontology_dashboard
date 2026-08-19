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


def test_feature_request_validation_errors(client):
    """Validation errors for horizon <= 0 and rebuild_npy=False return 422 REQUEST_VALIDATION_ERROR."""
    # horizon <= 0
    payload_bad_horizon = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "extraction_plan_version": "extraction-plan-1234567812345678",
        "mapping_version": "ontology-mapping-1234567812345678",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 0,
        "rebuild_npy": True,
    }
    res1 = client.post("/feature", json=payload_bad_horizon)
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"

    # rebuild_npy = False
    payload_bad_rebuild = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "extraction_plan_version": "extraction-plan-1234567812345678",
        "mapping_version": "ontology-mapping-1234567812345678",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": False,
    }
    res2 = client.post("/feature", json=payload_bad_rebuild)
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_feature_end_to_end_success(client, sample_dataset_with_failures):
    """POST /extraction -> POST /feature succeeds end-to-end with immutable NPY and SHA-256 fingerprint."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]

    # 1. Execute Extraction (generates plan and mapping)
    ext_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_path"],
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
    assert meta["feature_columns"] == [
        "voltage__Voltage__rolling_mean__window_5",
        "voltage__Voltage__rolling_std__window_5",
        "rotation__Rotation__rolling_mean__window_5",
        "rotation__Rotation__gradient__default",
    ]
    assert set(np.unique(y)).issubset({0, 1})


def test_feature_fingerprint_propagation(client, sample_dataset_with_failures):
    """Changing plan, mapping, schema, or horizon changes feature_dataset_version fingerprint."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]

    ext_res = client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_path"],
        "force_reanalyze": True,
    })
    ext_data = ext_res.json()
    plan_ver = ext_data["extraction_plan_version"]
    mapping_ver = ext_data["result"]["mapping_version"]

    # Run 1: horizon=24
    res1 = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": plan_ver,
        "mapping_version": mapping_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    fver1 = res1.json()["outputs"]["feature_dataset_version"]

    # Run 2: horizon=48
    res2 = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": plan_ver,
        "mapping_version": mapping_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 48,
        "rebuild_npy": True,
    })
    fver2 = res2.json()["outputs"]["feature_dataset_version"]

    assert fver1 != fver2, "Changing prediction_horizon_hours must produce distinct feature_dataset_version fingerprint"


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
        "contract": {"dataset_id": "ds1", "horizon": 48},  # conflicting contract
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
        "source_uri": str(telemetry_file),
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


def test_feature_ignores_preexisting_label_and_uses_failure_dataset(client, sample_dataset_with_failures):
    """Telemetry with existing label column does not bypass official horizon labeling."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]

    # Overwrite telemetry CSV to include a fake preexisting label column with all 9s
    raw_df = pd.read_csv(sample_dataset_with_failures["csv_path"])
    raw_df["label"] = 9
    raw_df.to_csv(sample_dataset_with_failures["csv_path"], index=False)

    ext_res = client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_path"],
        "force_reanalyze": True,
    })
    ext_data = ext_res.json()

    feat_res = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": ext_data["extraction_plan_version"],
        "mapping_version": ext_data["result"]["mapping_version"],
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert feat_res.status_code == 200
    feat_data = feat_res.json()

    # Load output labels.npy and verify labels are strictly {0, 1}, not 9
    from systems.generator.generator_config import PATHS
    repo_root = PATHS.models_store.parent
    y = np.load(repo_root / feat_data["outputs"]["labels_uri"])
    assert set(np.unique(y)).issubset({0, 1})
    assert (y == 1).sum() > 0


def test_feature_schema_leakage_columns_rejected(tmp_path):
    """FeatureSchemaProvider rejects schemas containing metadata or target leakage columns."""
    provider = FeatureSchemaProvider(schemas_dir=tmp_path)
    bad_schema = FeatureSchemaDefinition(
        feature_schema_version="bad-leakage-v1",
        feature_names=["voltage__Voltage__rolling_mean__window_5", "asset_id"],
    )
    provider.register_schema(bad_schema)

    df = pd.DataFrame({"voltage__Voltage__rolling_mean__window_5": [1.0, 2.0], "asset_id": ["A", "B"]})
    plan = {"id_column": "asset_id", "time_column": "observed_at"}

    with pytest.raises(FeatureSchemaMismatchError, match="금지된 메타/누수 컬럼"):
        provider.validate_and_filter_features("bad-leakage-v1", df, plan)


def test_repository_immutable_publish_and_validation(tmp_path):
    """FeatureRepository validates shapes, dtypes, values, and cleans up staging on error."""
    repo = FeatureRepository(base_dir=tmp_path / "features_cache")

    X = np.ones((10, 2), dtype=np.float64)
    y = np.zeros(10, dtype=np.int64)
    cols = ["col1", "col2"]
    meta = {
        "contract": {"dataset_id": "ds1"},
        "feature_dataset_version": "fver1",
        "row_count": 10,
        "feature_count": 2,
    }

    # 1. Success
    uris = repo.publish_feature_bundle("ds1", "v1", "fver1", X, y, cols, meta)
    assert (tmp_path / "features_cache" / "ds1-v1-fver1" / "features.npy").exists()

    # 2. y value outside {0, 1}
    y_invalid = np.array([0, 1, 2, 0, 1, 0, 1, 0, 1, 0], dtype=np.int64)
    with pytest.raises(NpyValidationError, match="outside {0, 1}"):
        repo.publish_feature_bundle("ds1", "v1", "fver2", X, y_invalid, cols, meta)

    # 3. NaN in X
    X_nan = X.copy()
    X_nan[0, 0] = np.nan
    with pytest.raises(NpyValidationError, match="contains NaN"):
        repo.publish_feature_bundle("ds1", "v1", "fver3", X_nan, y, cols, meta)

    # Ensure no leftover temp directories
    temp_dirs = list((tmp_path / "features_cache").glob(".tmp_*"))
    assert len(temp_dirs) == 0


def test_feature_does_not_call_map_all_sources(client, sample_dataset_with_failures, monkeypatch):
    """POST /feature does NOT call map_all_sources and only reads existing mapping."""
    import systems.generator.ontology_mapping.mapping_agent as ma

    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]

    ext_res = client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_path"],
        "force_reanalyze": True,
    })
    ext_data = ext_res.json()

    call_count = {"count": 0}
    orig_map = ma.map_all_sources
    def spy_map(*args, **kwargs):
        call_count["count"] += 1
        return orig_map(*args, **kwargs)
    monkeypatch.setattr(ma, "map_all_sources", spy_map)

    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": ext_data["extraction_plan_version"],
        "mapping_version": ext_data["result"]["mapping_version"],
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res = client.post("/feature", json=feat_payload)
    assert res.status_code == 200
    assert call_count["count"] == 0, "POST /feature must not call map_all_sources!"


def test_feature_missing_failure_data_fails_fast(client, tmp_path, monkeypatch):
    """POST /feature without matching failure dataset returns 404 FAILURE_DATA_NOT_READY."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    telemetry_file = data_dir / "telemetry_lonely.csv"
    pd.DataFrame({
        "asset_id": ["M001", "M001"],
        "timestamp": ["2026-01-01 00:00:00", "2026-01-01 01:00:00"],
        "voltage": [220.0, 225.0],
        "rotation": [1500.0, 1510.0],
    }).to_csv(telemetry_file, index=False)

    ext_res = client.post("/extraction", json={
        "dataset_id": "telemetry_lonely",
        "dataset_version": "v1.0",
        "source_uri": str(telemetry_file),
        "force_reanalyze": True,
    })
    assert ext_res.status_code == 200
    ext_data = ext_res.json()

    feat_res = client.post("/feature", json={
        "dataset_id": "telemetry_lonely",
        "dataset_version": "v1.0",
        "extraction_plan_version": ext_data["extraction_plan_version"],
        "mapping_version": ext_data["result"]["mapping_version"],
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert feat_res.status_code == 404
    assert feat_res.json()["error"]["code"] == "FAILURE_DATA_NOT_READY"

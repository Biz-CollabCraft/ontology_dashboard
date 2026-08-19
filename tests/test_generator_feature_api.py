"""Comprehensive test suite for Generator Feature API (/feature) conforming to Phase 2 contract."""

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
    OntologyMappingNotReadyError,
    OntologyMappingVersionMismatchError,
    FailureDataNotReadyError,
    LabelContractInvalidError,
    FeatureSchemaMismatchError,
    NpyValidationError,
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
        "extraction_plan_version": "extraction-plan-unextracted_dataset-v1.0",
        "mapping_version": "mapping-unextracted_dataset-v1.0",
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


def test_feature_extraction_plan_version_mismatch(client, sample_dataset_with_failures):
    """POST /feature with mismatched extraction_plan_version returns 422 EXTRACTION_PLAN_VERSION_MISMATCH."""
    ext_repo = ExtractionRepository()
    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
    }
    ext_repo.publish_plan(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_data, overwrite=True)

    payload = {
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "extraction_plan_version": "extraction-plan-wrong-version",
        "mapping_version": "mapping-telemetry_sample-v1.0",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res = client.post("/feature", json=payload)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "EXTRACTION_PLAN_VERSION_MISMATCH"


def test_feature_ontology_mapping_not_ready(client, sample_dataset_with_failures):
    """POST /feature without an existing Ontology Mapping returns 404 ONTOLOGY_MAPPING_NOT_READY."""
    ext_repo = ExtractionRepository()
    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
    }
    ext_repo.publish_plan(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_data, overwrite=True)

    payload = {
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "extraction_plan_version": f"extraction-plan-{sample_dataset_with_failures['dataset_id']}-{sample_dataset_with_failures['dataset_version']}",
        "mapping_version": f"mapping-{sample_dataset_with_failures['dataset_id']}-{sample_dataset_with_failures['dataset_version']}",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res = client.post("/feature", json=payload)
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "ONTOLOGY_MAPPING_NOT_READY"


def test_feature_ontology_mapping_version_mismatch(client, sample_dataset_with_failures):
    """POST /feature with mismatched mapping_version returns 422 ONTOLOGY_MAPPING_VERSION_MISMATCH."""
    ext_repo = ExtractionRepository()
    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
    }
    ext_repo.publish_plan(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_data, overwrite=True)
    mapping_data = {
        "voltage": {"target_ontology": "Voltage", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"}
    }
    ext_repo.publish_mapping(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], mapping_data, overwrite=True)

    payload = {
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "extraction_plan_version": f"extraction-plan-{sample_dataset_with_failures['dataset_id']}-{sample_dataset_with_failures['dataset_version']}",
        "mapping_version": "mapping-wrong-version-xyz",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res = client.post("/feature", json=payload)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "ONTOLOGY_MAPPING_VERSION_MISMATCH"


def test_feature_request_validation_errors(client):
    """Validation errors for horizon <= 0 and rebuild_npy=False return 422 REQUEST_VALIDATION_ERROR."""
    # horizon <= 0
    payload_bad_horizon = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "extraction_plan_version": "extraction-plan-ds1-v1",
        "mapping_version": "mapping-ds1-v1",
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
        "extraction_plan_version": "extraction-plan-ds1-v1",
        "mapping_version": "mapping-ds1-v1",
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
        "force": False,
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


def test_feature_contract_fingerprint_cache_invalidation(client, sample_dataset_with_failures):
    """Changing horizon or schema version changes SHA-256 fingerprint and creates new immutable dataset."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]

    client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_path"],
        "force_reanalyze": True,
    })

    plan_ver = f"extraction-plan-{dataset_id}-{dataset_version}"
    mapping_ver = f"mapping-{dataset_id}-{dataset_version}"

    # Run 1 with horizon=24
    res1 = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": plan_ver,
        "mapping_version": mapping_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
        "force": False,
    })
    fver1 = res1.json()["outputs"]["feature_dataset_version"]

    # Run 2 with horizon=48
    res2 = client.post("/feature", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": plan_ver,
        "mapping_version": mapping_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 48,
        "rebuild_npy": True,
        "force": False,
    })
    fver2 = res2.json()["outputs"]["feature_dataset_version"]

    assert fver1 != fver2, "Changing prediction_horizon_hours must produce distinct feature_dataset_version fingerprint"


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
    meta = {"row_count": 10, "feature_count": 2}

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

    # First run extraction to produce plan and mapping
    client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_path"],
        "force_reanalyze": True,
    })

    # Spy on map_all_sources during /feature
    call_count = {"count": 0}
    orig_map = ma.map_all_sources
    def spy_map(*args, **kwargs):
        call_count["count"] += 1
        return orig_map(*args, **kwargs)
    monkeypatch.setattr(ma, "map_all_sources", spy_map)

    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extraction_plan_version": f"extraction-plan-{dataset_id}-{dataset_version}",
        "mapping_version": f"mapping-{dataset_id}-{dataset_version}",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
        "force": False,
    }
    res = client.post("/feature", json=feat_payload)
    assert res.status_code == 200
    assert call_count["count"] == 0, "POST /feature must not call map_all_sources!"


def test_extraction_mapping_failure_fails_fast(client, sample_dataset_with_failures, monkeypatch):
    """If ontology mapping fails during POST /extraction, request must fail fast and not return 200."""
    import systems.generator.ontology_mapping.mapping_agent as ma
    def mock_broken_map(*args, **kwargs):
        raise RuntimeError("Simulated ontology mapping LLM connection crash")
    monkeypatch.setattr(ma, "map_all_sources", mock_broken_map)

    payload = {
        "dataset_id": "mapping_fail_ds",
        "dataset_version": "v1.0",
        "source_uri": sample_dataset_with_failures["csv_path"],
        "force_reanalyze": True,
    }
    res = client.post("/extraction", json=payload)
    assert res.status_code in (422, 500)
    assert res.json()["error"]["code"] in ("EXTRACTION_PLAN_PUBLISH_ERROR", "INTERNAL_SERVER_ERROR")


def test_feature_missing_failure_data_fails_fast(client, tmp_path, monkeypatch):
    """POST /feature without matching failure dataset returns 404 FAILURE_DATA_NOT_READY."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    # Telemetry only, NO failure data
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

    feat_res = client.post("/feature", json={
        "dataset_id": "telemetry_lonely",
        "dataset_version": "v1.0",
        "extraction_plan_version": "extraction-plan-telemetry_lonely-v1.0",
        "mapping_version": "mapping-telemetry_lonely-v1.0",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert feat_res.status_code == 404
    assert feat_res.json()["error"]["code"] == "FAILURE_DATA_NOT_READY"

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
    LabelSchemaMismatchError,
    InsufficientTrainingDataError,
    NpyValidationError,
    FeatureConflictError,
    FeatureDatasetIntegrityError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.app.feature.feature_schema_provider import (
    FeatureSchemaProvider,
    FeatureSchemaDefinition,
)
from systems.generator.app.feature.label_schema_provider import (
    LabelSchemaProvider,
    LabelSchemaDefinition,
)
from systems.generator.app.feature.feature_service import (
    FeatureService,
    compute_feature_dataset_version,
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
    failure_file = data_dir / "sample_failures.csv"
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
        "failure_dataset_id": "sample_failures",
        "failure_dataset_version": "v1.0",
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
        "failure_dataset_id": "unextracted_failures",
        "failure_dataset_version": "v1.0",
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


def test_feature_label_schema_validation_failure(client, sample_dataset_with_failures):
    """POST /feature with invalid or mismatched label schema fails fast with LABEL_SCHEMA_MISMATCH."""
    # 1. Non-existent schema
    payload_missing = {
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "failure_dataset_id": sample_dataset_with_failures["failure_dataset_id"],
        "failure_dataset_version": sample_dataset_with_failures["failure_dataset_version"],
        "extraction_plan_version": "extraction-plan-1122334455667788",
        "mapping_version": "ontology-mapping-1122334455667788",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "non_existent_label_schema",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    res1 = client.post("/feature", json=payload_missing)
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "LABEL_SCHEMA_MISMATCH"

    # 2. Horizon mismatch (pdm-label-v1 has horizon=24, request asks 12)
    payload_horizon = {
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "failure_dataset_id": sample_dataset_with_failures["failure_dataset_id"],
        "failure_dataset_version": sample_dataset_with_failures["failure_dataset_version"],
        "extraction_plan_version": "extraction-plan-1122334455667788",
        "mapping_version": "ontology-mapping-1122334455667788",
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 12,
        "rebuild_npy": True,
    }
    res2 = client.post("/feature", json=payload_horizon)
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "LABEL_SCHEMA_MISMATCH"


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
        json.dump({"tampered": True, "structure_type": "tabular_column_as_attribute", "selected_columns": []}, f)

    payload = {
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "failure_dataset_id": sample_dataset_with_failures["failure_dataset_id"],
        "failure_dataset_version": sample_dataset_with_failures["failure_dataset_version"],
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


def test_feature_end_to_end_and_reuse_integrity(client, sample_dataset_with_failures):
    """POST /extraction -> POST /feature succeeds end-to-end and verifies feature bundle reuse integrity."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]
    failure_id = sample_dataset_with_failures["failure_dataset_id"]
    failure_ver = sample_dataset_with_failures["failure_dataset_version"]

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

    # 2. Execute Feature generation first time
    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "failure_dataset_id": failure_id,
        "failure_dataset_version": failure_ver,
        "extraction_plan_version": plan_ver,
        "mapping_version": mapping_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    feat_res1 = client.post("/feature", json=feat_payload)
    assert feat_res1.status_code == 200
    feat_data1 = feat_res1.json()
    fver1 = feat_data1["outputs"]["feature_dataset_version"]
    assert fver1.startswith("feature-dataset-")

    # 3. Second call with exact same parameters -> reuses bundle successfully
    feat_res2 = client.post("/feature", json=feat_payload)
    assert feat_res2.status_code == 200
    assert feat_res2.json()["outputs"]["feature_dataset_version"] == fver1

    # 4. Tamper with features.npy on disk -> next call fails fast with FEATURE_DATASET_INTEGRITY_ERROR
    from systems.generator.generator_config import PATHS
    repo_root = PATHS.models_store.parent
    features_path = repo_root / feat_data1["outputs"]["features_uri"]
    with open(features_path, "wb") as f:
        f.write(b"not a valid npy file header")

    feat_res3 = client.post("/feature", json=feat_payload)
    assert feat_res3.status_code == 422
    assert feat_res3.json()["error"]["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"


def test_feature_bundle_validation_exhaustive(tmp_path):
    """Exhaustive test for validate_feature_bundle checking all integrity violations."""
    repo = FeatureRepository(base_dir=tmp_path / "features_cache")

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
    fver = compute_feature_dataset_version(**contract)
    target_dir = repo.get_feature_dir("ds1", "v1", fver)

    X = np.ones((5, 2), dtype=np.float64)
    y = np.array([0, 1, 0, 1, 0], dtype=np.int64)
    cols = ["col1", "col2"]
    meta = {
        "contract": contract,
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "feature_dataset_version": fver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "feature_columns": cols,
        "row_count": 5,
        "feature_count": 2,
    }

    # 1. Normal publish
    repo.publish_feature_bundle("ds1", "v1", fver, X, y, cols, meta)
    validated = repo.validate_feature_bundle("ds1", "v1", fver, contract)
    assert validated["row_count"] == 5

    # 2. Missing labels.npy
    (target_dir / "labels.npy").unlink()
    with pytest.raises(FeatureDatasetIntegrityError, match="필수 파일이 누락"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)
    np.save(target_dir / "labels.npy", y)

    # 3. Shape / byte mismatch (modified labels.npy triggers checksum mismatch)
    np.save(target_dir / "labels.npy", np.array([0, 1], dtype=np.int64))
    with pytest.raises(FeatureDatasetIntegrityError, match="체크섬이 일치하지 않습니다"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)
    np.save(target_dir / "labels.npy", y)

    # 4. Modified features.npy (triggers checksum mismatch)
    X_nan = np.copy(X)
    X_nan[0, 0] = 999.0
    np.save(target_dir / "features.npy", X_nan)
    with pytest.raises(FeatureDatasetIntegrityError, match="체크섬이 일치하지 않습니다"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)
    np.save(target_dir / "features.npy", X)

    # 5. Invalid label value (triggers checksum mismatch)
    np.save(target_dir / "labels.npy", np.array([0, 5, 0, 1, 0], dtype=np.int64))
    with pytest.raises(FeatureDatasetIntegrityError, match="체크섬이 일치하지 않습니다"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)
    np.save(target_dir / "labels.npy", y)


def test_failure_dataset_explicit_association_and_fingerprint_change(client, tmp_path, monkeypatch):
    """Explicit failure dataset connection and changing failure version produces different feature dataset version."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    # 1. Telemetry data
    pd.DataFrame({
        "asset_id": ["A1", "A1", "A2", "A2"],
        "timestamp": ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 00:00:00", "2026-01-01 01:00:00"],
        "voltage": [220.0, 222.0, 221.0, 225.0],
        "rotation": [1500.0, 1510.0, 1505.0, 1515.0],
    }).to_csv(data_dir / "telem.csv", index=False)

    # 2. Failure dataset v1
    pd.DataFrame([{
        "asset_id": "A1",
        "observed_at": "2026-01-01 01:30:00",
        "failure_type": "Overheat",
    }]).to_csv(data_dir / "failures_v1.csv", index=False)

    # 3. Failure dataset v2
    pd.DataFrame([{
        "asset_id": "A2",
        "observed_at": "2026-01-01 01:30:00",
        "failure_type": "Vibration",
    }]).to_csv(data_dir / "failures_v2.csv", index=False)

    # 4. Incompatible Failure dataset (different asset ID scheme)
    pd.DataFrame([{
        "asset_id": "CAR_999",
        "observed_at": "2026-01-01 01:30:00",
        "failure_type": "Engine",
    }]).to_csv(data_dir / "failures_incompat.csv", index=False)

    ext_res = client.post("/extraction", json={
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "source_uri": "telem.csv",
        "force_reanalyze": True,
    })
    assert ext_res.status_code == 200
    ext_data = ext_res.json()
    p_ver = ext_data["extraction_plan_version"]
    m_ver = ext_data["result"]["mapping_version"]

    # Run with failures_v1
    res1 = client.post("/feature", json={
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "failure_dataset_id": "failures_v1",
        "failure_dataset_version": "v1.0",
        "extraction_plan_version": p_ver,
        "mapping_version": m_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res1.status_code == 200
    fver1 = res1.json()["outputs"]["feature_dataset_version"]

    # Run with failures_v2 -> must produce DIFFERENT feature_dataset_version
    res2 = client.post("/feature", json={
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "failure_dataset_id": "failures_v2",
        "failure_dataset_version": "v2.0",
        "extraction_plan_version": p_ver,
        "mapping_version": m_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res2.status_code == 200
    fver2 = res2.json()["outputs"]["feature_dataset_version"]
    assert fver1 != fver2

    # Run with incompatible failure dataset -> fails fast with 422 LABEL_CONTRACT_INVALID
    res_incompat = client.post("/feature", json={
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "failure_dataset_id": "failures_incompat",
        "failure_dataset_version": "v1.0",
        "extraction_plan_version": p_ver,
        "mapping_version": m_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res_incompat.status_code == 422
    assert res_incompat.json()["error"]["code"] == "LABEL_CONTRACT_INVALID"

    # Run with non-existent failure dataset -> fails with 404 FAILURE_DATA_NOT_READY
    res_missing = client.post("/feature", json={
        "dataset_id": "telem",
        "dataset_version": "v1.0",
        "failure_dataset_id": "non_existent_failure_dataset",
        "failure_dataset_version": "v1.0",
        "extraction_plan_version": p_ver,
        "mapping_version": m_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res_missing.status_code == 404
    assert res_missing.json()["error"]["code"] == "FAILURE_DATA_NOT_READY"

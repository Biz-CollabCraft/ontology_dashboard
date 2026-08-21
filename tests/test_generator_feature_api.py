"""Comprehensive test suite for Generator Feature API (/feature) conforming to Phase 2 immutable contract."""

import json
import re
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
    SourceDatasetIntegrityError,
    SourceDatasetVersionMismatchError,
    FailureDatasetVersionMismatchError,
    TrainingSplitMetadataMissingError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository, ALLOWED_FEATURE_BUNDLE_FILES, compute_file_sha256
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

    # 2. Create failure events CSV in versioned path
    failure_file = data_dir / "sample_failures" / "v1.0.csv"
    failure_file.parent.mkdir(parents=True, exist_ok=True)
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
    sensor_sha = compute_file_sha256(Path(sample_dataset_with_failures["csv_path"]))
    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
        "source": {
            "dataset_id": sample_dataset_with_failures["dataset_id"],
            "dataset_version": sample_dataset_with_failures["dataset_version"],
            "source_uri": sample_dataset_with_failures["csv_rel_path"],
            "sha256": sensor_sha,
        },
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


def test_feature_bundle_reuse_fails_when_sensor_file_modified_after_bundle_creation(client, sample_dataset_with_failures):
    """If the raw sensor dataset is modified after bundle creation, subsequent /feature call rejects reuse with SOURCE_DATASET_INTEGRITY_ERROR."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]
    failure_id = sample_dataset_with_failures["failure_dataset_id"]
    failure_ver = sample_dataset_with_failures["failure_dataset_version"]

    ext_res = client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_rel_path"],
        "force_reanalyze": True,
    })
    assert ext_res.status_code == 200
    plan_ver = ext_res.json()["extraction_plan_version"]
    map_ver = ext_res.json()["result"]["mapping_version"]

    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "failure_dataset_id": failure_id,
        "failure_dataset_version": failure_ver,
        "extraction_plan_version": plan_ver,
        "mapping_version": map_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    # 1. First run creates bundle
    feat_res1 = client.post("/feature", json=feat_payload)
    assert feat_res1.status_code == 200

    # 2. Modify raw sensor CSV file
    with open(sample_dataset_with_failures["csv_path"], "a", encoding="utf-8") as f:
        f.write("M001,2026-01-01 10:00:00,299.0,1999.0\n")

    # 3. Second run must reject reuse because raw sensor SHA-256 changed!
    feat_res2 = client.post("/feature", json=feat_payload)
    assert feat_res2.status_code == 422
    assert feat_res2.json()["error"]["code"] == "SOURCE_DATASET_INTEGRITY_ERROR"


def test_feature_bundle_reuse_fails_when_failure_file_modified_after_bundle_creation(client, sample_dataset_with_failures):
    """If the failure dataset is modified after bundle creation, subsequent /feature call rejects reuse with FEATURE_DATASET_INTEGRITY_ERROR."""
    dataset_id = sample_dataset_with_failures["dataset_id"]
    dataset_version = sample_dataset_with_failures["dataset_version"]
    failure_id = sample_dataset_with_failures["failure_dataset_id"]
    failure_ver = sample_dataset_with_failures["failure_dataset_version"]

    ext_res = client.post("/extraction", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "source_uri": sample_dataset_with_failures["csv_rel_path"],
        "force_reanalyze": True,
    })
    assert ext_res.status_code == 200
    plan_ver = ext_res.json()["extraction_plan_version"]
    map_ver = ext_res.json()["result"]["mapping_version"]

    feat_payload = {
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "failure_dataset_id": failure_id,
        "failure_dataset_version": failure_ver,
        "extraction_plan_version": plan_ver,
        "mapping_version": map_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    }
    # 1. First run creates bundle
    feat_res1 = client.post("/feature", json=feat_payload)
    assert feat_res1.status_code == 200

    # 2. Modify failure CSV file
    with open(sample_dataset_with_failures["failure_csv"], "a", encoding="utf-8") as f:
        f.write("M001,2026-01-01 10:00:00,Overheat\n")

    # 3. Second run must reject reuse because failure SHA-256 changed!
    feat_res2 = client.post("/feature", json=feat_payload)
    assert feat_res2.status_code == 422
    assert feat_res2.json()["error"]["code"] == "FEATURE_DATASET_INTEGRITY_ERROR"


def test_feature_bundle_validation_exhaustive(tmp_path):
    """Exhaustive test for validate_feature_bundle checking all integrity and path safety violations."""
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
    split_indices = {
        "train": [0, 1, 2],
        "val": [3],
        "test": [4],
    }
    row_metadata = {
        "asset_ids": ["M1", "M1", "M1", "M1", "M1"],
        "timestamps": ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 02:00:00", "2026-01-01 03:00:00", "2026-01-01 04:00:00"],
    }
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
        "split_indices": split_indices,
    }

    # 1. Normal publish with row_metadata
    repo.publish_feature_bundle("ds1", "v1", fver, X, y, cols, meta, row_metadata=row_metadata)
    validated = repo.validate_feature_bundle("ds1", "v1", fver, contract)
    assert validated["row_count"] == 5

    # 2. Missing labels.npy
    (target_dir / "labels.npy").unlink()
    with pytest.raises(FeatureDatasetIntegrityError, match="필수 파일이 누락"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)
    np.save(target_dir / "labels.npy", y)

    # 3. Path traversal in checksum files (e.g. "../secret.txt")
    with open(target_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta_corrupted = json.load(f)
    meta_corrupted["checksum"]["files"]["../secret.txt"] = "abc"
    with open(target_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_corrupted, f)
    with pytest.raises(FeatureDatasetIntegrityError, match="유효하지 않은 문자나 상위/하위 경로"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)

    # 4. Unlisted file in checksum files
    with open(target_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta_corrupted = json.load(f)
    meta_corrupted["checksum"]["files"].pop("../secret.txt", None)
    meta_corrupted["checksum"]["files"]["unauthorized.exe"] = "abc"
    with open(target_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_corrupted, f)
    with pytest.raises(FeatureDatasetIntegrityError, match="허용되지 않은 체크섬 대상 파일명"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)

    # 5. Missing row_metadata.json from checksum when file exists
    with open(target_dir / "feature_metadata.json", "r", encoding="utf-8") as f:
        meta_corrupted = json.load(f)
    meta_corrupted["checksum"]["files"].pop("unauthorized.exe", None)
    meta_corrupted["checksum"]["files"].pop("row_metadata.json", None)
    with open(target_dir / "feature_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta_corrupted, f)
    with pytest.raises(FeatureDatasetIntegrityError, match="필수 파일 'row_metadata.json'의 체크섬이 선언되지 않았습니다"):
        repo.validate_feature_bundle("ds1", "v1", fver, contract)


def test_feature_plan_missing_source_rejected(client, sample_dataset_with_failures):
    """Extraction Plan lacking 'source' contract is rejected with SOURCE_DATASET_INTEGRITY_ERROR."""
    ext_repo = ExtractionRepository()
    plan_no_source = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
    }
    plan_ver, _ = ext_repo.publish_plan(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_no_source)
    mapping_data = {
        "voltage": {"target_ontology": "Voltage", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
        "rotation": {"target_ontology": "Rotation", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
    }
    map_ver, _ = ext_repo.publish_mapping(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], mapping_data)

    res = client.post("/feature", json={
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
    })
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "SOURCE_DATASET_INTEGRITY_ERROR"


def test_feature_plan_source_field_and_format_validations(client, sample_dataset_with_failures):
    """Extraction Plan source with missing fields, bad SHA-256 format, or traversal paths is rejected."""
    ext_repo = ExtractionRepository()
    sensor_sha = compute_file_sha256(Path(sample_dataset_with_failures["csv_path"]))
    mapping_data = {
        "voltage": {"target_ontology": "Voltage", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
        "rotation": {"target_ontology": "Rotation", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
    }
    map_ver, _ = ext_repo.publish_mapping(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], mapping_data)

    # 1. Invalid SHA-256 hex format (uppercase or bad length)
    plan_bad_sha = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
        "source": {
            "dataset_id": sample_dataset_with_failures["dataset_id"],
            "dataset_version": sample_dataset_with_failures["dataset_version"],
            "source_uri": sample_dataset_with_failures["csv_rel_path"],
            "sha256": "NOT_A_VALID_HEX_64_CHARS",
        },
    }
    p_ver1, _ = ext_repo.publish_plan(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_bad_sha)
    res1 = client.post("/feature", json={
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "failure_dataset_id": sample_dataset_with_failures["failure_dataset_id"],
        "failure_dataset_version": sample_dataset_with_failures["failure_dataset_version"],
        "extraction_plan_version": p_ver1,
        "mapping_version": map_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "SOURCE_DATASET_INTEGRITY_ERROR"

    # 2. Traversal path in source_uri
    plan_traversal = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "asset_id",
        "time_column": "timestamp",
        "duplicate_policy": "error",
        "source": {
            "dataset_id": sample_dataset_with_failures["dataset_id"],
            "dataset_version": sample_dataset_with_failures["dataset_version"],
            "source_uri": "../secret.csv",
            "sha256": sensor_sha,
        },
    }
    p_ver2, _ = ext_repo.publish_plan(sample_dataset_with_failures["dataset_id"], sample_dataset_with_failures["dataset_version"], plan_traversal)
    res2 = client.post("/feature", json={
        "dataset_id": sample_dataset_with_failures["dataset_id"],
        "dataset_version": sample_dataset_with_failures["dataset_version"],
        "failure_dataset_id": sample_dataset_with_failures["failure_dataset_id"],
        "failure_dataset_version": sample_dataset_with_failures["failure_dataset_version"],
        "extraction_plan_version": p_ver2,
        "mapping_version": map_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "SOURCE_DATASET_INTEGRITY_ERROR"


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

    # 2. Failure dataset v1 (version in filename)
    f1_file = data_dir / "failures_v1" / "v1.0.csv"
    f1_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "asset_id": "A1",
        "observed_at": "2026-01-01 01:30:00",
        "failure_type": "Overheat",
    }]).to_csv(f1_file, index=False)

    # 3. Failure dataset v2 (version in filename)
    f2_file = data_dir / "failures_v2" / "v2.0.csv"
    f2_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "asset_id": "A2",
        "observed_at": "2026-01-01 01:30:00",
        "failure_type": "Vibration",
    }]).to_csv(f2_file, index=False)

    # 4. Incompatible Failure dataset
    fincompat_file = data_dir / "failures_incompat" / "v1.0.csv"
    fincompat_file.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "asset_id": "CAR_999",
        "observed_at": "2026-01-01 01:30:00",
        "failure_type": "Engine",
    }]).to_csv(fincompat_file, index=False)

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

    # Run with non-existent failure dataset -> fails with 422 FAILURE_DATASET_VERSION_MISMATCH
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
    assert res_missing.status_code == 422
    assert res_missing.json()["error"]["code"] == "FAILURE_DATASET_VERSION_MISMATCH"


def test_feature_split_metadata_fail_fast_on_missing_id_or_time_column(client, tmp_path, monkeypatch):
    """If ID column or time column is missing, /feature fails fast with TRAINING_SPLIT_METADATA_MISSING."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    telem_path = data_dir / "split_fail.csv"
    pd.DataFrame({
        "asset_id": ["A1", "A1", "A1", "A1"],
        "timestamp": ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 02:00:00", "2026-01-01 03:00:00"],
        "voltage": [220.0, 222.0, 221.0, 225.0],
        "rotation": [1500.0, 1510.0, 1505.0, 1515.0],
    }).to_csv(telem_path, index=False)

    fail_path = data_dir / "fail" / "v1.0.csv"
    fail_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "asset_id": "A1",
        "observed_at": "2026-01-01 01:30:00",
        "failure_type": "Overheat",
    }]).to_csv(fail_path, index=False)

    ext_repo = ExtractionRepository()
    sensor_sha = compute_file_sha256(telem_path)
    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["asset_id", "timestamp", "voltage", "rotation"],
        "id_column": "non_existent_id_column",
        "time_column": "timestamp",
        "duplicate_policy": "error",
        "source": {
            "dataset_id": "split_fail",
            "dataset_version": "v1.0",
            "source_uri": "split_fail.csv",
            "sha256": sensor_sha,
        },
    }
    plan_ver, _ = ext_repo.publish_plan("split_fail", "v1.0", plan_data)
    mapping_data = {
        "voltage": {"target_ontology": "Voltage", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
        "rotation": {"target_ontology": "Rotation", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"},
    }
    map_ver, _ = ext_repo.publish_mapping("split_fail", "v1.0", mapping_data)

    res = client.post("/feature", json={
        "dataset_id": "split_fail",
        "dataset_version": "v1.0",
        "failure_dataset_id": "fail",
        "failure_dataset_version": "v1.0",
        "extraction_plan_version": plan_ver,
        "mapping_version": map_ver,
        "feature_schema_version": "pdm-feature-v1",
        "label_schema_version": "pdm-label-v1",
        "prediction_horizon_hours": 24,
        "rebuild_npy": True,
    })
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "TRAINING_SPLIT_METADATA_MISSING"

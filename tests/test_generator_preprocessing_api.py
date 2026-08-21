"""Tests for Generator domain FastAPI application and Preprocessing API (/preprocessing)."""

import json
import pytest
import pandas as pd
from pathlib import Path
from fastapi.testclient import TestClient

from systems.generator.generator_config import PATHS
from systems.generator.app.main import app
from systems.generator.app.preprocessing.preprocessing_schema import (
    PreprocessingRequest,
    PreprocessingResponse,
    PreprocessingPlanResponse,
)
from systems.generator.app.preprocessing.preprocessing_exception import (
    PreprocessingError,
    DatasetNotFoundError,
    DatasetContractError,
    PreprocessingRoleError,
)
from systems.generator.app.preprocessing.preprocessing_repository import PreprocessingRepository
from systems.generator.app.preprocessing.preprocessing_service import (
    PreprocessingService,
    preprocess_with_plan,
    load_all_sources,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_wide_csv(tmp_path):
    rel_path = "tmp_telemetry_wide_test.csv"
    csv_path = PATHS.data_dir / rel_path
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "asset_id": ["M001", "M001", "M002"],
        "timestamp": ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 00:00:00"],
        "temperature": [55.2, 57.8, 62.1],
        "vibration": [0.12, 0.15, 0.18],
    })
    df.to_csv(csv_path, index=False)
    yield rel_path
    if csv_path.exists():
        csv_path.unlink()


@pytest.fixture
def sample_long_csv(tmp_path):
    rel_path = "tmp_telemetry_long_test.csv"
    csv_path = PATHS.data_dir / rel_path
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({
        "machine_id": ["M1", "M1", "M1", "M1"],
        "ts": ["2026-01-01 00:00:00", "2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 01:00:00"],
        "metric_name": ["temp", "vib", "temp", "vib"],
        "metric_value": [50.0, 0.1, 52.0, 0.15],
    })
    df.to_csv(csv_path, index=False)
    yield rel_path
    if csv_path.exists():
        csv_path.unlink()


def test_app_health_endpoint(client):
    """GET /health returns 200 and system identifier."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["system"] == "generator"
    assert "X-Request-ID" in res.headers


def test_preprocessing_wide_format_success(client, sample_wide_csv):
    """POST /preprocessing on wide tabular data succeeds and returns plan response."""
    payload = {
        "dataset_id": "test_wide",
        "dataset_version": "v1.0",
        "source_uri": sample_wide_csv,
        "force_reanalyze": True,
        "duplicate_policy": "error",
        "aggregation": None,
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "succeeded"
    assert data["dataset_id"] == "test_wide"
    assert data["dataset_version"] == "v1.0"
    assert "request_id" in data
    assert "run_id" in data
    assert "result" in data
    assert data["result"]["extraction_type"] in ("tabular_column_as_attribute", "wide_pivot")
    assert "mapping_uri" in data["result"]
    assert not data["result"]["mapping_uri"].startswith("C:")  # Logical / relative URI


def test_preprocessing_long_format_success(client, sample_long_csv, monkeypatch):
    """POST /preprocessing on long format data plans roles and pivots successfully."""
    from systems.generator.app.preprocessing.preprocessing_planner import PreprocessingPlanner
    def mock_plan_columns(self, filepath, structure_type, df_preview, duplicate_policy="error", aggregation=None):
        return {
            "selected_columns": ["machine_id", "ts", "metric_name", "metric_value"],
            "id_column": "machine_id",
            "time_column": "ts",
            "attribute_column": "metric_name",
            "value_column": "metric_value",
            "duplicate_policy": duplicate_policy,
            "aggregation": aggregation,
        }

    monkeypatch.setattr(PreprocessingPlanner, "classify_structure", lambda self, f, d: "tabular_row_as_attribute")
    monkeypatch.setattr(PreprocessingPlanner, "plan_columns", mock_plan_columns)

    payload = {
        "dataset_id": "test_long",
        "dataset_version": "v1.0",
        "source_uri": sample_long_csv,
        "force_reanalyze": True,
        "duplicate_policy": "error",
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "succeeded"
    assert data["dataset_id"] == "test_long"
    assert data["result"]["id_column"] == "machine_id"
    assert data["result"]["attribute_column"] == "metric_name"
    assert data["result"]["value_column"] == "metric_value"
    assert data["result"]["time_column"] == "ts"


def test_preprocessing_dataset_not_found(client):
    """POST /preprocessing returns 404 when dataset cannot be resolved."""
    payload = {
        "dataset_id": "non_existent_dataset_xyz",
        "dataset_version": "v99.0",
        "source_uri": "non_existent_path.csv",
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 404
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "DATASET_NOT_FOUND"
    assert "X-Request-ID" in res.headers


def test_preprocessing_long_format_missing_roles_fails_fast(client, sample_long_csv, monkeypatch):
    """POST /preprocessing raises 422 PREPROCESSING_ROLE_COLUMNS_MISSING when long-format roles are incomplete."""
    from systems.generator.app.preprocessing.preprocessing_planner import PreprocessingPlanner
    def mock_plan_columns_incomplete(self, filepath, structure_type, df_preview, duplicate_policy="error", aggregation=None):
        return {
            "selected_columns": ["machine_id", "ts"],
            "id_column": "machine_id",
            "time_column": "ts",
            "attribute_column": None,  # Missing!
            "value_column": None,      # Missing!
        }

    monkeypatch.setattr(PreprocessingPlanner, "classify_structure", lambda self, f, d: "tabular_row_as_attribute")
    monkeypatch.setattr(PreprocessingPlanner, "plan_columns", mock_plan_columns_incomplete)

    payload = {
        "dataset_id": "test_long_missing_roles",
        "dataset_version": "v1.0",
        "source_uri": sample_long_csv,
        "force_reanalyze": True,
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "PREPROCESSING_ROLE_COLUMNS_MISSING"


def test_preprocessing_invalid_duplicate_aggregation_policy(client):
    """POST /preprocessing rejects aggregate policy without aggregation function."""
    payload = {
        "dataset_id": "test_ds",
        "dataset_version": "v1.0",
        "duplicate_policy": "aggregate",
        "aggregation": None,  # Invalid
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_preprocessing_absolute_path_traversal_rejection(client):
    """POST /preprocessing rejects path traversal or absolute path in source_uri."""
    payload = {
        "dataset_id": "test_ds",
        "dataset_version": "v1.0",
        "source_uri": "../../../etc/passwd",
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "DATASET_CONTRACT_ERROR"

    # Also test absolute path rejection
    payload_abs = {
        "dataset_id": "test_ds",
        "dataset_version": "v1.0",
        "source_uri": "C:/Windows/System32/drivers/etc/hosts",
    }
    res_abs = client.post("/preprocessing", json=payload_abs)
    assert res_abs.status_code == 422
    assert res_abs.json()["error"]["code"] == "DATASET_CONTRACT_ERROR"


def test_preprocessing_outside_allowed_root_rejection(client):
    """POST /preprocessing rejects source_uri that exists in repo but is outside allowed data roots."""
    payload = {
        "dataset_id": "test_ds",
        "dataset_version": "v1.0",
        "source_uri": "docs/architecture.md",
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "DATASET_CONTRACT_ERROR"


def test_preprocessing_dataset_id_path_traversal_rejection(client):
    """POST /preprocessing rejects dataset_id with path traversal (..)."""
    payload = {
        "dataset_id": "../../../etc/passwd",
        "dataset_version": "v1.0",
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "DATASET_CONTRACT_ERROR"


def test_preprocessing_dataset_version_path_traversal_rejection(client):
    """POST /preprocessing rejects dataset_version with path traversal (..)."""
    payload = {
        "dataset_id": "valid_ds",
        "dataset_version": "../../../etc/shadow",
    }
    res = client.post("/preprocessing", json=payload)
    assert res.status_code == 422
    data = res.json()
    assert "error" in data
    assert data["error"]["code"] == "DATASET_CONTRACT_ERROR"


def test_preprocessing_dataset_id_lookup_success(client):
    """POST /preprocessing successfully finds file by dataset_id within PATHS.data_dir."""
    # Ensure test file exists in data/
    test_file = PATHS.data_dir / "lookup_test_dataset" / "v1.0.csv"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame({"asset_id": ["A1"], "timestamp": ["2026-01-01 00:00:00"], "val": [10.0]})
    df.to_csv(test_file, index=False)

    try:
        payload = {
            "dataset_id": "lookup_test_dataset",
            "dataset_version": "v1.0",
            "force_reanalyze": True,
        }
        res = client.post("/preprocessing", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "succeeded"
        assert data["dataset_id"] == "lookup_test_dataset"
        assert data["dataset_version"] == "v1.0"
    finally:
        if test_file.exists():
            test_file.unlink()
        if test_file.parent.exists():
            test_file.parent.rmdir()


def test_preprocessing_plan_cache_and_reuse(client, sample_wide_csv, tmp_path):
    """POST /preprocessing reuses cached plan when force_reanalyze=False and regenerates when True."""
    repo = PreprocessingRepository(base_dir=tmp_path / "plans")
    service = PreprocessingService(repository=repo)

    req1 = PreprocessingRequest(
        dataset_id="cache_test",
        dataset_version="v1",
        source_uri=sample_wide_csv,
        force_reanalyze=False,
    )
    res1 = service.run_preprocessing(req1)
    plan_path = repo.get_plan_path("cache_test", "v1")
    assert plan_path.exists()

    # Re-run: should reuse
    res2 = service.run_preprocessing(req1)
    assert res2.status == "succeeded"
    assert res2.preprocessing_plan_version == res1.preprocessing_plan_version


def test_legacy_extraction_facade_compatibility(sample_wide_csv):
    """Verify legacy systems.generator.extraction import facades delegate correctly to preprocessing."""
    from systems.generator.extraction import (
        load_all_sources as legacy_load_all,
        extract_with_plan as legacy_extract_with_plan,
        build_extraction_plan as legacy_build_plan,
    )
    from systems.generator.extraction.extraction_agent import ExtractionPlanner as LegacyPlanner

    actual_file = str(PATHS.data_dir / sample_wide_csv)
    plan = legacy_build_plan(actual_file)
    assert "structure_type" in plan
    assert "selected_columns" in plan

    df = legacy_extract_with_plan(actual_file, plan)
    assert not df.empty
    assert len(df) == 3

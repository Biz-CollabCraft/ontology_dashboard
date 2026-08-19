"""Tests for Generator domain FastAPI application and Extraction API (/extraction)."""

import json
import pytest
import pandas as pd
from pathlib import Path
from fastapi.testclient import TestClient

from systems.generator.app.main import app
from systems.generator.app.extraction.extraction_schema import (
    ExtractionRequest,
    ExtractionResponse,
    ExtractionPlanResponse,
)
from systems.generator.app.extraction.extraction_exception import (
    ExtractionError,
    DatasetNotFoundError,
    ExtractionRoleError,
)
from systems.generator.app.extraction.extraction_repository import ExtractionRepository
from systems.generator.app.extraction.extraction_service import (
    ExtractionService,
    extract_with_plan,
    load_all_sources,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_wide_csv(tmp_path):
    csv_path = tmp_path / "telemetry_wide.csv"
    df = pd.DataFrame({
        "asset_id": ["M001", "M001", "M002"],
        "timestamp": ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 00:00:00"],
        "temperature": [55.2, 57.8, 62.1],
        "vibration": [0.12, 0.15, 0.18],
    })
    df.to_csv(csv_path, index=False)
    return str(csv_path)


@pytest.fixture
def sample_long_csv(tmp_path):
    csv_path = tmp_path / "telemetry_long.csv"
    df = pd.DataFrame({
        "machine_id": ["M1", "M1", "M1", "M1"],
        "ts": ["2026-01-01 00:00:00", "2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 01:00:00"],
        "metric_name": ["temp", "vib", "temp", "vib"],
        "metric_value": [50.0, 0.1, 52.0, 0.15],
    })
    df.to_csv(csv_path, index=False)
    return str(csv_path)


def test_app_health_endpoint(client):
    """GET /health returns 200 and system identifier."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["system"] == "generator"
    assert "X-Request-ID" in res.headers


def test_extraction_wide_format_success(client, sample_wide_csv):
    """POST /extraction on wide tabular data succeeds and returns plan response."""
    payload = {
        "dataset_id": "test_wide",
        "dataset_version": "v1.0",
        "source_uri": sample_wide_csv,
        "force_reanalyze": True,
        "duplicate_policy": "error",
        "aggregation": None,
    }
    res = client.post("/extraction", json=payload)
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


def test_extraction_long_format_success(client, sample_long_csv, monkeypatch):
    """POST /extraction on long format data plans roles and pivots successfully."""
    # Mock planner stage2 to return explicit long format roles
    from systems.generator.app.extraction.extraction_planner import ExtractionPlanner
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
    def mock_classify(self, filepath, df_preview):
        return "tabular_row_as_attribute"

    monkeypatch.setattr(ExtractionPlanner, "classify_structure", mock_classify)
    monkeypatch.setattr(ExtractionPlanner, "plan_columns", mock_plan_columns)

    payload = {
        "dataset_id": "test_long",
        "dataset_version": "v1.0",
        "source_uri": sample_long_csv,
        "force_reanalyze": True,
        "duplicate_policy": "error",
    }
    res = client.post("/extraction", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "succeeded"
    assert data["result"]["extraction_type"] == "tabular_row_as_attribute"
    assert data["result"]["id_column"] == "machine_id"
    assert data["result"]["attribute_column"] == "metric_name"
    assert data["result"]["value_column"] == "metric_value"


def test_extraction_long_format_missing_roles_fails_fast(client, sample_long_csv, monkeypatch):
    """Long-format without explicit roles fails fast with EXTRACTION_ROLE_COLUMNS_MISSING."""
    from systems.generator.app.extraction.extraction_planner import ExtractionPlanner

    def mock_plan_columns_missing_role(self, filepath, structure_type, df_preview, duplicate_policy="error", aggregation=None):
        return {
            "selected_columns": list(df_preview.columns),
            "id_column": None,  # Missing id_column
            "attribute_column": "metric_name",
            "value_column": "metric_value",
        }
    def mock_classify(self, filepath, df_preview):
        return "tabular_row_as_attribute"

    monkeypatch.setattr(ExtractionPlanner, "classify_structure", mock_classify)
    monkeypatch.setattr(ExtractionPlanner, "plan_columns", mock_plan_columns_missing_role)

    payload = {
        "dataset_id": "test_long_bad",
        "dataset_version": "v1.0",
        "source_uri": sample_long_csv,
        "force_reanalyze": True,
    }
    res = client.post("/extraction", json=payload)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "EXTRACTION_ROLE_COLUMNS_MISSING"
    assert "error_id" in err
    assert "request_id" in err


def test_extraction_dataset_not_found(client):
    """POST /extraction with non-existent dataset returns 404 DATASET_NOT_FOUND."""
    payload = {
        "dataset_id": "completely_nonexistent_dataset_xyz",
        "dataset_version": "v99.9",
        "source_uri": "nonexistent/path/never_existed.csv",
    }
    res = client.post("/extraction", json=payload)
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "DATASET_NOT_FOUND"


def test_extraction_method_not_allowed(client):
    """GET /extraction returns 405 METHOD_NOT_ALLOWED."""
    res = client.get("/extraction")
    assert res.status_code == 405
    err = res.json()["error"]
    assert err["code"] == "METHOD_NOT_ALLOWED"


def test_undefined_route_not_found(client):
    """Undefined route returns 404 NOT_FOUND."""
    res = client.get("/nonexistent/api/route")
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "NOT_FOUND"


def test_request_validation_missing_required_fields(client):
    """Missing required dataset_id/dataset_version returns 422 REQUEST_VALIDATION_ERROR."""
    res = client.post("/extraction", json={"force_reanalyze": True})
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "REQUEST_VALIDATION_ERROR"
    assert len(err["details"]) > 0


def test_request_validation_duplicate_policy_aggregation_conflict(client):
    """duplicate_policy='aggregate' without aggregation returns 422 REQUEST_VALIDATION_ERROR."""
    payload = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "duplicate_policy": "aggregate",
        "aggregation": None,
    }
    res = client.post("/extraction", json=payload)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "REQUEST_VALIDATION_ERROR"

    # duplicate_policy='error' with aggregation='mean'
    payload2 = {
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "duplicate_policy": "error",
        "aggregation": "mean",
    }
    res2 = client.post("/extraction", json=payload2)
    assert res2.status_code == 422
    err2 = res2.json()["error"]
    assert err2["code"] == "REQUEST_VALIDATION_ERROR"


def test_repository_atomic_publish(tmp_path):
    """ExtractionRepository stages in temp file and publishes atomically."""
    repo = ExtractionRepository(base_dir=tmp_path / "plans")
    plan_data = {"test_key": "test_value", "structure_type": "tabular_column_as_attribute"}
    uri = repo.publish_plan("ds_test", "v1", plan_data)
    assert "ds_test-v1.json" in uri

    loaded = repo.find_plan("ds_test", "v1")
    assert loaded == plan_data

    # Ensure no lingering .tmp files
    tmp_files = list((tmp_path / "plans").glob(".tmp_*"))
    assert len(tmp_files) == 0


def test_legacy_facade_compatibility(sample_wide_csv):
    """Legacy extraction imports work seamlessly without regression."""
    from systems.generator.extraction.extraction_service import (
        extract_with_plan as legacy_extract,
        SUPPORTED_EXTENSIONS,
    )
    from systems.generator.extraction.extraction_agent import (
        build_extraction_plan as legacy_build_plan,
    )
    from systems.generator.generator_llm_client import ExtractionPlanResponse as LegacyResponse

    assert ".csv" in SUPPORTED_EXTENSIONS
    plan = legacy_build_plan(sample_wide_csv, force_reanalyze=True)
    assert plan is not None
    assert "selected_columns" in plan

    df = legacy_extract(sample_wide_csv, plan)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3

    resp = LegacyResponse(
        structure_type="tabular_column_as_attribute",
        selected_columns=["col1", "col2"],
    )
    assert resp.structure_type == "tabular_column_as_attribute"

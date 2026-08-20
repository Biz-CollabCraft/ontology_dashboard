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
    DatasetContractError,
    ExtractionRoleError,
    ExtractionPlanNotReadyError,
    ExtractionPlanIntegrityError,
    ExtractionPlanContractInvalidError,
    OntologyMappingNotReadyError,
    OntologyMappingIntegrityError,
    OntologyMappingContractInvalidError,
)
from systems.generator.app.extraction.extraction_repository import (
    ExtractionRepository,
    compute_plan_version,
    compute_mapping_version,
)
from systems.generator.app.extraction.extraction_service import (
    ExtractionService,
    extract_with_plan,
    load_all_sources,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_wide_csv(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    csv_path = data_dir / "telemetry_wide.csv"
    df = pd.DataFrame({
        "asset_id": ["M001", "M001", "M002"],
        "timestamp": ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 00:00:00"],
        "temperature": [55.2, 57.8, 62.1],
        "vibration": [0.12, 0.15, 0.18],
    })
    df.to_csv(csv_path, index=False)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    return "telemetry_wide.csv"


@pytest.fixture
def sample_long_csv(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    models_store = tmp_path / "models_store"
    models_store.mkdir(parents=True, exist_ok=True)

    csv_path = data_dir / "telemetry_long.csv"
    df = pd.DataFrame({
        "machine_id": ["M1", "M1", "M1", "M1"],
        "ts": ["2026-01-01 00:00:00", "2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 01:00:00"],
        "metric_name": ["temp", "vib", "temp", "vib"],
        "metric_value": [50.0, 0.1, 52.0, 0.15],
    })
    df.to_csv(csv_path, index=False)

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)
    monkeypatch.setattr(PATHS, "models_store", models_store)

    return "telemetry_long.csv"


def test_app_health_endpoint(client):
    """GET /health returns 200 and system identifier."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["system"] == "generator"
    assert "X-Request-ID" in res.headers


def test_extraction_wide_format_success(client, sample_wide_csv):
    """POST /extraction on wide tabular data succeeds and returns content-addressed plan response."""
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
    assert data["extraction_plan_version"].startswith("extraction-plan-")
    assert data["result"]["mapping_version"].startswith("ontology-mapping-")
    assert "result" in data
    assert data["result"]["extraction_type"] in ("tabular_column_as_attribute", "wide_pivot")
    assert "mapping_uri" in data["result"]
    assert not data["result"]["mapping_uri"].startswith("C:")


def test_extraction_does_not_mutate_global_mapping_cache(client, sample_wide_csv, tmp_path, monkeypatch):
    """POST /extraction must NOT mutate global MAPPING_CACHE_PATH file."""
    fake_global_cache = tmp_path / "global_mapping_cache.json"
    fake_global_cache.write_text('{"existing_col": {"target_ontology": "Voltage"}}', encoding="utf-8")
    orig_content = fake_global_cache.read_text(encoding="utf-8")

    from systems.generator.ontology_mapping import mapping_agent
    monkeypatch.setattr(mapping_agent, "MAPPING_CACHE_PATH", fake_global_cache)

    payload = {
        "dataset_id": "test_wide",
        "dataset_version": "v1.0",
        "source_uri": sample_wide_csv,
        "force_reanalyze": True,
    }
    res = client.post("/extraction", json=payload)
    assert res.status_code == 200

    # Global cache remains completely untouched
    assert fake_global_cache.read_text(encoding="utf-8") == orig_content


def test_extraction_reuse_valid_and_reject_corrupted_plan_and_mapping(tmp_path):
    """ExtractionRepository reuses valid plans/mappings and rejects corrupted/tampered files without overwriting."""
    repo = ExtractionRepository(
        base_dir=tmp_path / "plans",
        mappings_dir=tmp_path / "mappings",
    )

    plan_data = {
        "structure_type": "tabular_column_as_attribute",
        "selected_columns": ["colA", "colB"],
        "id_column": "colA",
        "duplicate_policy": "error",
    }
    mapping_data = {
        "colB": {"target_ontology": "Voltage", "source": "mapping_agent", "confidence": 1.0, "status": "auto_mapped"}
    }

    # 1. Publish first time
    plan_ver, _ = repo.publish_plan("ds1", "v1", plan_data)
    map_ver, _ = repo.publish_mapping("ds1", "v1", mapping_data)

    # 2. Re-publish valid -> returns same version and reuses cleanly
    plan_ver2, _ = repo.publish_plan("ds1", "v1", plan_data)
    map_ver2, _ = repo.publish_mapping("ds1", "v1", mapping_data)
    assert plan_ver == plan_ver2
    assert map_ver == map_ver2

    # 3. Corrupt plan on disk (tampered content)
    plan_file = repo.get_plan_path("ds1", "v1", plan_ver)
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump({"tampered": True, "structure_type": "invalid_type"}, f)

    with pytest.raises(ExtractionPlanContractInvalidError):
        repo.publish_plan("ds1", "v1", plan_data)

    # 4. Corrupt mapping on disk (tampered content)
    map_file = repo.get_mapping_path("ds1", "v1", map_ver)
    with open(map_file, "w", encoding="utf-8") as f:
        json.dump({"colB": {"invalid_format": True}}, f)

    with pytest.raises(OntologyMappingContractInvalidError):
        repo.publish_mapping("ds1", "v1", mapping_data)


def test_extraction_long_format_success(client, sample_long_csv, monkeypatch):
    """POST /extraction on long format data plans roles and pivots successfully."""
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
            "id_column": None,
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


def test_extraction_source_uri_security(client, tmp_path, monkeypatch):
    """Absolute paths or traversal attempts in source_uri return 422 DATASET_PATH_NOT_ALLOWED."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)

    # 1. Absolute path
    res1 = client.post("/extraction", json={
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "source_uri": "C:/etc/passwd",
    })
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "DATASET_PATH_NOT_ALLOWED"

    # 2. Path traversal
    res2 = client.post("/extraction", json={
        "dataset_id": "ds1",
        "dataset_version": "v1",
        "source_uri": "../secret.csv",
    })
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "DATASET_PATH_NOT_ALLOWED"


def test_extraction_dataset_not_found(client):
    """Non-existent dataset returns 404 DATASET_NOT_FOUND."""
    payload = {
        "dataset_id": "non_existent_dataset_xyz",
        "dataset_version": "v999",
        "source_uri": "non_existent.csv",
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
    res = client.get("/unknown_domain_endpoint")
    assert res.status_code == 404
    err = res.json()["error"]
    assert err["code"] == "NOT_FOUND"


def test_request_validation_identifier_format(client):
    """Invalid dataset_id or dataset_version with path traversal returns 422 REQUEST_VALIDATION_ERROR."""
    res = client.post("/extraction", json={
        "dataset_id": "../evil_dataset",
        "dataset_version": "v1",
    })
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"


def test_repository_containment_verification(tmp_path):
    """ExtractionRepository rejects paths attempting root breakout with INVALID_ARTIFACT_PATH."""
    repo = ExtractionRepository(
        base_dir=tmp_path / "plans",
        mappings_dir=tmp_path / "mappings",
    )

    with pytest.raises(ExtractionPlanContractInvalidError) as exc_plan:
        repo.get_plan_path("../escape", "v1", "extraction-plan-1234567812345678")
    assert exc_plan.value.code == "INVALID_ARTIFACT_PATH"

    with pytest.raises(OntologyMappingContractInvalidError) as exc_map:
        repo.get_mapping_path("../escape", "v1", "ontology-mapping-1234567812345678")
    assert exc_map.value.code == "INVALID_ARTIFACT_PATH"


def test_legacy_facade_compatibility(tmp_path):
    """Legacy extraction imports work seamlessly without regression."""
    csv_file = tmp_path / "wide.csv"
    pd.DataFrame({"asset_id": ["A", "B"], "voltage": [220.0, 221.0]}).to_csv(csv_file, index=False)

    from systems.generator.extraction.extraction_service import (
        extract_with_plan as legacy_extract,
        SUPPORTED_EXTENSIONS,
    )
    from systems.generator.extraction.extraction_agent import (
        build_extraction_plan as legacy_build_plan,
    )
    from systems.generator.generator_llm_client import ExtractionPlanResponse as LegacyResponse

    assert ".csv" in SUPPORTED_EXTENSIONS
    plan = legacy_build_plan(str(csv_file), force_reanalyze=True)
    assert plan is not None
    assert "selected_columns" in plan

    df = legacy_extract(str(csv_file), plan)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2

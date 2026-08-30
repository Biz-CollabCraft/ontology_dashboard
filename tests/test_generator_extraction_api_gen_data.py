"""API tests for POST /extraction and GET /extraction/status in gen_data mode."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from systems.generator.generator_config import PATHS
from systems.generator.app.extraction.extraction_manager import (
    ExtractionManager,
)
from systems.generator.app.extraction.mapping_validator import (
    compute_mapping_canonical_sha256,
)
from systems.generator.app.main import app


@pytest.fixture(autouse=True)
def reset_singletons():
    ExtractionManager.set_instance(None)
    yield
    ExtractionManager.set_instance(None)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_mapping():
    m = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-static-mapping-table.schema.json",
        "mapping_id": "gen-data-sensor-stream-canonical",
        "mapping_version": "v1",
        "status": "approved",
        "source_format": "gen_data_sensor_stream",
        "source_schema_version": "gen-data-sensor-stream-v1",
        "source_schema_fingerprint": "0" * 64,
        "fingerprint_algorithm_version": "v1",
        "field_mappings": [
            {
                "source_field": "torque_nm",
                "target_field": "torque_nm",
                "source_type": "number",
                "target_type": "float",
                "required": False,
                "transform": "to_float",
            }
        ],
    }
    m["mapping_sha256"] = compute_mapping_canonical_sha256(m)
    return m


def test_post_extraction_single_source(client, tmp_path, monkeypatch, sample_mapping):
    """POST /extraction with specific source_uri extracts data and returns 200 with GenDataExtractionResponse."""
    sensor_root = tmp_path / "gen_data" / "sensor"
    stream_file = sensor_root / "facS01" / "lineL01" / "sensor_stream.jsonl"
    stream_file.parent.mkdir(parents=True, exist_ok=True)

    records = [
        {"asset_id": "CNC-01", "site_id": "S01", "cell_id": "L01", "observed_at": "2026-08-28T13:10:00Z", "torque_nm": 40.0},
        {"asset_id": "CNC-01", "site_id": "S01", "cell_id": "L01", "observed_at": "2026-08-28T14:05:00Z", "torque_nm": 45.0},
    ]
    stream_file.write_bytes(b"".join(json.dumps(r).encode("utf-8") + b"\n" for r in records))

    monkeypatch.setattr(PATHS, "data_dir", tmp_path / "data")
    monkeypatch.setattr(PATHS, "data_preprocessed", tmp_path / "preprocessed")
    monkeypatch.setattr(PATHS, "gen_data_output_dir", tmp_path / "gen_data")
    monkeypatch.setattr(PATHS, "gen_data_sensor_root", sensor_root)
    monkeypatch.setattr(PATHS, "observations_root", tmp_path / "data" / "observations")
    monkeypatch.setattr(PATHS, "extraction_mapping_sha256", sample_mapping["mapping_sha256"])

    ExtractionManager.set_instance(None)
    manager = ExtractionManager.get_instance()
    monkeypatch.setattr(manager, "_resolve_mapping_data", lambda *args, **kwargs: sample_mapping)

    resp = client.post(
        "/extraction",
        json={
            "source_mode": "gen_data_sensor_stream",
            "source_uri": "sensor/facS01/lineL01/sensor_stream.jsonl",
            "mapping_id": sample_mapping["mapping_id"],
            "mapping_version": sample_mapping["mapping_version"],
            "mapping_sha256": sample_mapping["mapping_sha256"],
        },
        headers={"X-Request-ID": "req-test-001"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "succeeded"
    assert data["processed_sources"] == 1
    assert data["succeeded_sources"] == 1
    assert len(data["sources"]) == 1
    assert len(data["sources"][0]["published_datasets"]) == 1


def test_post_extraction_all_sources(client, tmp_path, monkeypatch, sample_mapping):
    """POST /extraction with source_uri=None processes all discovered sources."""
    sensor_root = tmp_path / "gen_data" / "sensor"
    s1_file = sensor_root / "facS01" / "lineL01" / "sensor_stream.jsonl"
    s1_file.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"asset_id": "CNC-01", "site_id": "S01", "cell_id": "L01", "observed_at": "2026-08-28T13:10:00Z", "torque_nm": 40.0},
    ]
    s1_file.write_bytes(b"".join(json.dumps(r).encode("utf-8") + b"\n" for r in records))

    monkeypatch.setattr(PATHS, "data_dir", tmp_path / "data")
    monkeypatch.setattr(PATHS, "data_preprocessed", tmp_path / "preprocessed")
    monkeypatch.setattr(PATHS, "gen_data_output_dir", tmp_path / "gen_data")
    monkeypatch.setattr(PATHS, "gen_data_sensor_root", sensor_root)
    monkeypatch.setattr(PATHS, "observations_root", tmp_path / "data" / "observations")
    monkeypatch.setattr(PATHS, "extraction_mapping_sha256", sample_mapping["mapping_sha256"])

    ExtractionManager.set_instance(None)
    manager = ExtractionManager.get_instance()
    monkeypatch.setattr(manager, "_resolve_mapping_data", lambda *args, **kwargs: sample_mapping)

    resp = client.post(
        "/extraction",
        json={"source_mode": "gen_data_sensor_stream"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["processed_sources"] == 1


def test_get_extraction_status(client):
    """GET /extraction/status returns 200 with ExtractionManagerStatus payload."""
    resp = client.get("/extraction/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "running" in data
    assert "sources" in data


def test_extraction_disallowed_methods(client):
    """GET/PUT/DELETE /extraction return 405 Method Not Allowed."""
    assert client.get("/extraction").status_code == 405
    assert client.put("/extraction", json={}).status_code == 405
    assert client.delete("/extraction").status_code == 405


def test_post_extraction_validation_errors(client):
    """Invalid requests return standard 422 validation errors."""
    # Absolute path
    resp = client.post(
        "/extraction",
        json={"source_mode": "gen_data_sensor_stream", "source_uri": "/etc/passwd"},
    )
    assert resp.status_code == 422

    # Path traversal ..
    resp = client.post(
        "/extraction",
        json={"source_mode": "gen_data_sensor_stream", "source_uri": "sensor/../secret.jsonl"},
    )
    assert resp.status_code == 422

    # Incomplete mapping definition
    resp = client.post(
        "/extraction",
        json={"source_mode": "gen_data_sensor_stream", "mapping_id": "map-1"},
    )
    assert resp.status_code == 422

    # max_records <= 0
    resp = client.post(
        "/extraction",
        json={"source_mode": "gen_data_sensor_stream", "max_records": -10},
    )
    assert resp.status_code == 422

    # Extra unknown field
    resp = client.post(
        "/extraction",
        json={"source_mode": "gen_data_sensor_stream", "unknown_field": "foo"},
    )
    assert resp.status_code == 422

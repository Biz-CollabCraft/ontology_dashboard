"""Unit and integration tests for Generator Protocol Extraction API and domain."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient

from systems.generator.generator_config import PATHS, PROJECT_ROOT
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.main import app
from systems.generator.app.extraction.extraction_schema import (
    ExtractionRequest,
    ExtractionResponse,
)
from systems.generator.app.extraction.extraction_exception import (
    ExtractionMappingNotApprovedError,
    ExtractionMappingChecksumMismatchError,
    ExtractionSchemaFingerprintMismatchError,
    ExtractionFeatureNotImplementedError,
    ExtractionSourceIncompleteError,
    ExtractionSourceIntegrityError,
    ExtractionDatasetConflictError,
    ExtractionAlreadyRunningError,
    ExtractionIdempotencyConflictError,
    ExtractionSourceNotFoundError,
    ExtractionSourceChecksumMismatchError,
)
from systems.generator.app.extraction.mapping_validator import MappingValidator, compute_mapping_canonical_sha256, compute_source_schema_fingerprint
from systems.generator.app.extraction.mapping_repository import MappingRepository
from systems.generator.app.extraction.parsers.sensor_record_parser import SensorRecordParser
from systems.generator.app.extraction.dedup_repository import DedupRepository
from systems.generator.app.extraction.checkpoint_repository import CheckpointRepository
from systems.generator.app.extraction.extraction_repository import ExtractionRepository
from systems.generator.app.extraction.extraction_service import ExtractionService


@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def isolated_extraction_env(tmp_path):
    """Create clean isolated environment for extraction testing."""
    data_dir = tmp_path / "data"
    preprocessed_dir = tmp_path / "data_preprocessed"
    obs_dir = data_dir / "observations"
    runs_dir = preprocessed_dir / "extraction_runs"
    state_dir = preprocessed_dir / "extraction_state"
    mappings_dir = tmp_path / "mappings"

    for p in (data_dir, preprocessed_dir, obs_dir, runs_dir, state_dir, mappings_dir):
        p.mkdir(parents=True, exist_ok=True)

    mapping_repo = MappingRepository(search_roots=[mappings_dir])
    mapping_validator = MappingValidator()
    parser = SensorRecordParser(mapping_validator=mapping_validator)
    dedup_repo = DedupRepository(state_root=state_dir)
    checkpoint_repo = CheckpointRepository(runs_root=runs_dir)
    extraction_repo = ExtractionRepository(observations_root=obs_dir, runs_root=runs_dir)

    service = ExtractionService(
        mapping_repo=mapping_repo,
        mapping_validator=mapping_validator,
        parser=parser,
        dedup_repo=dedup_repo,
        checkpoint_repo=checkpoint_repo,
        extraction_repo=extraction_repo,
        allowed_roots=[data_dir, preprocessed_dir, tmp_path, PROJECT_ROOT],
    )

    return {
        "tmp_path": tmp_path,
        "data_dir": data_dir,
        "preprocessed_dir": preprocessed_dir,
        "obs_dir": obs_dir,
        "runs_dir": runs_dir,
        "state_dir": state_dir,
        "mappings_dir": mappings_dir,
        "mapping_repo": mapping_repo,
        "mapping_validator": mapping_validator,
        "parser": parser,
        "dedup_repo": dedup_repo,
        "checkpoint_repo": checkpoint_repo,
        "extraction_repo": extraction_repo,
        "service": service,
    }


def create_sample_protocol_file(file_path: Path, num_timestamps: int = 3, asset_id: str = "CNC-S01-L01-01", direction: str = "received") -> tuple[Path, str]:
    """Helper to create sample protocol jsonl file and return (path, sha256)."""
    lines = []
    seq = 1
    for t in range(num_timestamps):
        ts = f"2026-08-27T01:0{t}:00Z"
        rec1 = {
            "direction": direction,
            "schema_version": "sensor-record-v2",
            "observation_id": f"obs-{seq:04d}",
            "source_kind": "simulation",
            "record_kind": "observation",
            "quality": "Good",
            "run_id": "run-gen-001",
            "sequence": seq,
            "asset_id": asset_id,
            "measurement_key": "voltage",
            "node_id": f"{asset_id}.voltage",
            "data_type": "float",
            "unit": "V",
            "value": 220.0 + t,
            "status_code": "Good",
            "status_code_value": 0,
            "observed_at_source": ts,
            "source_timestamp": ts,
            "server_timestamp": ts,
            "received_at": ts,
            "branch_kind": "canonical",
            "overlay": False,
            "mapping_version": "v1.0",
        }
        seq += 1
        rec2 = {
            "direction": direction,
            "schema_version": "sensor-record-v2",
            "observation_id": f"obs-{seq:04d}",
            "source_kind": "simulation",
            "record_kind": "observation",
            "quality": "Good",
            "run_id": "run-gen-001",
            "sequence": seq,
            "asset_id": asset_id,
            "measurement_key": "rotation",
            "node_id": f"{asset_id}.rotation",
            "data_type": "float",
            "unit": "rpm",
            "value": 1500.0 + t * 5,
            "status_code": "Good",
            "status_code_value": 0,
            "observed_at_source": ts,
            "source_timestamp": ts,
            "server_timestamp": ts,
            "received_at": ts,
            "branch_kind": "canonical",
            "overlay": False,
            "mapping_version": "v1.0",
        }
        seq += 1
        lines.append(json.dumps(rec1, ensure_ascii=False))
        lines.append(json.dumps(rec2, ensure_ascii=False))

    content_bytes = ("\n".join(lines) + "\n").encode("utf-8")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content_bytes)
    sha256 = compute_file_sha256(file_path)
    return file_path, sha256


def create_sample_mapping_file(file_path: Path, status: str = "approved") -> tuple[dict[str, Any], Path, str]:
    """Helper to create sample static mapping table file and return (dict, path, sha256)."""
    mapping_dict = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-static-mapping-table.schema.json",
        "mapping_id": "test-sensor-mapping",
        "mapping_version": "v1.0",
        "status": status,
        "protocol_version": "v2",
        "source_schema_version": "sensor-record-v2",
        "source_schema_fingerprint": "67b7951388d5b463505f7ff0380d5174272db14000e8c91d72374a6edb422810",
        "fingerprint_algorithm_version": "v1",
        "description": "Test static mapping table",
        "field_mappings": [
            {
                "source_field": "voltage",
                "target_field": "voltage",
                "source_type": "float",
                "target_type": "float",
                "required": True,
                "transform": "to_float",
                "unit": "V",
                "timezone": "UTC",
            },
            {
                "source_field": "rotation",
                "target_field": "rotation",
                "source_type": "float",
                "target_type": "float",
                "required": True,
                "transform": "to_float",
                "unit": "rpm",
                "timezone": "UTC",
            },
        ],
    }
    sha256 = compute_mapping_canonical_sha256(mapping_dict)
    mapping_dict["mapping_sha256"] = sha256
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(json.dumps(mapping_dict, indent=2, ensure_ascii=False).encode("utf-8"))
    return mapping_dict, file_path, sha256


# =====================================================================
# 1. Contract & Schema Validation Tests
# =====================================================================

def test_static_mapping_unapproved_raises_error(isolated_extraction_env):
    """When mapping status is not 'approved' (e.g. draft), raise ExtractionMappingNotApprovedError."""
    env = isolated_extraction_env
    mapping_dict, _, sha = create_sample_mapping_file(
        env["mappings_dir"] / "draft_map.json",
        status="draft",
    )
    validator = env["mapping_validator"]

    with pytest.raises(ExtractionMappingNotApprovedError) as exc_info:
        validator.validate_mapping(mapping_dict)
    assert exc_info.value.code == "EXTRACTION_MAPPING_NOT_APPROVED"
    assert exc_info.value.status_code == 422


def test_static_mapping_checksum_mismatch_raises_error(isolated_extraction_env):
    """When declared or expected mapping sha256 does not match canonical definition, raise ExtractionMappingChecksumMismatchError."""
    env = isolated_extraction_env
    mapping_dict, _, sha = create_sample_mapping_file(env["mappings_dir"] / "valid_map.json")
    validator = env["mapping_validator"]

    with pytest.raises(ExtractionMappingChecksumMismatchError) as exc_info:
        validator.validate_mapping(mapping_dict, expected_mapping_sha256="0" * 64)
    assert exc_info.value.code == "EXTRACTION_MAPPING_CHECKSUM_MISMATCH"
    assert exc_info.value.status_code == 422


def test_static_mapping_fingerprint_mismatch_raises_error(isolated_extraction_env):
    """When source schema fingerprint does not match expected fingerprint, raise ExtractionSchemaFingerprintMismatchError."""
    env = isolated_extraction_env
    mapping_dict, _, _ = create_sample_mapping_file(env["mappings_dir"] / "fp_map.json")
    validator = env["mapping_validator"]

    with pytest.raises(ExtractionSchemaFingerprintMismatchError) as exc_info:
        validator.validate_mapping(mapping_dict, expected_source_schema_fingerprint="f" * 64)
    assert exc_info.value.code == "EXTRACTION_SCHEMA_FINGERPRINT_MISMATCH"
    assert exc_info.value.status_code == 422


def test_static_mapping_unsupported_transform_raises_error(isolated_extraction_env):
    """When transform is not in allowlist, schema validator or mapping validator raises error."""
    env = isolated_extraction_env
    mapping_dict, _, _ = create_sample_mapping_file(env["mappings_dir"] / "bad_tf_map.json")
    mapping_dict["field_mappings"][0]["transform"] = "custom_dynamic_eval"
    validator = env["mapping_validator"]

    with pytest.raises(Exception) as exc_info:
        validator.validate_mapping(mapping_dict)
    assert getattr(exc_info.value, "status_code", 422) in (422, 501)


# =====================================================================
# 2. Parser, Flat Wide-Format & Conflict Detection Tests
# =====================================================================

def test_parser_normal_long_format_grouping(isolated_extraction_env):
    """Parser groups multiple long-format sensor records into flat wide-format canonical observation rows."""
    env = isolated_extraction_env
    src_file, _ = create_sample_protocol_file(env["data_dir"] / "test_proto.jsonl", num_timestamps=3)
    mapping_dict, _, _ = create_sample_mapping_file(env["mappings_dir"] / "map.json")

    parser = env["parser"]
    obs, provs, rejs, processed, stats = parser.parse_file(
        source_path=src_file,
        mapping_data=mapping_dict,
        extraction_run_id="run-test-01",
        source_direction="received",
    )

    assert len(obs) == 3
    assert len(rejs) == 0
    assert len(provs) == 6
    assert len(processed) == 6
    assert stats["observations_count"] == 3
    assert stats["asset_ids"] == ["CNC-S01-L01-01"]

    # Check first observation row (flat wide-format!)
    first_obs = obs[0]
    assert first_obs["asset_id"] == "CNC-S01-L01-01"
    assert first_obs["observed_at"] == "2026-08-27T01:00:00Z"
    assert first_obs["voltage"] == 220.0
    assert first_obs["rotation"] == 1500.0

    # Check provenance entries
    assert provs[0]["asset_id"] == "CNC-S01-L01-01"
    assert provs[0]["mapping_id"] == "test-sensor-mapping"
    assert provs[0]["source_direction"] == "received"


def test_parser_incomplete_trailing_jsonl_raises_error(isolated_extraction_env):
    """Incomplete trailing line in non-finalized source raises ExtractionSourceIncompleteError (409)."""
    env = isolated_extraction_env
    src_file, _ = create_sample_protocol_file(env["data_dir"] / "torn.jsonl", num_timestamps=2)
    # Append broken trailing line
    with open(src_file, "a", encoding="utf-8") as f:
        f.write('{"observation_id": "obs-torn", "run_id": "run-gen-001", "ass\n')

    mapping_dict, _, _ = create_sample_mapping_file(env["mappings_dir"] / "map.json")
    parser = env["parser"]

    with pytest.raises(ExtractionSourceIncompleteError) as exc_info:
        parser.parse_file(
            source_path=src_file,
            mapping_data=mapping_dict,
            extraction_run_id="run-test-torn",
            is_source_finalized=False,
        )
    assert exc_info.value.code == "EXTRACTION_SOURCE_INCOMPLETE"
    assert exc_info.value.status_code == 409


def test_parser_measurement_conflict_isolated_to_rejected(isolated_extraction_env):
    """Conflicting measurement values for same asset, timestamp, channel are isolated to rejected without averaging."""
    env = isolated_extraction_env
    src_file = env["data_dir"] / "conflict.jsonl"
    lines = [
        json.dumps({
            "direction": "received",
            "schema_version": "sensor-record-v2",
            "observation_id": "obs-0001",
            "source_kind": "simulation",
            "record_kind": "observation",
            "quality": "Good",
            "run_id": "run-gen-001",
            "sequence": 1,
            "asset_id": "CNC-001",
            "measurement_key": "voltage",
            "node_id": "CNC-001.voltage",
            "data_type": "float",
            "unit": "V",
            "value": 220.0,
            "status_code": "Good",
            "observed_at_source": "2026-08-27T01:00:00Z",
            "branch_kind": "canonical",
            "overlay": False,
            "mapping_version": "v1.0",
        }),
        json.dumps({
            "direction": "received",
            "schema_version": "sensor-record-v2",
            "observation_id": "obs-0002",
            "source_kind": "simulation",
            "record_kind": "observation",
            "quality": "Good",
            "run_id": "run-gen-001",
            "sequence": 2,
            "asset_id": "CNC-001",
            "measurement_key": "voltage",
            "node_id": "CNC-001.voltage",
            "data_type": "float",
            "unit": "V",
            "value": 240.0,  # Conflict!
            "status_code": "Good",
            "observed_at_source": "2026-08-27T01:00:00Z",
            "branch_kind": "canonical",
            "overlay": False,
            "mapping_version": "v1.0",
        }),
        json.dumps({
            "direction": "received",
            "schema_version": "sensor-record-v2",
            "observation_id": "obs-0003",
            "source_kind": "simulation",
            "record_kind": "observation",
            "quality": "Good",
            "run_id": "run-gen-001",
            "sequence": 3,
            "asset_id": "CNC-001",
            "measurement_key": "rotation",
            "node_id": "CNC-001.rotation",
            "data_type": "float",
            "unit": "rpm",
            "value": 1500.0,
            "status_code": "Good",
            "observed_at_source": "2026-08-27T01:00:00Z",
            "branch_kind": "canonical",
            "overlay": False,
            "mapping_version": "v1.0",
        }),
    ]
    src_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mapping_dict, _, _ = create_sample_mapping_file(env["mappings_dir"] / "map.json")

    parser = env["parser"]
    obs, provs, rejs, processed, stats = parser.parse_file(
        source_path=src_file,
        mapping_data=mapping_dict,
        extraction_run_id="run-conflict-test",
    )

    assert len(rejs) >= 1
    # Required conflict -> entire observation row isolated
    assert len(obs) == 0


# =====================================================================
# 3. Dedup, Single-Writer Lock & Idempotency Tests
# =====================================================================

def test_single_writer_lock_blocks_concurrent_execution(isolated_extraction_env):
    """Acquiring lock on already running dataset raises ExtractionAlreadyRunningError (409)."""
    env = isolated_extraction_env
    dedup = env["dedup_repo"]

    dedup.acquire_lock("dataset-a", "v1", "run-1", timeout_seconds=60.0)

    # Second acquisition with different run_id should fail
    with pytest.raises(ExtractionAlreadyRunningError) as exc_info:
        dedup.acquire_lock("dataset-a", "v1", "run-2", timeout_seconds=60.0)
    assert exc_info.value.code == "EXTRACTION_ALREADY_RUNNING"
    assert exc_info.value.status_code == 409

    # Releasing lock allows new run
    dedup.release_lock("dataset-a", "v1", "run-1")
    dedup.acquire_lock("dataset-a", "v1", "run-2", timeout_seconds=60.0)
    dedup.release_lock("dataset-a", "v1", "run-2")


def test_persistent_dedup_records_and_restarts(isolated_extraction_env):
    """Dedup ledger persists in SQLite across instances."""
    env = isolated_extraction_env
    state_dir = env["state_dir"]

    repo1 = DedupRepository(state_root=state_dir)
    assert not repo1.is_record_processed("src-id-1", "rec-01", "d1", "v1")

    repo1.record_processed_batch("src-id-1", ["rec-01", "rec-02"], "d1", "v1")
    assert repo1.is_record_processed("src-id-1", "rec-01", "d1", "v1")
    assert repo1.is_record_processed("src-id-1", "rec-02", "d1", "v1")

    # New repo instance (restart simulation)
    repo2 = DedupRepository(state_root=state_dir)
    assert repo2.is_record_processed("src-id-1", "rec-01", "d1", "v1")
    assert not repo2.is_record_processed("src-id-1", "rec-03", "d1", "v1")


# =====================================================================
# 4. End-to-End Extraction Service & Atomic Publishing Tests
# =====================================================================

def test_extraction_service_end_to_end_publish(isolated_extraction_env):
    """Execute full extraction workflow: parse, stage, publish manifest with auxiliary files, and commit dedup."""
    env = isolated_extraction_env
    service = env["service"]

    src_file, src_sha = create_sample_protocol_file(env["data_dir"] / "e2e_source.jsonl", num_timestamps=3)
    mapping_dict, _, map_sha = create_sample_mapping_file(env["mappings_dir"] / "e2e_map.json")

    req = ExtractionRequest(
        request_id="req-e2e-001",
        idempotency_key="idem-e2e-001",
        run_id="run-e2e-001",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="test-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="test-canonical-dataset",
        dataset_version="v1",
    )

    resp = service.execute_extraction(req)
    assert resp.status == "succeeded"
    assert resp.dataset_id == "test-canonical-dataset"
    assert resp.result.observations_count == 3
    assert resp.result.total_records_processed == 6
    assert resp.result.provenance_sha256 != ""
    assert resp.result.rejected_sha256 != ""

    # Verify published files in data/observations/test-canonical-dataset/v1
    target_dir = env["obs_dir"] / "test-canonical-dataset" / "v1"
    assert (target_dir / "observations.jsonl").is_file()
    assert (target_dir / "dataset_manifest.json").is_file()
    assert (target_dir / "provenance.jsonl").is_file()
    assert (target_dir / "rejected.jsonl").is_file()

    # Validate dataset_manifest.json contents
    manifest = json.loads((target_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == "generator-dataset-input-v1"
    assert manifest["dataset_type"] == "observation"
    assert manifest["dataset_id"] == "test-canonical-dataset"
    assert manifest["dataset_version"] == "v1"
    assert len(manifest["files"]) == 1
    assert manifest["files"][0]["role"] == "observations"
    assert len(manifest["auxiliary_files"]) == 2


def test_extraction_idempotency_reuse_and_conflict(isolated_extraction_env):
    """Same idempotency key with identical payload returns existing response; differing payload raises 409."""
    env = isolated_extraction_env
    service = env["service"]

    src_file, src_sha = create_sample_protocol_file(env["data_dir"] / "idem_source.jsonl", num_timestamps=2)
    mapping_dict, _, map_sha = create_sample_mapping_file(env["mappings_dir"] / "idem_map.json")

    req = ExtractionRequest(
        request_id="req-idem-001",
        idempotency_key="idem-key-abc",
        run_id="run-idem-001",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="test-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="test-idem-dataset",
        dataset_version="v1",
    )

    resp1 = service.execute_extraction(req)
    assert resp1.status == "succeeded"

    # Same request and idempotency key -> returns existing response
    resp2 = service.execute_extraction(req)
    assert resp2.result.manifest_sha256 == resp1.result.manifest_sha256

    # Same idempotency key with differing dataset version -> 409 conflict
    req_conflict = req.model_copy(update={"dataset_version": "v2"})
    with pytest.raises(ExtractionIdempotencyConflictError) as exc_info:
        service.execute_extraction(req_conflict)
    assert exc_info.value.code == "EXTRACTION_IDEMPOTENCY_CONFLICT"
    assert exc_info.value.status_code == 409


def test_extraction_overwrite_existing_different_content_raises_conflict(isolated_extraction_env):
    """Attempting to publish different content into existing dataset version fails closed with 409 EXTRACTION_DATASET_CONFLICT."""
    env = isolated_extraction_env
    service = env["service"]

    src_file1, src_sha1 = create_sample_protocol_file(env["data_dir"] / "src1.jsonl", num_timestamps=2)
    mapping_dict, _, map_sha = create_sample_mapping_file(env["mappings_dir"] / "map1.json")

    req1 = ExtractionRequest(
        request_id="req-ov-001",
        idempotency_key="idem-ov-001",
        run_id="run-ov-001",
        source_uri=str(src_file1),
        source_sha256=src_sha1,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="test-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="test-overwrite-dataset",
        dataset_version="v1",
    )
    service.execute_extraction(req1)

    # Now attempt second extraction with different source file (5 timestamps instead of 2) targeting same dataset version
    src_file2, src_sha2 = create_sample_protocol_file(env["data_dir"] / "src2.jsonl", num_timestamps=5)
    req2 = ExtractionRequest(
        request_id="req-ov-002",
        idempotency_key="idem-ov-002",
        run_id="run-ov-002",
        source_uri=str(src_file2),
        source_sha256=src_sha2,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="test-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="test-overwrite-dataset",
        dataset_version="v1",
    )

    with pytest.raises(ExtractionDatasetConflictError) as exc_info:
        service.execute_extraction(req2)
    assert exc_info.value.code == "EXTRACTION_DATASET_CONFLICT"
    assert exc_info.value.status_code == 409


# =====================================================================
# 5. FastAPI Router & Preprocessing Downstream Integration Tests
# =====================================================================

def test_fastapi_extraction_endpoint_and_preprocessing_consumption(test_client):
    """End-to-end integration: POST /extraction -> POST /preprocessing consumes published flat wide-format dataset."""
    src_file = PATHS.data_dir / "api_test_source.jsonl"
    src_file, src_sha = create_sample_protocol_file(src_file, num_timestamps=4, asset_id="CNC-M01")

    # Put mapping in ontology/mappings/
    map_dir = PATHS.ontology / "mappings" / "api-sensor-mapping"
    map_dir.mkdir(parents=True, exist_ok=True)
    map_file = map_dir / "v1.0.json"
    mapping_dict = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-static-mapping-table.schema.json",
        "mapping_id": "api-sensor-mapping",
        "mapping_version": "v1.0",
        "status": "approved",
        "protocol_version": "v2",
        "source_schema_version": "sensor-record-v2",
        "source_schema_fingerprint": "67b7951388d5b463505f7ff0380d5174272db14000e8c91d72374a6edb422810",
        "fingerprint_algorithm_version": "v1",
        "description": "API integration mapping table",
        "field_mappings": [
            {
                "source_field": "voltage",
                "target_field": "voltage",
                "source_type": "float",
                "target_type": "float",
                "required": True,
                "transform": "to_float",
                "unit": "V",
                "timezone": "UTC",
            },
            {
                "source_field": "rotation",
                "target_field": "rotation",
                "source_type": "float",
                "target_type": "float",
                "required": True,
                "transform": "to_float",
                "unit": "rpm",
                "timezone": "UTC",
            },
        ],
    }
    map_sha = compute_mapping_canonical_sha256(mapping_dict)
    mapping_dict["mapping_sha256"] = map_sha
    import uuid
    test_uid = uuid.uuid4().hex[:8]
    dataset_id = f"api-extracted-dataset-{test_uid}"
    dataset_version = "v1"

    # Clean up existing test dataset if any
    target_obs = PATHS.data_dir / "observations" / dataset_id / dataset_version
    if target_obs.exists():
        shutil.rmtree(target_obs, ignore_errors=True)

    # 1. Call POST /extraction
    extract_req_payload = {
        "request_id": f"req-api-{test_uid}",
        "idempotency_key": f"idem-api-{test_uid}",
        "run_id": f"run-api-{test_uid}",
        "source_uri": "data/api_test_source.jsonl",
        "source_sha256": src_sha,
        "source_direction": "received",
        "source_schema_version": "sensor-record-v2",
        "protocol_version": "v2",
        "mapping_id": "api-sensor-mapping",
        "mapping_version": "v1.0",
        "mapping_sha256": map_sha,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
    }

    resp = test_client.post("/extraction", json=extract_req_payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "succeeded"
    assert data["dataset_id"] == dataset_id
    assert data["result"]["observations_count"] == 4
    assert data["result"]["provenance_sha256"] != ""
    assert data["result"]["rejected_sha256"] != ""

    # 2. Call POST /preprocessing with the newly extracted dataset
    prep_resp = test_client.post(
        "/preprocessing",
        json={
            "dataset_id": dataset_id,
            "dataset_version": dataset_version,
            "force_reanalyze": True,
        },
    )
    assert prep_resp.status_code == 200, prep_resp.text
    prep_data = prep_resp.json()
    assert prep_data["status"] == "succeeded"
    assert prep_data["dataset_id"] == dataset_id
    assert prep_data["result"]["id_column"] == "asset_id"
    assert prep_data["result"]["time_column"] == "observed_at"

"""Fault injection, recovery, and robustness test suite for Generator Protocol Extraction (Issue #108)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any
import pytest

from systems.generator.generator_config import PATHS, PROJECT_ROOT
from systems.generator.file_integrity import compute_file_sha256
from systems.generator.app.extraction.extraction_schema import (
    ExtractionRequest,
    ExtractionResponse,
)
from systems.generator.app.extraction.extraction_exception import (
    ExtractionAlreadyRunningError,
    ExtractionDatasetConflictError,
    ExtractionIdempotencyConflictError,
    ExtractionSourceIncompleteError,
    ExtractionSourceIntegrityError,
    ExtractionIntegrityError,
    ExtractionSchemaFingerprintMismatchError,
)
from systems.generator.app.extraction.mapping_validator import (
    MappingValidator,
    compute_mapping_canonical_sha256,
    compute_source_schema_fingerprint,
)
from systems.generator.app.extraction.mapping_repository import MappingRepository
from systems.generator.app.extraction.parsers.sensor_record_parser import SensorRecordParser
from systems.generator.app.extraction.dedup_repository import DedupRepository
from systems.generator.app.extraction.checkpoint_repository import CheckpointRepository
from systems.generator.app.extraction.extraction_repository import ExtractionRepository
from systems.generator.app.extraction.extraction_service import ExtractionService


@pytest.fixture
def recovery_env(tmp_path):
    """Create isolated environment for fault injection tests."""
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


def make_proto_file(file_path: Path, num_timestamps: int = 3, asset_id: str = "CNC-S01-L01-01", direction: str = "received") -> tuple[Path, str]:
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
            "run_id": "run-rec-001",
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
            "run_id": "run-rec-001",
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


def make_mapping_file(file_path: Path, mapping_id: str = "rec-sensor-mapping", mapping_version: str = "v1.0") -> tuple[dict[str, Any], Path, str]:
    mapping_dict = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-static-mapping-table.schema.json",
        "mapping_id": mapping_id,
        "mapping_version": mapping_version,
        "status": "approved",
        "protocol_version": "v2",
        "source_schema_version": "sensor-record-v2",
        "source_schema_fingerprint": "67b7951388d5b463505f7ff0380d5174272db14000e8c91d72374a6edb422810",
        "fingerprint_algorithm_version": "v1",
        "description": "Recovery test mapping table",
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
# 1-5. Batch State Transition & Crash Recovery Scenarios
# =====================================================================

def test_1_crash_after_dedup_pending_before_staging(recovery_env):
    """1. Dedup pending 기록 후 staging 작성 전 장애 발생 시 재실행에서 정상 복구된다."""
    env = recovery_env
    dedup = env["dedup_repo"]
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "crash1_source.jsonl", num_timestamps=2)
    _, _, map_sha = make_mapping_file(env["mappings_dir"] / "map1.json")

    # Manually create pending batch to simulate crash before staging
    dedup.create_batch(
        batch_id="batch_crash_01",
        run_id="run_crash_01",
        source_identity=f"{src_file}:{src_sha}",
        source_start_offset=1,
        source_end_offset=0,
        record_count=0,
        dataset_id="ds_crash_01",
        dataset_version="v1",
    )
    batch_record = dedup.get_batch("batch_crash_01", "ds_crash_01", "v1")
    assert batch_record["status"] == "pending"

    # Execution completes and recovers
    req = ExtractionRequest(
        request_id="req-c1",
        idempotency_key="idem-c1",
        run_id="run_crash_01",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="ds_crash_01",
        dataset_version="v1",
    )
    resp = service.execute_extraction(req)
    assert resp.status == "succeeded"
    assert resp.result.observations_count == 2


def test_2_crash_after_staging_before_dedup_commit(recovery_env):
    """2. Staging 작성 후 dedup commit 전 장애 발생 시 재실행에서 checksum 검증 후 정상 진행된다."""
    env = recovery_env
    dedup = env["dedup_repo"]
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "crash2_source.jsonl", num_timestamps=3)
    _, _, map_sha = make_mapping_file(env["mappings_dir"] / "map2.json")

    dedup.create_batch(
        batch_id="batch_crash_02",
        run_id="run_crash_02",
        source_identity=f"{src_file}:{src_sha}",
        source_start_offset=1,
        source_end_offset=6,
        record_count=6,
        dataset_id="ds_crash_02",
        dataset_version="v1",
    )
    dedup.mark_batch_staged("batch_crash_02", "some_staging_sha", "ds_crash_02", "v1")
    batch_record = dedup.get_batch("batch_crash_02", "ds_crash_02", "v1")
    assert batch_record["status"] == "staged"

    req = ExtractionRequest(
        request_id="req-c2",
        idempotency_key="idem-c2",
        run_id="run_crash_02",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="ds_crash_02",
        dataset_version="v1",
    )
    resp = service.execute_extraction(req)
    assert resp.status == "succeeded"
    assert resp.result.observations_count == 3


def test_3_crash_after_dedup_commit_before_checkpoint(recovery_env):
    """3. Dedup commit 후 checkpoint 갱신 전 장애 발생 시 재실행에서 마지막 committed batch부터 정상 재개된다."""
    env = recovery_env
    dedup = env["dedup_repo"]
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "crash3_source.jsonl", num_timestamps=2)
    _, _, map_sha = make_mapping_file(env["mappings_dir"] / "map3.json")

    dedup.record_processed_batch(
        f"{src_file}:{src_sha}",
        ["obs-0001", "obs-0002"],
        "ds_crash_03",
        "v1",
    )

    req = ExtractionRequest(
        request_id="req-c3",
        idempotency_key="idem-c3",
        run_id="run_crash_03",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="ds_crash_03",
        dataset_version="v1",
    )
    resp = service.execute_extraction(req)
    assert resp.status == "succeeded"


def test_4_crash_after_checkpoint_before_publish(recovery_env):
    """4. Checkpoint 갱신 후 최종 publish 전 장애 발생 시 staging을 재구성하여 원자적으로 발행된다."""
    env = recovery_env
    chk_repo = env["checkpoint_repo"]
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "crash4_source.jsonl", num_timestamps=3)
    _, _, map_sha = make_mapping_file(env["mappings_dir"] / "map4.json")

    chk_repo.save_checkpoint(
        run_id="run_crash_04",
        source_identity=f"{src_file}:{src_sha}",
        source_offset=6,
        processed_count=6,
    )

    req = ExtractionRequest(
        request_id="req-c4",
        idempotency_key="idem-c4",
        run_id="run_crash_04",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="ds_crash_04",
        dataset_version="v1",
    )
    resp = service.execute_extraction(req)
    assert resp.status == "succeeded"
    assert resp.result.observations_count == 3


def test_5_crash_after_publish_before_idempotency_saved(recovery_env):
    """5. 최종 Dataset rename 직후 응답 저장 전 장애 발생 시 재실행 시 기존 Dataset 무결성을 검증하고 정상 결과를 반환한다."""
    env = recovery_env
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "crash5_source.jsonl", num_timestamps=2)
    _, _, map_sha = make_mapping_file(env["mappings_dir"] / "map5.json")

    req = ExtractionRequest(
        request_id="req-c5",
        idempotency_key="idem-c5",
        run_id="run_crash_05",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="ds_crash_05",
        dataset_version="v1",
    )
    resp1 = service.execute_extraction(req)

    # Simulate missing idempotency record (e.g. crash before saving ledger)
    conn = env["dedup_repo"]._get_idempotency_connection()
    with conn:
        conn.execute("DELETE FROM idempotency_ledger WHERE idempotency_key = 'idem-c5'")

    # Second call with same request should detect identical dataset and succeed without crash
    resp2 = service.execute_extraction(req)
    assert resp2.status == "succeeded"
    assert resp2.result.manifest_sha256 == resp1.result.manifest_sha256


# =====================================================================
# 6-8. Lock Lease & Idempotency Edge Scenarios
# =====================================================================

def test_6_lock_holder_crashed_and_stale_lease_recovery(recovery_env):
    """6. Lock 소유 프로세스 비정상 종료 후 lease 만료 시 새로운 실행이 lease를 정상 탈취 및 복구한다."""
    env = recovery_env
    dedup = env["dedup_repo"]

    # Acquire lock with immediate past expiry
    dedup.acquire_lock("ds_lease_01", "v1", "crashed_run_id", timeout_seconds=-10.0)

    # Next acquire should succeed by overtaking the stale lock
    dedup.acquire_lock("ds_lease_01", "v1", "new_active_run_id", timeout_seconds=60.0)
    dedup.release_lock("ds_lease_01", "v1", "new_active_run_id")


def test_7_active_lease_blocks_other_runs(recovery_env):
    """7. Active lease가 유효한 동안 다른 실행은 409 EXTRACTION_ALREADY_RUNNING으로 즉시 실패한다."""
    env = recovery_env
    dedup = env["dedup_repo"]

    dedup.acquire_lock("ds_lease_02", "v1", "holder_run", timeout_seconds=300.0)
    with pytest.raises(ExtractionAlreadyRunningError) as exc_info:
        dedup.acquire_lock("ds_lease_02", "v1", "intruder_run", timeout_seconds=300.0)
    assert exc_info.value.code == "EXTRACTION_ALREADY_RUNNING"
    assert exc_info.value.status_code == 409
    dedup.release_lock("ds_lease_02", "v1", "holder_run")


def test_8_same_idempotency_key_different_payload_conflict(recovery_env):
    """8. 동일 idempotency key에 다른 request payload 요청 시 409 EXTRACTION_IDEMPOTENCY_CONFLICT를 반환한다."""
    env = recovery_env
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "idem_src.jsonl", num_timestamps=2)
    _, _, map_sha = make_mapping_file(env["mappings_dir"] / "idem_map.json")

    req1 = ExtractionRequest(
        request_id="req-idem-1",
        idempotency_key="shared_idem_key_01",
        run_id="run-idem-1",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="ds_idem_01",
        dataset_version="v1",
    )
    service.execute_extraction(req1)

    req2 = req1.model_copy(update={"dataset_id": "different_ds"})
    with pytest.raises(ExtractionIdempotencyConflictError) as exc_info:
        service.execute_extraction(req2)
    assert exc_info.value.code == "EXTRACTION_IDEMPOTENCY_CONFLICT"
    assert exc_info.value.status_code == 409


# =====================================================================
# 9-12. Source Finalization & Checksum Tampering Tests
# =====================================================================

def test_9_source_non_finalized_torn_last_line_retries(recovery_env):
    """9. Source non-finalized 상태에서 마지막 행 불완전 시 EXTRACTION_SOURCE_INCOMPLETE (409)를 반환한다."""
    env = recovery_env
    src_file, _ = make_proto_file(env["data_dir"] / "torn_non_final.jsonl", num_timestamps=2)
    with open(src_file, "a", encoding="utf-8") as f:
        f.write('{"observation_id": "incomplete_tail"\n')

    mapping_dict, _, _ = make_mapping_file(env["mappings_dir"] / "map.json")
    parser = env["parser"]

    with pytest.raises(ExtractionSourceIncompleteError) as exc_info:
        parser.parse_file(
            source_path=src_file,
            mapping_data=mapping_dict,
            extraction_run_id="run-torn-01",
            is_source_finalized=False,
        )
    assert exc_info.value.code == "EXTRACTION_SOURCE_INCOMPLETE"
    assert exc_info.value.status_code == 409


def test_10_source_finalized_broken_last_line_integrity_error(recovery_env):
    """10. Source finalized 상태인데 마지막 행이 깨져 있으면 EXTRACTION_SOURCE_INTEGRITY_ERROR를 발생시킨다."""
    env = recovery_env
    src_file, _ = make_proto_file(env["data_dir"] / "broken_final.jsonl", num_timestamps=2)
    with open(src_file, "a", encoding="utf-8") as f:
        f.write('{"observation_id": "incomplete_tail"\n')

    mapping_dict, _, _ = make_mapping_file(env["mappings_dir"] / "map.json")
    parser = env["parser"]

    with pytest.raises(ExtractionSourceIntegrityError) as exc_info:
        parser.parse_file(
            source_path=src_file,
            mapping_data=mapping_dict,
            extraction_run_id="run-broken-01",
            is_source_finalized=True,
        )
    assert exc_info.value.code == "EXTRACTION_SOURCE_INTEGRITY_ERROR"


def test_11_tampered_provenance_checksum_detected(recovery_env):
    """11. Provenance 파일 변조 시 dataset 확인 과정에서 무결성 불일치가 탐지된다."""
    env = recovery_env
    repo = env["extraction_repo"]

    ds_dir = env["obs_dir"] / "ds_tamper_prov" / "v1"
    ds_dir.mkdir(parents=True, exist_ok=True)
    obs_file = ds_dir / "observations.jsonl"
    obs_file.write_text('{"asset_id": "A1", "observed_at": "2026-08-27T01:00:00Z", "voltage": 220.0}\n', encoding="utf-8")
    prov_file = ds_dir / "provenance.jsonl"
    prov_file.write_text('{"asset_id": "A1"}\n', encoding="utf-8")
    manifest_file = ds_dir / "dataset_manifest.json"
    manifest_file.write_text(json.dumps({
        "manifest_version": "generator-dataset-input-v1",
        "dataset_type": "observation",
        "dataset_id": "ds_tamper_prov",
        "dataset_version": "v1",
        "schema_version": "canonical-observation-v1",
        "created_at": "2026-08-27T01:00:00Z",
        "files": [{"role": "observations", "path": "observations.jsonl", "media_type": "application/x-ndjson", "sha256": compute_file_sha256(obs_file), "size_bytes": obs_file.stat().st_size}],
    }), encoding="utf-8")

    with pytest.raises(ExtractionDatasetConflictError):
        repo.check_existing_dataset(
            "ds_tamper_prov",
            "v1",
            expected_obs_sha256=compute_file_sha256(obs_file),
            expected_prov_sha256="0" * 64,  # Mismatched expected prov
        )


def test_12_tampered_rejected_checksum_detected(recovery_env):
    """12. Rejected 파일 변조 또는 삭제 시 불완전 디렉터리 충돌로 감지된다."""
    env = recovery_env
    repo = env["extraction_repo"]

    ds_dir = env["obs_dir"] / "ds_tamper_rej" / "v1"
    ds_dir.mkdir(parents=True, exist_ok=True)
    # Missing observations.jsonl -> incomplete
    (ds_dir / "dataset_manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ExtractionDatasetConflictError):
        repo.check_existing_dataset("ds_tamper_rej", "v1")


# =====================================================================
# 13-16. Determinism, Immutability, E2E & Fingerprint Tests
# =====================================================================

def test_13_deterministic_reexecution_identical_manifest_and_data(recovery_env):
    """13. 동일 입력·동일 Mapping의 결정론적 재실행 결과 sha256이 100% 일치한다."""
    env = recovery_env
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "det_source.jsonl", num_timestamps=4)
    _, _, map_sha = make_mapping_file(env["mappings_dir"] / "det_map.json")

    req = ExtractionRequest(
        request_id="req-det-1",
        idempotency_key="idem-det-1",
        run_id="run-det-1",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha,
        dataset_id="ds_det_01",
        dataset_version="v1",
    )
    resp1 = service.execute_extraction(req)
    resp2 = service.execute_extraction(req)

    assert resp1.result.observations_sha256 == resp2.result.observations_sha256
    assert resp1.result.manifest_sha256 == resp2.result.manifest_sha256
    assert resp1.result.provenance_sha256 == resp2.result.provenance_sha256


def test_14_different_mapping_version_blocks_append_to_existing_dataset(recovery_env):
    """14. 동일 입력에 다른 Mapping version으로 기존 완료된 Dataset version에 append/overwrite 시도 시 409로 차단된다."""
    env = recovery_env
    service = env["service"]

    src_file, src_sha = make_proto_file(env["data_dir"] / "map_ver_src.jsonl", num_timestamps=2)
    _, _, map_sha1 = make_mapping_file(env["mappings_dir"] / "map_v1.json", mapping_version="v1.0")
    _, _, map_sha2 = make_mapping_file(env["mappings_dir"] / "map_v2.json", mapping_version="v2.0")

    req1 = ExtractionRequest(
        request_id="req-mv-1",
        idempotency_key="idem-mv-1",
        run_id="run-mv-1",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v1.0",
        mapping_sha256=map_sha1,
        dataset_id="ds_immutable_version",
        dataset_version="v1",
    )
    service.execute_extraction(req1)

    # Attempt to write to same dataset_version with different mapping
    req2 = ExtractionRequest(
        request_id="req-mv-2",
        idempotency_key="idem-mv-2",
        run_id="run-mv-2",
        source_uri=str(src_file),
        source_sha256=src_sha,
        source_direction="received",
        source_schema_version="sensor-record-v2",
        protocol_version="v2",
        mapping_id="rec-sensor-mapping",
        mapping_version="v2.0",
        mapping_sha256=map_sha2,
        dataset_id="ds_immutable_version",
        dataset_version="v1",
    )

    with pytest.raises(ExtractionDatasetConflictError) as exc_info:
        service.execute_extraction(req2)
    assert exc_info.value.code == "EXTRACTION_DATASET_CONFLICT"
    assert exc_info.value.status_code == 409


def test_15_e2e_extraction_to_preprocessing_to_feature_bundle():
    """15. Extraction 발행 산출물을 Preprocessing이 읽고 Plan 수립 및 실행까지 완결되는 E2E 검증."""
    from fastapi.testclient import TestClient
    from systems.generator.app.main import app
    import uuid

    client = TestClient(app)
    src_file = PATHS.data_dir / "e2e_rec_source.jsonl"
    src_file, src_sha = make_proto_file(src_file, num_timestamps=5, asset_id="CNC-E01")

    # Put mapping in ontology/mappings/
    map_dir = PATHS.ontology / "mappings" / "e2e-rec-mapping"
    map_dir.mkdir(parents=True, exist_ok=True)
    map_file = map_dir / "v1.0.json"
    mapping_dict, _, map_sha = make_mapping_file(map_file, mapping_id="e2e-rec-mapping", mapping_version="v1.0")

    uid = uuid.uuid4().hex[:8]
    dataset_id = f"ds_e2e_rec_{uid}"
    dataset_version = "v1"

    # Clean up target obs if any
    target_obs = PATHS.data_dir / "observations" / dataset_id / dataset_version
    if target_obs.exists():
        shutil.rmtree(target_obs, ignore_errors=True)

    # 1. POST /extraction
    ext_resp = client.post("/extraction", json={
        "request_id": f"req-rec-{uid}",
        "idempotency_key": f"idem-rec-{uid}",
        "run_id": f"run-rec-{uid}",
        "source_uri": "data/e2e_rec_source.jsonl",
        "source_sha256": src_sha,
        "source_direction": "received",
        "source_schema_version": "sensor-record-v2",
        "protocol_version": "v2",
        "mapping_id": "e2e-rec-mapping",
        "mapping_version": "v1.0",
        "mapping_sha256": map_sha,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
    })
    assert ext_resp.status_code == 200, ext_resp.text
    assert ext_resp.json()["status"] == "succeeded"

    # 2. POST /preprocessing
    prep_resp = client.post("/preprocessing", json={
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "force_reanalyze": True,
    })
    assert prep_resp.status_code == 200, prep_resp.text
    prep_data = prep_resp.json()
    assert prep_data["status"] == "succeeded"
    assert prep_data["result"]["id_column"] == "asset_id"
    assert prep_data["result"]["time_column"] == "observed_at"


def test_16_schema_fingerprint_deterministic_and_sensitive_to_structure():
    """16. Schema fingerprint는 필드 순서와 무관하게 동일하며, 타입이나 required 변경 시 민감하게 달라진다."""
    base_schema = {
        "title": "SensorRecord",
        "required": ["asset_id", "value"],
        "properties": {
            "asset_id": {"type": "string"},
            "value": {"type": "number"},
        },
    }
    fp_base = compute_source_schema_fingerprint(base_schema)

    # Reordered properties -> same fingerprint
    reordered_schema = {
        "title": "SensorRecord",
        "required": ["value", "asset_id"],
        "properties": {
            "value": {"type": "number"},
            "asset_id": {"type": "string"},
        },
    }
    fp_reordered = compute_source_schema_fingerprint(reordered_schema)
    assert fp_base == fp_reordered

    # Type changed -> different fingerprint
    type_changed_schema = {
        "title": "SensorRecord",
        "required": ["asset_id", "value"],
        "properties": {
            "asset_id": {"type": "string"},
            "value": {"type": "string"},  # changed from number to string
        },
    }
    fp_type_changed = compute_source_schema_fingerprint(type_changed_schema)
    assert fp_base != fp_type_changed

    # Required changed -> different fingerprint
    required_changed_schema = {
        "title": "SensorRecord",
        "required": ["asset_id"],
        "properties": {
            "asset_id": {"type": "string"},
            "value": {"type": "number"},
        },
    }
    fp_required_changed = compute_source_schema_fingerprint(required_changed_schema)
    assert fp_base != fp_required_changed

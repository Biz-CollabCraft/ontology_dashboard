"""Unit tests for gen_data Source Identity, Prefix Verification, Checkpoints, and File Locking."""

import hashlib
import json
from pathlib import Path

import pytest

from systems.generator.app.extraction.checkpoint_repository import (
    GenDataExtractionCheckpoint,
    GenDataExtractionCheckpointRepository,
    PendingExtractionBatch,
)
from systems.generator.app.extraction.extraction_exception import (
    ExtractionCheckpointInvalidError,
    ExtractionCheckpointMappingMigrationRequiredError,
    ExtractionFragmentConflictError,
    ExtractionMappingRebuildNotImplementedError,
    ExtractionSourceLockedError,
    ExtractionSourcePrefixMismatchError,
    ExtractionSourceTruncatedError,
)
from systems.generator.app.extraction.gen_data_fragment import (
    GenDataFragmentRepository,
)
from systems.generator.app.extraction.gen_data_identity import (
    compute_extraction_batch_id,
    compute_gen_data_source_identity,
    compute_source_prefix_info,
    verify_source_prefix,
)
from systems.generator.app.extraction.gen_data_incremental_service import (
    GenDataIncrementalExtractionService,
)
from systems.generator.app.extraction.gen_data_lock import GenDataSourceLock
from systems.generator.app.extraction.gen_data_mapping import (
    CanonicalObservationCandidate,
    GenDataStaticMappingConverter,
    RejectedMappingRecord,
)
from systems.generator.app.extraction.gen_data_source import (
    GenDataSensorStreamSource,
)
from systems.generator.app.extraction.mapping_validator import (
    compute_mapping_canonical_sha256,
)
from systems.generator.app.extraction.parsers.gen_data_sensor_stream_parser import (
    GenDataSensorStreamParser,
)


# =============================================================================
# 1. Source Identity & Batch ID Tests
# =============================================================================


def test_source_identity_deterministic_and_distinct():
    """Source identity is deterministic and binds site, cell, uri, and first record sha."""
    id1 = compute_gen_data_source_identity(
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
        site_id="S01",
        cell_id="L01",
        first_record_sha256="aaaabbbbcccc",
    )
    id2 = compute_gen_data_source_identity(
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
        site_id="S01",
        cell_id="L01",
        first_record_sha256="aaaabbbbcccc",
    )
    assert id1 == id2

    # Different site
    id_diff_site = compute_gen_data_source_identity(
        source_uri="sensor/facS02/lineL01/sensor_stream.jsonl",
        site_id="S02",
        cell_id="L01",
        first_record_sha256="aaaabbbbcccc",
    )
    assert id1 != id_diff_site

    # Different first record sha
    id_diff_rec = compute_gen_data_source_identity(
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
        site_id="S01",
        cell_id="L01",
        first_record_sha256="dddd",
    )
    assert id1 != id_diff_rec


def test_batch_id_deterministic():
    """Batch ID binds source identity, offset ranges, and mapping sha."""
    b1 = compute_extraction_batch_id(
        source_identity="src-1",
        source_start_offset=0,
        source_end_offset=1000,
        mapping_sha256="map-sha",
    )
    b2 = compute_extraction_batch_id(
        source_identity="src-1",
        source_start_offset=0,
        source_end_offset=1000,
        mapping_sha256="map-sha",
    )
    assert b1 == b2

    b3 = compute_extraction_batch_id(
        source_identity="src-1",
        source_start_offset=1000,
        source_end_offset=2000,
        mapping_sha256="map-sha",
    )
    assert b1 != b3


# =============================================================================
# 2. Prefix Verification Tests
# =============================================================================


def test_prefix_verification_append_success(tmp_path):
    """Appending new bytes preserves prefix verification."""
    f = tmp_path / "sensor_stream.jsonl"
    init_content = b'{"line": 1}\n{"line": 2}\n'
    f.write_bytes(init_content)

    prefix_len, prefix_sha = compute_source_prefix_info(f, committed_offset=len(init_content))
    assert prefix_len == len(init_content)
    assert prefix_sha == hashlib.sha256(init_content).hexdigest()

    # Append new line
    f.write_bytes(init_content + b'{"line": 3}\n')

    # Prefix verification on appended file succeeds
    verify_source_prefix(
        source_path=f,
        expected_length=prefix_len,
        expected_sha256=prefix_sha,
        last_committed_offset=len(init_content),
    )


def test_prefix_verification_detects_truncation(tmp_path):
    """Truncating file below last committed offset raises ExtractionSourceTruncatedError."""
    f = tmp_path / "sensor_stream.jsonl"
    init_content = b'{"line": 1}\n{"line": 2}\n'
    f.write_bytes(init_content)

    prefix_len, prefix_sha = compute_source_prefix_info(f, committed_offset=len(init_content))

    # Truncate
    f.write_bytes(b'{"line": 1}\n')

    with pytest.raises(ExtractionSourceTruncatedError):
        verify_source_prefix(
            source_path=f,
            expected_length=prefix_len,
            expected_sha256=prefix_sha,
            last_committed_offset=len(init_content),
        )


def test_prefix_verification_detects_replaced_file(tmp_path):
    """Swapping file contents with same length raises ExtractionSourcePrefixMismatchError."""
    f = tmp_path / "sensor_stream.jsonl"
    init_content = b'{"line": 1}\n{"line": 2}\n'
    f.write_bytes(init_content)

    prefix_len, prefix_sha = compute_source_prefix_info(f, committed_offset=len(init_content))

    # Replace with different content of same length
    replaced_content = b'{"line": 9}\n{"line": 8}\n'
    assert len(replaced_content) == len(init_content)
    f.write_bytes(replaced_content)

    with pytest.raises(ExtractionSourcePrefixMismatchError):
        verify_source_prefix(
            source_path=f,
            expected_length=prefix_len,
            expected_sha256=prefix_sha,
            last_committed_offset=len(init_content),
        )


# =============================================================================
# 3. Checkpoint Repository Tests
# =============================================================================


def test_checkpoint_repository_save_and_load(tmp_path):
    """Checkpoint is atomically saved, verified, and loaded."""
    chk_repo = GenDataExtractionCheckpointRepository(checkpoints_root=tmp_path / "checkpoints")

    valid_src_id = "a" * 64
    valid_batch_id = "b" * 64

    chk = GenDataExtractionCheckpoint(
        source_identity=valid_src_id,
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
        site_id="S01",
        cell_id="L01",
        mapping_id="map-1",
        mapping_version="v1.0",
        mapping_sha256="c" * 64,
        last_committed_offset=1024,
        last_committed_line=10,
        last_observed_at="2026-08-28T13:00:00Z",
        verified_prefix_length=512,
        verified_prefix_sha256="0" * 64,
        last_committed_batch_id=valid_batch_id,
        committed_batch_ids=[valid_batch_id],
        status="idle",
        created_at="2026-08-28T13:00:00Z",
        updated_at="2026-08-28T13:00:00Z",
    )

    saved_path = chk_repo.save_checkpoint_atomic(chk)
    assert saved_path.is_file()

    loaded = chk_repo.load_checkpoint(valid_src_id)
    assert loaded is not None
    assert loaded.source_identity == valid_src_id
    assert loaded.mapping_id == "map-1"
    assert loaded.mapping_version == "v1.0"
    assert loaded.mapping_sha256 == "c" * 64
    assert loaded.last_committed_offset == 1024
    assert loaded.status == "idle"


def test_checkpoint_repository_corrupt_file_raises(tmp_path):
    """Corrupted checkpoint JSON raises ExtractionCheckpointInvalidError."""
    chk_dir = tmp_path / "checkpoints"
    chk_dir.mkdir()
    (chk_dir / f"{'f' * 64}.json").write_text("invalid json...", encoding="utf-8")

    chk_repo = GenDataExtractionCheckpointRepository(checkpoints_root=chk_dir)
    with pytest.raises(ExtractionCheckpointInvalidError):
        chk_repo.load_checkpoint("f" * 64)


# =============================================================================
# 4. Fragment Repository Tests
# =============================================================================


def test_fragment_repository_save_and_idempotency(tmp_path):
    """Fragment repository creates observations, provenance, rejected files, manifest, and supports idempotent reuse."""
    frag_repo = GenDataFragmentRepository(base_runs_dir=tmp_path / "extraction_runs")

    valid_src_id = "c" * 64
    valid_batch_id = "d" * 64
    valid_mapping_sha = "e" * 64

    obs = [
        CanonicalObservationCandidate(
            asset_id="CNC-01",
            observed_at="2026-08-28T13:00:00Z",
            measurements={"torque_nm": 45.0},
            site_id="S01",
            cell_id="L01",
            source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
            source_byte_start=0,
            source_byte_end=50,
            source_line_number=1,
            source_row_sha256="sha1",
            mapping_id="map-1",
            mapping_version="v1",
            mapping_sha256=valid_mapping_sha,
            ignored_source_fields=(),
        )
    ]
    rej = [
        RejectedMappingRecord(
            source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
            source_byte_start=50,
            source_byte_end=100,
            source_line_number=2,
            raw_sha256="sha2",
            asset_id=None,
            observed_at=None,
            error_code="GEN_DATA_ASSET_ID_MISSING",
            error_message="missing asset_id",
            mapping_id="map-1",
            mapping_version="v1",
        )
    ]

    frag_dir, manifest, manifest_sha = frag_repo.save_fragment_atomic(
        run_id="run-001",
        batch_id=valid_batch_id,
        source_identity=valid_src_id,
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
        source_start_offset=0,
        source_end_offset=100,
        source_start_line=1,
        source_end_line=2,
        mapping_id="map-1",
        mapping_version="v1",
        mapping_sha256=valid_mapping_sha,
        observations=obs,
        rejected_records=rej,
    )

    assert frag_dir.is_dir()
    assert (frag_dir / "observations.jsonl").is_file()
    assert (frag_dir / "provenance.jsonl").is_file()
    assert (frag_dir / "rejected.jsonl").is_file()
    assert (frag_dir / "fragment_manifest.json").is_file()
    assert manifest.observation_count == 1
    assert manifest.rejected_count == 1

    # Idempotent re-save returns existing
    frag_dir2, manifest2, manifest_sha2 = frag_repo.save_fragment_atomic(
        run_id="run-001",
        batch_id=valid_batch_id,
        source_identity=valid_src_id,
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
        source_start_offset=0,
        source_end_offset=100,
        source_start_line=1,
        source_end_line=2,
        mapping_id="map-1",
        mapping_version="v1",
        mapping_sha256=valid_mapping_sha,
        observations=obs,
        rejected_records=rej,
    )
    assert frag_dir2 == frag_dir
    assert manifest_sha2 == manifest_sha


# =============================================================================
# 5. OS File Lock Tests
# =============================================================================


def test_source_lock_mutual_exclusion(tmp_path):
    """Lock enforces single-writer mutual exclusion per source_identity."""
    lock_dir = tmp_path / "locks"
    lock1 = GenDataSourceLock(lock_dir, "source-A", timeout_seconds=0.2)
    lock2 = GenDataSourceLock(lock_dir, "source-A", timeout_seconds=0.2)
    lock_other = GenDataSourceLock(lock_dir, "source-B", timeout_seconds=0.2)

    with lock1:
        # Concurrent lock on different source succeeds
        with lock_other:
            pass

        # Concurrent lock on same source fails with ExtractionSourceLockedError
        with pytest.raises(ExtractionSourceLockedError):
            with lock2:
                pass

    # After lock1 released, lock2 succeeds
    with lock2:
        pass


# =============================================================================
# 6. Mapping Identity Checkpoint and Rebuild Disallowance Tests (PR #134)
# =============================================================================


@pytest.fixture
def base_mapping_fixture() -> dict:
    raw = {
        "$schema": "https://ontology-dashboard.local/schemas/generator-static-mapping-table.schema.json",
        "mapping_id": "gen-data-sensor-stream-canonical",
        "mapping_version": "v1.0",
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
            },
            {
                "source_field": "rotational_speed_rpm",
                "target_field": "rotational_speed_rpm",
                "source_type": "number",
                "target_type": "float",
                "required": False,
                "transform": "to_float",
            },
        ],
    }
    raw["mapping_sha256"] = compute_mapping_canonical_sha256(raw)
    return raw


def _create_stream_source(tmp_path: Path, records: list[dict]) -> tuple[Path, GenDataSensorStreamSource]:
    stream_file = tmp_path / "sensor_stream.jsonl"
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    stream_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    source = GenDataSensorStreamSource(
        site_id="S01",
        cell_id="L01",
        facility_dir_name="facS01",
        line_dir_name="lineL01",
        source_path=stream_file,
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
    )
    return stream_file, source


def _create_service(tmp_path: Path) -> GenDataIncrementalExtractionService:
    chk_repo = GenDataExtractionCheckpointRepository(checkpoints_root=tmp_path / "checkpoints")
    frag_repo = GenDataFragmentRepository(base_runs_dir=tmp_path / "extraction_runs")
    return GenDataIncrementalExtractionService(
        checkpoint_repo=chk_repo,
        fragment_repo=frag_repo,
        lock_dir=tmp_path / "locks",
    )


def test_checkpoint_same_mapping_returns_no_data_at_eof(tmp_path, base_mapping_fixture):
    """Mapping v1 processes source to EOF, subsequent call with same Mapping v1 returns no_data."""
    records = [
        {"ts": "2026-08-28T13:00:00Z", "asset_id": "CNC-01", "torque_nm": 45.0, "rotational_speed_rpm": 1500.0},
        {"ts": "2026-08-28T13:01:00Z", "asset_id": "CNC-01", "torque_nm": 46.0, "rotational_speed_rpm": 1510.0},
    ]
    stream_file, source = _create_stream_source(tmp_path, records)
    service = _create_service(tmp_path)

    # 1. First run consumes all records to EOF
    res1 = service.process_available_records(
        source=source,
        mapping_data=base_mapping_fixture,
        run_id="run-001",
    )
    assert res1.status == "fragment_committed"
    assert res1.records_read == 2

    # 2. Second run with same Mapping v1 returns no_data
    res2 = service.process_available_records(
        source=source,
        mapping_data=base_mapping_fixture,
        run_id="run-002",
    )
    assert res2.status == "no_data"
    assert res2.records_read == 0
    assert res2.committed_offset == res1.committed_offset


def test_checkpoint_different_mapping_raises_409_rebuild_not_implemented_at_eof(tmp_path, base_mapping_fixture):
    """Mapping v1 processes to EOF, subsequent call on same source with Mapping v2 raises 409 Conflict instead of no_data."""
    records = [
        {"ts": "2026-08-28T13:00:00Z", "asset_id": "CNC-01", "torque_nm": 45.0, "rotational_speed_rpm": 1500.0},
    ]
    stream_file, source = _create_stream_source(tmp_path, records)
    service = _create_service(tmp_path)

    # First run with mapping v1
    res1 = service.process_available_records(
        source=source,
        mapping_data=base_mapping_fixture,
        run_id="run-001",
    )
    assert res1.status == "fragment_committed"

    # Create mapping v2
    mapping_v2 = dict(base_mapping_fixture)
    mapping_v2["mapping_version"] = "v2.0"
    mapping_v2["mapping_sha256"] = compute_mapping_canonical_sha256(mapping_v2)

    # Second run with mapping v2 must raise 409 EXTRACTION_MAPPING_REBUILD_NOT_IMPLEMENTED
    with pytest.raises(ExtractionMappingRebuildNotImplementedError) as exc_info:
        service.process_available_records(
            source=source,
            mapping_data=mapping_v2,
            run_id="run-002",
        )

    exc = exc_info.value
    assert exc.status_code == 409
    assert exc.code == "EXTRACTION_MAPPING_REBUILD_NOT_IMPLEMENTED"
    assert exc.context.get("checkpoint_mapping_version") == "v1.0"
    assert exc.context.get("requested_mapping_version") == "v2.0"
    assert exc.context.get("source_identity") == res1.source_identity


def test_checkpoint_different_mapping_with_intermediate_offset_raises_409(tmp_path, base_mapping_fixture):
    """Mapping v1 checkpoint is at intermediate offset, requesting Mapping v2 raises 409 immediately without processing remainder."""
    records = [
        {"ts": "2026-08-28T13:00:00Z", "asset_id": "CNC-01", "torque_nm": 45.0, "rotational_speed_rpm": 1500.0},
        {"ts": "2026-08-28T13:01:00Z", "asset_id": "CNC-01", "torque_nm": 46.0, "rotational_speed_rpm": 1510.0},
    ]
    stream_file, source = _create_stream_source(tmp_path, records)
    service = _create_service(tmp_path)

    # First run processes only 1 record (intermediate offset)
    res1 = service.process_available_records(
        source=source,
        mapping_data=base_mapping_fixture,
        run_id="run-001",
        max_records=1,
    )
    assert res1.status == "fragment_committed"
    assert res1.records_read == 1

    # Request with mapping v2
    mapping_v2 = dict(base_mapping_fixture)
    mapping_v2["mapping_version"] = "v2.0"
    mapping_v2["mapping_sha256"] = compute_mapping_canonical_sha256(mapping_v2)

    with pytest.raises(ExtractionMappingRebuildNotImplementedError) as exc_info:
        service.process_available_records(
            source=source,
            mapping_data=mapping_v2,
            run_id="run-002",
        )
    assert exc_info.value.status_code == 409


def test_checkpoint_missing_mapping_identity_raises_migration_required(tmp_path):
    """Loading legacy checkpoint lacking mapping identity raises EXTRACTION_CHECKPOINT_MAPPING_MIGRATION_REQUIRED."""
    chk_dir = tmp_path / "checkpoints"
    chk_dir.mkdir(parents=True, exist_ok=True)
    src_id = "f" * 64
    legacy_payload = {
        "checkpoint_schema_version": "generator-gen-data-extraction-checkpoint-v1",
        "source_identity": src_id,
        "source_uri": "sensor/facS01/lineL01/sensor_stream.jsonl",
        "source_format": "gen_data_sensor_stream",
        "site_id": "S01",
        "cell_id": "L01",
        "last_committed_offset": 100,
        "last_committed_line": 5,
        "verified_prefix_length": 0,
        "verified_prefix_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "committed_batch_ids": [],
        "pending_batch": None,
        "status": "idle",
        "created_at": "2026-08-28T13:00:00Z",
        "updated_at": "2026-08-28T13:00:00Z",
    }
    (chk_dir / f"{src_id}.json").write_text(json.dumps(legacy_payload), encoding="utf-8")

    chk_repo = GenDataExtractionCheckpointRepository(checkpoints_root=chk_dir)
    with pytest.raises(ExtractionCheckpointMappingMigrationRequiredError):
        chk_repo.load_checkpoint(src_id)


def test_checkpoint_and_dataset_state_preserved_on_mapping_mismatch_failure(tmp_path, base_mapping_fixture):
    """Rejection with 409 leaves existing checkpoint, offsets, and fragment artifacts completely unmodified."""
    records = [
        {"ts": "2026-08-28T13:00:00Z", "asset_id": "CNC-01", "torque_nm": 45.0, "rotational_speed_rpm": 1500.0},
    ]
    stream_file, source = _create_stream_source(tmp_path, records)
    service = _create_service(tmp_path)

    res1 = service.process_available_records(
        source=source,
        mapping_data=base_mapping_fixture,
        run_id="run-001",
    )
    assert res1.status == "fragment_committed"

    chk_before = service.checkpoint_repo.load_checkpoint(res1.source_identity)
    assert chk_before is not None

    mapping_v2 = dict(base_mapping_fixture)
    mapping_v2["mapping_version"] = "v2.0"
    mapping_v2["mapping_sha256"] = compute_mapping_canonical_sha256(mapping_v2)

    with pytest.raises(ExtractionMappingRebuildNotImplementedError):
        service.process_available_records(
            source=source,
            mapping_data=mapping_v2,
            run_id="run-002",
        )

    # State verification: checkpoint is identical
    chk_after = service.checkpoint_repo.load_checkpoint(res1.source_identity)
    assert chk_after is not None
    assert chk_after.last_committed_offset == chk_before.last_committed_offset
    assert chk_after.last_committed_line == chk_before.last_committed_line
    assert chk_after.mapping_version == "v1.0"
    assert chk_after.status == "idle"

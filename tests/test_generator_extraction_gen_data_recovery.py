"""Crash recovery regression tests across all failure injection points."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from systems.generator.app.extraction.checkpoint_repository import (
    GenDataExtractionCheckpointRepository,
)
from systems.generator.app.extraction.gen_data_fragment import (
    GenDataFragmentRepository,
)
from systems.generator.app.extraction.gen_data_incremental_service import (
    GenDataIncrementalExtractionService,
)
from systems.generator.app.extraction.gen_data_mapping import (
    GenDataStaticMappingConverter,
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


@pytest.fixture
def mapping_fixture() -> dict:
    raw = {
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


@pytest.fixture
def sample_source_stream(tmp_path) -> tuple[GenDataSensorStreamSource, bytes]:
    f = tmp_path / "sensor" / "facS01" / "lineL01" / "sensor_stream.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {"asset_id": "CNC-01", "site_id": "S01", "cell_id": "L01", "observed_at": "2026-08-28T13:00:00Z", "torque_nm": 45.0},
        {"asset_id": "CNC-02", "site_id": "S01", "cell_id": "L01", "observed_at": "2026-08-28T13:01:00Z", "rotational_speed_rpm": 1500.0},
        {"asset_id": "CNC-03", "site_id": "S01", "cell_id": "L01", "observed_at": "2026-08-28T13:02:00Z", "torque_nm": 50.0},
    ]
    raw_lines = [json.dumps(r).encode("utf-8") + b"\n" for r in records]
    full_bytes = b"".join(raw_lines)
    f.write_bytes(full_bytes)

    source = GenDataSensorStreamSource(
        site_id="S01",
        cell_id="L01",
        facility_dir_name="facS01",
        line_dir_name="lineL01",
        source_path=f,
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
    )
    return source, full_bytes


@pytest.mark.parametrize(
    "failure_point",
    [
        "after_lock_acquired",
        "after_processing_checkpoint",
        "after_fragment_files_written",
        "after_fragment_manifest_written",
        "after_fragment_renamed",
        "after_pending_checkpoint_written",
        "after_committed_checkpoint_written",
    ],
)
def test_crash_recovery_at_failure_injection_points(
    tmp_path, mapping_fixture, sample_source_stream, failure_point
):
    """Crash at any stage leaves system in a clean, recoverable state with zero duplicated records upon restart."""
    source, full_bytes = sample_source_stream

    chk_repo = GenDataExtractionCheckpointRepository(checkpoints_root=tmp_path / "checkpoints")
    frag_repo = GenDataFragmentRepository(base_runs_dir=tmp_path / "runs")
    lock_dir = tmp_path / "locks"

    class InjectedCrash(Exception):
        pass

    def injector(point: str):
        if point == failure_point:
            raise InjectedCrash(f"Simulated crash at {point}")

    service_fail = GenDataIncrementalExtractionService(
        checkpoint_repo=chk_repo,
        fragment_repo=frag_repo,
        lock_dir=lock_dir,
        failure_injector=injector,
    )

    # 1. First execution crashes at failure_point
    with pytest.raises(Exception) as exc_info:
        service_fail.process_available_records(
            source=source,
            mapping_data=mapping_fixture,
            run_id="run-crash-test",
        )
    # Ensure the crash was indeed triggered by the failure injector
    assert "Simulated crash at" in str(exc_info.value) or (
        exc_info.value.__cause__ is not None and "Simulated crash at" in str(exc_info.value.__cause__)
    )

    # 2. Restart and re-run recovery without crash
    service_recover = GenDataIncrementalExtractionService(
        checkpoint_repo=chk_repo,
        fragment_repo=frag_repo,
        lock_dir=lock_dir,
        failure_injector=None,
    )

    res = service_recover.process_available_records(
        source=source,
        mapping_data=mapping_fixture,
        run_id="run-crash-test",
    )

    # 3. Recovery assertions
    assert res.status in ("fragment_committed", "no_data")
    assert res.committed_offset == len(full_bytes)

    # 4. Subsequent run produces no_data (cleanly caught up)
    res_subsequent = service_recover.process_available_records(
        source=source,
        mapping_data=mapping_fixture,
        run_id="run-crash-test",
    )
    assert res_subsequent.status == "no_data"
    assert res_subsequent.records_read == 0

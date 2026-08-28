"""Unit and integration tests for Immutable Dataset Bundle Publishing and FeatureInputResolver compatibility."""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from systems.generator.app.extraction.extraction_exception import (
    ExtractionDatasetConflictError,
    ExtractionNoValidObservationsError,
)
from systems.generator.app.extraction.window_assembler import (
    AssembledExtractionWindow,
    FragmentReference,
)
from systems.generator.app.extraction.window_publisher import (
    ExtractionWindowPublisher,
)
from systems.generator.app.feature.feature_input_resolver import (
    FeatureInputResolver,
)


@pytest.fixture
def sample_assembled_window() -> AssembledExtractionWindow:
    return AssembledExtractionWindow(
        source_identity="f" * 64,
        source_uri="sensor/facS01/lineL01/sensor_stream.jsonl",
        site_id="S01",
        cell_id="L01",
        dataset_id="gen-data-S01-L01",
        dataset_version="window-20260828T130000Z-map-a1b2c3d4",
        window_start="2026-08-28T13:00:00Z",
        window_end="2026-08-28T14:00:00Z",
        mapping_id="gen-data-sensor-stream-canonical",
        mapping_version="v1",
        mapping_sha256="a1b2c3d4" + "0" * 56,
        observations=[
            {
                "asset_id": "CNC-01",
                "observed_at": "2026-08-28T13:00:00Z",
                "torque_nm": 45.0,
            }
        ],
        provenance_records=[
            {
                "asset_id": "CNC-01",
                "observed_at": "2026-08-28T13:00:00Z",
                "source_uri": "sensor/facS01/lineL01/sensor_stream.jsonl",
                "source_byte_start": 0,
                "source_byte_end": 50,
                "source_line_number": 1,
                "source_row_sha256": "0" * 64,
                "mapping_id": "gen-data-sensor-stream-canonical",
                "mapping_version": "v1",
                "mapping_sha256": "a1b2c3d4" + "0" * 56,
                "extraction_run_id": "run-001",
                "batch_id": "b" * 64,
            }
        ],
        rejected_records=[],
        source_fragment_refs=[
            FragmentReference(batch_id="b" * 64, fragment_manifest_sha256="0" * 64)
        ],
        source_start_offset=0,
        source_end_offset=50,
    )


def test_window_publisher_atomic_publish_and_receipt(tmp_path, sample_assembled_window):
    """Publisher creates 4 files in data/observations, validates manifest, and saves publication receipt."""
    data_root = tmp_path / "data" / "observations"
    pubs_root = tmp_path / "extraction_state" / "publications"

    publisher = ExtractionWindowPublisher(
        data_root=data_root,
        publications_root=pubs_root,
    )

    published = publisher.publish_window_dataset(sample_assembled_window, run_id="run-001")

    assert Path(published.dataset_dir).is_dir()
    assert (Path(published.dataset_dir) / "dataset_manifest.json").is_file()
    assert (Path(published.dataset_dir) / "observations.jsonl").is_file()
    assert (Path(published.dataset_dir) / "provenance.jsonl").is_file()
    assert (Path(published.dataset_dir) / "rejected.jsonl").is_file()
    assert published.observation_count == 1

    # Receipt exists
    receipt_file = pubs_root / sample_assembled_window.source_identity / f"{sample_assembled_window.dataset_version}.json"
    assert receipt_file.is_file()


def test_window_publisher_zero_observations_rejected(tmp_path, sample_assembled_window):
    """Publishing window with 0 observations raises ExtractionNoValidObservationsError."""
    data_root = tmp_path / "data" / "observations"
    publisher = ExtractionWindowPublisher(data_root=data_root)

    empty_win = copy.deepcopy(sample_assembled_window)
    empty_win.observations = []

    with pytest.raises(ExtractionNoValidObservationsError):
        publisher.publish_window_dataset(empty_win, run_id="run-001")


def test_window_publisher_idempotency_and_conflict(tmp_path, sample_assembled_window):
    """Re-publishing identical dataset is idempotent; publishing conflicting payload raises ExtractionDatasetConflictError."""
    data_root = tmp_path / "data" / "observations"
    pubs_root = tmp_path / "extraction_state" / "publications"

    publisher = ExtractionWindowPublisher(
        data_root=data_root,
        publications_root=pubs_root,
    )

    # 1. First publish
    p1 = publisher.publish_window_dataset(sample_assembled_window, run_id="run-001")

    # 2. Idempotent publish
    p2 = publisher.publish_window_dataset(sample_assembled_window, run_id="run-001")
    assert p1.manifest_sha256 == p2.manifest_sha256

    # 3. Conflicting publish (different observation content for same dataset_version)
    conflict_win = copy.deepcopy(sample_assembled_window)
    conflict_win.observations[0]["torque_nm"] = 999.9

    with pytest.raises(ExtractionDatasetConflictError):
        publisher.publish_window_dataset(conflict_win, run_id="run-002")


def test_published_dataset_compatible_with_feature_input_resolver(tmp_path, sample_assembled_window, monkeypatch):
    """Published observation dataset can be resolved and loaded by FeatureInputResolver."""
    data_dir = tmp_path / "data"
    obs_dir = data_dir / "observations"

    from systems.generator.generator_config import PATHS
    monkeypatch.setattr(PATHS, "data_dir", data_dir)

    publisher = ExtractionWindowPublisher(
        data_root=obs_dir,
        publications_root=tmp_path / "pubs",
    )

    published = publisher.publish_window_dataset(sample_assembled_window, run_id="run-001")

    # Resolve using FeatureInputResolver
    resolver = FeatureInputResolver()
    resolved = resolver.resolve_dataset(
        dataset_type="observation",
        dataset_id=sample_assembled_window.dataset_id,
        dataset_version=sample_assembled_window.dataset_version,
    )

    assert resolved.dataset_id == sample_assembled_window.dataset_id
    assert resolved.dataset_version == sample_assembled_window.dataset_version
    assert resolved.payload_path.is_file()
    assert resolved.manifest_path.is_file()

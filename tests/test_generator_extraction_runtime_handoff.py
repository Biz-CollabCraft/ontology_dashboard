"""Unit and integration tests for Extraction Runtime Handoff Service, Worker, and APIs."""

import asyncio
import hashlib
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from systems.generator.file_integrity import compute_file_sha256
from systems.generator.generator_config import PATHS
from systems.generator.app.extraction.extraction_exception import (
    ExtractionHandoffChecksumMismatchError,
    ExtractionRequestInvalidError,
    ExtractionSourceNotFoundError,
)
from systems.generator.app.extraction.extraction_handoff_repository import (
    ExtractionHandoffRepository,
)
from systems.generator.app.extraction.extraction_handoff_worker import (
    ExtractionHandoffWorker,
)
from systems.generator.app.extraction.extraction_manager import (
    ExtractionManager,
)
from systems.generator.app.extraction.extraction_runtime_handoff_service import (
    ExtractionRuntimeHandoffService,
)
from systems.generator.app.main import app
from systems.generator.app.runtime_pipeline.pipeline_manager import (
    PipelineManager,
)
from systems.generator.app.runtime_pipeline.pipeline_queue import (
    PipelineQueue,
)


@pytest.fixture
def client():
    return TestClient(app)


def _create_test_dataset(tmp_path: Path) -> Path:
    """Helper to build a valid published canonical observation dataset."""
    dataset_dir = tmp_path / "data" / "observations" / "gen-data-S01-L01" / "window-20260828T130000Z-map-d545f01d"
    dataset_dir.mkdir(parents=True, exist_ok=True)

    obs_file = dataset_dir / "observations.jsonl"
    obs_content = b'{"asset_id":"CNC-01","observed_at":"2026-08-28T13:10:00Z","measurements":{"torque_nm":40.0}}\n'
    obs_file.write_bytes(obs_content)
    obs_sha = compute_file_sha256(obs_file)
    obs_size = len(obs_content)

    prov_file = dataset_dir / "provenance.jsonl"
    prov_content = b'{"asset_id":"CNC-01","observed_at":"2026-08-28T13:10:00Z","measurement_key":"torque_nm","source_observation_id":"s-01","source_sequence":1,"source_direction":"forward","mapping_id":"m1","mapping_version":"v1","mapping_sha256":"0000000000000000000000000000000000000000000000000000000000000000","extraction_run_id":"r1"}\n'
    prov_file.write_bytes(prov_content)
    prov_sha = compute_file_sha256(prov_file)

    rej_file = dataset_dir / "rejected.jsonl"
    rej_file.write_bytes(b"")
    rej_sha = compute_file_sha256(rej_file)

    manifest_data = {
        "manifest_version": "generator-dataset-input-v1",
        "dataset_type": "observation",
        "dataset_id": "gen-data-S01-L01",
        "dataset_version": "window-20260828T130000Z-map-d545f01d",
        "schema_version": "canonical-observation-v1",
        "created_at": "2026-08-28T13:00:00Z",
        "files": [
            {
                "role": "observations",
                "path": "observations.jsonl",
                "media_type": "application/x-ndjson",
                "sha256": obs_sha,
                "size_bytes": obs_size,
            }
        ],
        "auxiliary_files": [
            {
                "role": "provenance",
                "path": "provenance.jsonl",
                "media_type": "application/x-ndjson",
                "sha256": prov_sha,
                "size_bytes": len(prov_content),
            },
            {
                "role": "rejected",
                "path": "rejected.jsonl",
                "media_type": "application/x-ndjson",
                "sha256": rej_sha,
                "size_bytes": 0,
            }
        ],
    }

    manifest_file = dataset_dir / "dataset_manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2) + "\n", encoding="utf-8")
    return manifest_file


def test_create_handoff_from_published_dataset(tmp_path, monkeypatch):
    manifest_path = _create_test_dataset(tmp_path)

    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    svc = ExtractionRuntimeHandoffService(repository=handoff_repo)

    handoff = svc.create_or_get_handoff(manifest_path)
    assert handoff is not None
    assert handoff.dataset.dataset_id == "gen-data-S01-L01"
    assert handoff.dataset.dataset_version == "window-20260828T130000Z-map-d545f01d"
    assert handoff.runtime_input.source.source_kind == "live_sensor"
    assert handoff.runtime_input.source.source_checksum == handoff.dataset.observations_sha256
    assert len(handoff.handoff_id) == 64


def test_create_handoff_checksum_mismatch_raises(tmp_path):
    manifest_path = _create_test_dataset(tmp_path)
    # Corrupt observations.jsonl
    obs_file = manifest_path.parent / "observations.jsonl"
    obs_file.write_bytes(b"corrupted contents\n")

    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    svc = ExtractionRuntimeHandoffService(repository=handoff_repo)

    with pytest.raises(ExtractionHandoffChecksumMismatchError):
        svc.create_or_get_handoff(manifest_path)


def test_process_handoff_runtime_disabled(tmp_path, monkeypatch):
    manifest_path = _create_test_dataset(tmp_path)
    monkeypatch.setattr(PATHS, "runtime_prediction_enabled", False)

    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    svc = ExtractionRuntimeHandoffService(repository=handoff_repo)

    handoff = svc.create_or_get_handoff(manifest_path)
    processed = svc.process_handoff(handoff)

    assert processed.status == "runtime_disabled"


def test_process_handoff_runtime_enabled_enqueues(tmp_path, monkeypatch):
    manifest_path = _create_test_dataset(tmp_path)
    monkeypatch.setattr(PATHS, "runtime_prediction_enabled", True)

    db_path = tmp_path / "queue.db"
    queue = PipelineQueue(db_path=db_path)
    pipe_mgr = PipelineManager(queue=queue)
    monkeypatch.setattr(PipelineManager, "get_instance", lambda: pipe_mgr)

    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    svc = ExtractionRuntimeHandoffService(repository=handoff_repo, pipeline_manager=pipe_mgr)

    handoff = svc.create_or_get_handoff(manifest_path)
    processed = svc.process_handoff(handoff)

    assert processed.status == "enqueued"
    assert processed.delivery.runtime_job_id is not None
    assert processed.delivery.queue_item_id is not None

    # Check queue item
    item = queue.get_item(processed.delivery.runtime_job_id)
    assert item is not None
    assert item.status == "queued"
    assert item.dataset_id == "gen-data-S01-L01"


def test_process_handoff_self_healing(tmp_path, monkeypatch):
    manifest_path = _create_test_dataset(tmp_path)
    monkeypatch.setattr(PATHS, "runtime_prediction_enabled", True)

    db_path = tmp_path / "queue.db"
    queue = PipelineQueue(db_path=db_path)
    pipe_mgr = PipelineManager(queue=queue)
    monkeypatch.setattr(PipelineManager, "get_instance", lambda: pipe_mgr)

    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    svc = ExtractionRuntimeHandoffService(repository=handoff_repo, pipeline_manager=pipe_mgr)

    handoff = svc.create_or_get_handoff(manifest_path)

    # Manually enqueue into queue first (simulating crash before handoff update)
    from systems.generator.app.extraction.extraction_handoff_repository import compute_runtime_job_id
    from systems.generator.app.runtime_pipeline.pipeline_schema import (
        PredictionResultLineage,
        RuntimeInputIdentity,
        RuntimeSourceContext,
    )
    r_job_id = compute_runtime_job_id(handoff.handoff_id)
    runtime_input = RuntimeInputIdentity(
        dataset_id=handoff.runtime_input.dataset_id,
        dataset_version=handoff.runtime_input.dataset_version,
        source=RuntimeSourceContext(
            source_uri=handoff.runtime_input.source.source_uri,
            source_checksum=handoff.runtime_input.source.source_checksum,
            source_kind=handoff.runtime_input.source.source_kind,
            source_contract_version=handoff.runtime_input.source.source_contract_version,
            source_schema_version=handoff.runtime_input.source.source_schema_version,
            pipeline_contract_version=handoff.runtime_input.source.pipeline_contract_version,
            lineage=PredictionResultLineage.model_validate(
                handoff.runtime_input.source.lineage.model_dump()
            ),
        ),
    )
    queue.enqueue(
        job_id=r_job_id,
        runtime_input=runtime_input,
        size_bytes=handoff.dataset.observations_size_bytes,
    )

    # Now process handoff -> should self-heal to enqueued without duplicate
    processed = svc.process_handoff(handoff)
    assert processed.status == "enqueued"
    assert processed.delivery.runtime_job_id == r_job_id


def test_handoff_worker_polling_cycle(tmp_path, monkeypatch):
    manifest_path = _create_test_dataset(tmp_path)
    monkeypatch.setattr(PATHS, "runtime_prediction_enabled", True)

    db_path = tmp_path / "queue.db"
    queue = PipelineQueue(db_path=db_path)
    pipe_mgr = PipelineManager(queue=queue)
    monkeypatch.setattr(PipelineManager, "get_instance", lambda: pipe_mgr)

    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    svc = ExtractionRuntimeHandoffService(repository=handoff_repo, pipeline_manager=pipe_mgr)
    handoff = svc.create_or_get_handoff(manifest_path)
    assert handoff.status == "pending"

    worker = ExtractionHandoffWorker(service=svc)

    def _run():
        asyncio.run(worker.run_single_cycle())

    _run()

    found, _ = handoff_repo.find_handoff_by_id(handoff.handoff_id)
    assert found is not None
    assert found.status == "enqueued"


def test_status_summary_includes_handoff_metrics(tmp_path, monkeypatch):
    manifest_path = _create_test_dataset(tmp_path)
    monkeypatch.setattr(PATHS, "extraction_runtime_handoff_enabled", True)
    monkeypatch.setattr(PATHS, "runtime_prediction_enabled", False)

    manager = ExtractionManager()
    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    manager.handoff_repo = handoff_repo
    manager.handoff_service = ExtractionRuntimeHandoffService(repository=handoff_repo)

    manager.handoff_service.create_or_get_handoff(manifest_path)

    status = manager.get_status()
    assert status.runtime_handoff is not None
    assert status.runtime_handoff.enabled is True
    assert status.runtime_handoff.runtime_disabled == 1


def test_api_get_and_retry_handoff(client, tmp_path, monkeypatch):
    manifest_path = _create_test_dataset(tmp_path)
    monkeypatch.setattr(PATHS, "runtime_prediction_enabled", True)

    db_path = tmp_path / "queue.db"
    queue = PipelineQueue(db_path=db_path)
    pipe_mgr = PipelineManager(queue=queue)
    monkeypatch.setattr(PipelineManager, "get_instance", lambda: pipe_mgr)

    manager = ExtractionManager.get_instance()
    handoff_repo = ExtractionHandoffRepository(root_dir=tmp_path / "handoffs")
    manager.handoff_repo = handoff_repo
    manager.handoff_service = ExtractionRuntimeHandoffService(
        repository=handoff_repo, pipeline_manager=pipe_mgr
    )

    handoff = manager.handoff_service.create_or_get_handoff(manifest_path)

    # 1. GET /extraction/handoffs/{id}
    resp = client.get(f"/extraction/handoffs/{handoff.handoff_id}")
    assert resp.status_code == 200
    assert resp.json()["handoff_id"] == handoff.handoff_id

    # 2. GET invalid ID format
    resp_invalid = client.get("/extraction/handoffs/short-id")
    assert resp_invalid.status_code in (400, 422)

    # 3. POST /extraction/handoffs/{id}/retry
    resp_retry = client.post(f"/extraction/handoffs/{handoff.handoff_id}/retry")
    assert resp_retry.status_code == 200
    assert resp_retry.json()["status"] == "enqueued"

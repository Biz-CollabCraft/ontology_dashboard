from pathlib import Path

from app.infra.db.migrations import migrate
from app.infra.db.pipeline_job_repository import PipelineJobRepository
from app.system_operations.pipeline_job_schema import PipelineJobCreate
from app.system_operations.pipeline_job_service import PipelineJobService


class FakeGenerator:
    def rebuild(self, payload):
        return {"status": "succeeded", "run_id": payload["run_id"], "published_datasets": ["dataset-v2"]}

    def activate(self, mapping_id, payload):
        return {"mapping_id": mapping_id, **payload, "activated_at": "2026-09-01T00:00:00Z", "idempotent": False}


def _service(tmp_path: Path) -> PipelineJobService:
    database = tmp_path / "jobs.db"
    migrate(str(database))
    return PipelineJobService(PipelineJobRepository(database), FakeGenerator())


def _request(key: str = "rebuild-1") -> PipelineJobCreate:
    return PipelineJobCreate(
        mapping_id="mapping-a", mapping_version="v2", mapping_sha256="1" * 64,
        source_uri="sensor/fac1/line1/sensor_stream.jsonl", idempotency_key=key,
        reason="mapping replay",
    )


def test_pipeline_job_is_idempotent_and_executes_before_activation(tmp_path: Path):
    service = _service(tmp_path)
    first, created = service.create(_request(), "operator", "req-1")
    second, created_again = service.create(_request(), "operator", "req-2")
    assert created is True
    assert created_again is False
    assert second["job_id"] == first["job_id"]

    completed = service.execute(first["job_id"])
    assert completed["status"] == "succeeded"
    assert completed["result"]["rebuild"]["status"] == "succeeded"
    assert completed["result"]["activation"]["mapping_version"] == "v2"


def test_queued_pipeline_job_can_be_cancelled(tmp_path: Path):
    service = _service(tmp_path)
    job, _ = service.create(_request("rebuild-cancel"), "operator", "req-1")
    cancelled = service.cancel(job["job_id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] is True

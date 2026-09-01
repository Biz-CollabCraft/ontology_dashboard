from pathlib import Path

from app.infra.db.impact_analysis_repository import ImpactAnalysisRepository
from app.infra.db.migrations import migrate
from app.infra.db.pipeline_job_repository import PipelineJobRepository
from app.system_operations.impact_analysis_schema import DownstreamRebuildCreate
from app.system_operations.pipeline_job_service import PipelineJobService


class UnusedMappingGenerator:
    pass


class DownstreamGenerator:
    def __init__(self) -> None:
        self.calls = []

    def execute(self, stage, payload):
        self.calls.append((stage, payload))
        return {"status": "succeeded", "stage": stage}


def _analysis(repository: ImpactAnalysisRepository) -> dict:
    now = "2026-09-02T00:00:00+00:00"
    return repository.create(
        {
            "analysis_id": "c77620ca-812a-49b4-b74d-b105e8356711",
            "status": "completed",
            "mapping_id": "mapping-a",
            "mapping_version": "v2",
            "mapping_sha256": "1" * 64,
            "rebuild_job_id": "e5329616-3d08-42ff-9f14-76dd668b6902",
            "include_stages": ["preprocessing"],
            "source": {},
            "nodes": [],
            "edges": [],
            "actions": [
                {
                    "action_id": "preprocessing:dataset-a:v2",
                    "stage": "preprocessing",
                    "status": "recommended",
                    "required_parameters": {"dataset_id": "dataset-a", "dataset_version": "v2"},
                    "depends_on_action_ids": [],
                }
            ],
            "snapshot_sha256": "2" * 64,
            "created_by": "operator",
            "created_at": now,
        }
    )


def test_downstream_rebuild_executes_selected_steps(tmp_path: Path):
    database = tmp_path / "downstream.db"
    migrate(str(database))
    impact_repository = ImpactAnalysisRepository(database)
    analysis = _analysis(impact_repository)
    downstream = DownstreamGenerator()
    service = PipelineJobService(
        PipelineJobRepository(database), UnusedMappingGenerator(), impact_repository, downstream
    )
    request = DownstreamRebuildCreate(
        expected_snapshot_sha256=analysis["snapshot_sha256"],
        selected_action_ids=["preprocessing:dataset-a:v2"],
        reason="rebuild affected dataset",
    )

    queued = service.create_downstream(analysis["analysis_id"], request, "operator", "request-1")
    completed = service.execute(queued["job_id"])

    assert completed["status"] == "succeeded"
    assert completed["steps"][0]["status"] == "succeeded"
    assert downstream.calls == [
        ("preprocessing", {"dataset_id": "dataset-a", "dataset_version": "v2"})
    ]


def test_training_step_forces_publish_only():
    from app.infra.generator_downstream import GeneratorDownstreamClient

    class Response:
        is_error = False

        def json(self):
            return {"status": "succeeded"}

    class Client:
        def __init__(self):
            self.payload = None

        def post(self, url, json):
            self.payload = json
            return Response()

    http = Client()
    client = GeneratorDownstreamClient("http://generator", client=http)
    client.execute("training", {"dataset_id": "dataset-a"})
    assert http.payload["activation_policy"] == "publish_only"

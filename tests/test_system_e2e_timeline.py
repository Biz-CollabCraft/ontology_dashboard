import sqlite3
import json
from pathlib import Path
from types import SimpleNamespace

from systems.backend.app.infra.db.system_e2e_repository import SystemE2ERepository
from systems.backend.app.system_operations.e2e_service import SystemE2EService
from jsonschema import Draft202012Validator, RefResolver


def _service(tmp_path: Path) -> SystemE2EService:
    database = tmp_path / "e2e.sqlite3"
    migration = "\n".join(
        Path(path).read_text(encoding="utf-8")
        for path in (
            "systems/backend/migrations/sqlite/0051_system_e2e_timeline.sql",
            "systems/backend/migrations/sqlite/0052_system_e2e_scope.sql",
        )
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(migration)
    return SystemE2EService(SystemE2ERepository(database))


def test_prediction_receipt_creates_timeline_and_only_anomaly_alerts(tmp_path):
    service = _service(tmp_path)
    receipt = SimpleNamespace(batch_id="batch-1", payload_sha256="a" * 64,
        validation_status="accepted", rejection_reason=None, promotion_status="promoted")
    payload = {"emitted_at": "2026-09-02T00:00:00Z", "source_context": {
        "source_uri": "data_preprocessed/source.jsonl", "source_checksum": "b" * 64},
        "results": [{"asset_id": "asset-1"}, {"asset_id": "asset-2"}]}
    service.record_prediction_receipt(organization_id="org-1", project_id="project-1", workspace_id="workspace-1", payload=payload, receipt=receipt, request_id="request-1",
        product_results=[
            {"artifact_id": "RESULT#1", "prediction_result_id": "prediction-1", "asset_id": "asset-1", "observed_at": "2026-09-02T00:00:00Z", "status_grade": "warning"},
            {"artifact_id": "RESULT#2", "prediction_result_id": "prediction-2", "asset_id": "asset-2", "observed_at": "2026-09-02T00:00:00Z", "status_grade": "normal"},
        ])
    run = service.list_runs(organization_id="org-1")["items"][0]
    assert run["status"] == "succeeded"
    assert run["source_sha256"] == "b" * 64
    assert len(service.timeline(run["run_id"], organization_id="org-1")["events"]) == 3
    alerts = service.list_alerts(organization_id="org-1")["items"]
    assert [item["asset_id"] for item in alerts] == ["asset-1"]
    assert service.list_runs(organization_id="org-2")["items"] == []
    assert service.list_alerts(organization_id="org-2")["items"] == []


def test_recording_same_receipt_is_idempotent(tmp_path):
    service = _service(tmp_path)
    receipt = SimpleNamespace(batch_id="batch-1", payload_sha256="a" * 64,
        validation_status="duplicate", rejection_reason=None, promotion_status="already_promoted")
    payload = {"results": [{"asset_id": "asset-1"}]}
    for _ in range(2):
        service.record_prediction_receipt(organization_id="org-1", project_id="project-1", workspace_id="workspace-1", payload=payload, receipt=receipt, request_id="request-1", product_results=[])
    runs = service.list_runs(organization_id="org-1")["items"]
    assert len(runs) == 1
    assert len(service.timeline(runs[0]["run_id"], organization_id="org-1")["events"]) == 1


def test_system_e2e_examples_match_canonical_schemas():
    root = Path("contracts")
    schema_root = root / "schemas"
    cases = (
        ("system-e2e-run-summary.schema.json", "run-summary.json"),
        ("system-e2e-timeline.schema.json", "timeline.json"),
        ("dashboard-anomaly-alert.schema.json", "dashboard-alert.json"),
    )
    store = {}
    for path in schema_root.glob("*.schema.json"):
        data = json.loads(path.read_text(encoding="utf-8")); store[data.get("$id", path.name)] = data; store[path.name] = data
    for schema_name, example_name in cases:
        schema = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
        example = json.loads((root / "examples" / "system-e2e" / example_name).read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, resolver=RefResolver.from_schema(schema, store=store))
        assert list(validator.iter_errors(example)) == []


def test_unknown_product_status_fails_closed(tmp_path):
    service = _service(tmp_path)
    receipt = SimpleNamespace(batch_id="batch-unsupported", payload_sha256="a" * 64,
        validation_status="accepted", rejection_reason=None, promotion_status="promoted")
    try:
        service.record_prediction_receipt(
            organization_id="org-1", project_id="project-1", workspace_id="workspace-1",
            payload={"results": [{"asset_id": "asset-1"}]}, receipt=receipt, request_id="request-1",
            product_results=[{"artifact_id": "RESULT#x", "prediction_result_id": "prediction-x",
                "asset_id": "asset-1", "status_grade": "unknown"}],
        )
    except ValueError as exc:
        assert "unsupported Product Result status_grade" in str(exc)
    else:
        raise AssertionError("unsupported status_grade must fail closed")
    assert service.list_runs(organization_id="org-1")["items"] == []
    assert service.list_alerts(organization_id="org-1")["items"] == []

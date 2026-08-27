from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from app.infra.generator_runtime_pipeline import (
    GeneratorRuntimePipelineClient,
    GeneratorRuntimePipelineUnavailable,
)
from app.infra.live_predictive_maintenance_runtime import (
    _materialize_overlay_pipeline_snapshot,
    _read_overlay_history_rows,
)
from app.infra.runtime_overlay_contract import (
    expected_storage_reference,
    semantic_observation_sha256,
)


def _event() -> dict[str, object]:
    return {
        "event_id": "OVERLAY-AVAILABLE:MAINT-1:post:1",
        "overlay_branch_id": "MAINT-1:post",
        "equipment_id": "CNC-1",
    }


def _row() -> dict[str, object]:
    return {
        "asset_id": "CNC-1",
        "equipment_id": "CNC-1",
        "observed_at": "2026-08-27T01:00:00+00:00",
        "maintenance_event_id": "MAINT-1",
        "overlay_branch_id": "MAINT-1:post",
        "history_segment_id": "MAINT-1:post",
        "tool_wear_min": 0,
    }


def test_overlay_delta_is_frozen_as_content_addressed_generator_input(tmp_path: Path) -> None:
    rows = [_row()]

    first = _materialize_overlay_pipeline_snapshot(tmp_path, _event(), rows)
    second = _materialize_overlay_pipeline_snapshot(tmp_path, _event(), rows)

    snapshot = Path(first["source_uri"])
    content = snapshot.read_bytes()
    assert first == second
    assert snapshot.parent == tmp_path / "runtime_pipeline_input"
    assert snapshot.name == f"sha256-{first['source_checksum']}.jsonl"
    assert hashlib.sha256(content).hexdigest() == first["source_checksum"]
    assert first["size_bytes"] == len(content)
    assert json.loads(content.decode("utf-8")) == rows[0]


def test_overlay_snapshot_does_not_change_when_branch_file_keeps_growing(tmp_path: Path) -> None:
    branch = tmp_path / "runtime_overlay" / "branch.jsonl"
    branch.parent.mkdir(parents=True)
    branch.write_text(json.dumps(_row()) + "\n", encoding="utf-8")
    snapshot = _materialize_overlay_pipeline_snapshot(tmp_path, _event(), [_row()])
    frozen = Path(snapshot["source_uri"]).read_bytes()

    branch.write_text(
        branch.read_text(encoding="utf-8") + json.dumps({**_row(), "observed_at": "2026-08-27T01:10:00+00:00"}) + "\n",
        encoding="utf-8",
    )

    assert Path(snapshot["source_uri"]).read_bytes() == frozen
    assert hashlib.sha256(frozen).hexdigest() == snapshot["source_checksum"]


def test_generator_snapshot_uses_cumulative_history_not_only_latest_delta(
    tmp_path: Path,
) -> None:
    vector_path = (
        Path(__file__).parents[1]
        / "contracts"
        / "test-vectors"
        / "runtime-overlay-output-v1"
        / "observation-unicode.json"
    )
    first = json.loads(vector_path.read_text(encoding="utf-8"))
    second = {
        **first,
        "sequence": 2,
        "observation_id": "obs-22222222222222222222222222222222",
        "observed_at": "2026-08-18T01:50:00+00:00",
        "generated_at": "2026-08-18T02:01:00+00:00",
    }
    second["observation_sha256"] = semantic_observation_sha256(second)
    event = {
        "event_id": "OVERLAY-AVAILABLE:MAINT-1:post:2",
        "simulation_session_id": first["simulation_session_id"],
        "equipment_id": first["equipment_id"],
        "maintenance_action_id": first["maintenance_action_id"],
        "maintenance_event_id": first["maintenance_event_id"],
        "overlay_branch_id": first["overlay_branch_id"],
        "history_segment_id": first["history_segment_id"],
        "state_version": first["state_version"],
        "batch_rows": 1,
        "generated_rows": 2,
        "observed_from": second["observed_at"],
        "observed_to": second["observed_at"],
        "storage_reference": "",
    }
    event["storage_reference"] = expected_storage_reference(event)
    storage = tmp_path.joinpath(*Path(event["storage_reference"]).parts)
    storage.parent.mkdir(parents=True)
    storage.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in (first, second)) + "\n",
        encoding="utf-8",
    )

    history = _read_overlay_history_rows(tmp_path, event)
    snapshot = _materialize_overlay_pipeline_snapshot(tmp_path, event, history)
    frozen_rows = [
        json.loads(line)
        for line in Path(snapshot["source_uri"]).read_text(encoding="utf-8").splitlines()
    ]

    assert [row["observation_id"] for row in history] == [
        first["observation_id"],
        second["observation_id"],
    ]
    assert frozen_rows == history


def test_generator_enqueue_client_sends_pr127_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={**captured, "status": "queued"})

    client = GeneratorRuntimePipelineClient(
        "http://generator/internal/runtime-pipeline/enqueue",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    payload = {
        "job_id": "runtime-overlay-job",
        "source_uri": "/shared/runtime_pipeline_input/source.jsonl",
        "source_checksum": "a" * 64,
        "size_bytes": 123,
        "dataset_id": "canonical-ai4i-v1",
        "dataset_version": "canonical-ai4i-physics-v3.1",
        "pipeline_contract_version": "generator-prediction-result-v1",
    }

    result = client.enqueue(payload)

    assert captured == payload
    assert result["status"] == "queued"


@pytest.mark.parametrize(
    "code",
    ["PIPELINE_SOURCE_ALREADY_REGISTERED", "PIPELINE_SOURCE_ALREADY_PROCESSED"],
)
def test_generator_enqueue_client_treats_same_source_redelivery_as_reuse(code: str) -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            409,
            json={"error": {"code": code, "message": "duplicate"}},
        )
    )
    client = GeneratorRuntimePipelineClient(
        "http://generator/internal/runtime-pipeline/enqueue",
        client=httpx.Client(transport=transport),
    )

    result = client.enqueue({"job_id": "stable-job"})

    assert result == {
        "job_id": "stable-job",
        "status": "reused",
        "duplicate_code": code,
    }


def test_generator_enqueue_client_fails_closed_without_endpoint() -> None:
    client = GeneratorRuntimePipelineClient(endpoint="")
    with pytest.raises(
        GeneratorRuntimePipelineUnavailable,
        match="ONTOLOGY_DASHBOARD_GENERATOR_RUNTIME_ENQUEUE_URL",
    ):
        client.enqueue({"job_id": "job"})

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.dependencies import current_principal, get_identity_service, require_csrf
from app.diagnosis.runtime_router import router
from app.diagnosis.runtime_schema import PredictionResultBatch
from app.identity import Principal


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "contracts" / "examples" / "prediction-result-batch"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


class FakeIdentity:
    def require_permission(self, principal: Principal, permission: str) -> None:
        if permission not in principal.permissions:
            raise AssertionError(f"missing permission: {permission}")

    def require_project(self, principal: Principal, project_id: str) -> None:
        if project_id not in principal.project_scopes:
            raise AssertionError(f"missing project scope: {project_id}")

    def require_workspace(self, principal: Principal, workspace_id: str) -> None:
        if workspace_id not in principal.workspace_scopes:
            raise AssertionError(f"missing workspace scope: {workspace_id}")


def principal() -> Principal:
    return Principal(
        user_id="user-1",
        organization_id="org-ontology-demo",
        email="ml@example.com",
        display_name="ML Validator",
        status="active",
        roles=["ml_validator"],
        permissions=["predictions.ingest"],
        workspace_scopes=["manufacturing-demo"],
        project_scopes=["manufacturing-demo-project"],
        active_project_id="manufacturing-demo-project",
        active_project_roles=["ml_validator"],
        is_admin=False,
        default_path="/app/projects/manufacturing-demo-project/mvp",
        landing_key="mvp",
    )


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[current_principal] = principal
    app.dependency_overrides[get_identity_service] = lambda: FakeIdentity()
    app.dependency_overrides[require_csrf] = lambda: None
    return TestClient(app)


def load_predicted_example() -> dict:
    return load_example("prediction-result-batch-v1.json")


def load_maintenance_replay_example() -> dict:
    payload = load_predicted_example()
    item = payload["results"][0]
    item["source_kind"] = "maintenance_replay_overlay"
    item["output_status"] = "history_insufficient"
    item["score"] = None
    item["failure_reason"] = "Only 3 prior overlay observations are available; model requires 35 prior rows."
    item["lineage"] = {
        "simulation_session_id": "sim-20260826-0001",
        "overlay_branch_id": "overlay-branch-cnc-001-0001",
        "history_segment_id": "history-segment-cnc-001-0001",
        "maintenance_event_id": "maintenance-event-0001",
        "maintenance_action_id": "maintenance-action-0001",
        "state_version": 4,
    }
    return payload


def test_prediction_result_batch_example_matches_backend_model():
    batch = PredictionResultBatch.model_validate(load_predicted_example())

    assert batch.contract_version == "prediction-result-batch-v1"
    assert batch.producer.system == "systems.generator"
    assert batch.results


def test_prediction_result_batch_keeps_predicted_score_required():
    payload = load_predicted_example()
    payload["results"][0]["score"] = None

    with pytest.raises(ValidationError, match="predicted batch items require score"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_rejects_failure_reason_on_predicted_item():
    payload = load_predicted_example()
    payload["results"][0]["failure_reason"] = "model warning"

    with pytest.raises(ValidationError, match="must not carry failure_reason"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_rejects_score_before_prediction_ready():
    payload = load_maintenance_replay_example()
    payload["results"][0]["score"] = 0.2

    with pytest.raises(ValidationError, match="non-predicted batch items must not carry score"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_requires_failure_reason_before_prediction_ready():
    payload = load_maintenance_replay_example()
    payload["results"][0]["failure_reason"] = None

    with pytest.raises(ValidationError, match="non-predicted batch items require failure_reason"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_requires_replay_lineage_for_maintenance_source():
    payload = load_maintenance_replay_example()
    payload["results"][0]["lineage"]["maintenance_event_id"] = None

    with pytest.raises(ValidationError, match="maintenance_replay_overlay batch items require lineage fields"):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_forbids_product_result_fields():
    payload = load_predicted_example()
    payload["results"][0]["status_grade"] = "critical"

    with pytest.raises(ValidationError):
        PredictionResultBatch.model_validate(payload)


def test_prediction_result_batch_validation_endpoint_returns_receipt(client: TestClient):
    response = client.post(
        "/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/"
        "predictive-maintenance/prediction-result-batches/validate",
        json=load_predicted_example(),
        headers={"X-CSRF-Token": "test"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["promotion_status"] == "validated_only"
    assert body["product_result_created"] is False
    assert body["received_results"] == 1
    assert body["predicted_results"] == 1
    assert body["blocked_results"] == 0
    assert body["idempotency_basis"] == [
        {
            "event_id": "evt-001",
            "payload_sha256": "d2421e9a707b7333cf7f090d24de6025d1df8a605653040e95c6d5e0e88067ce",
        }
    ]


def test_prediction_result_batch_validation_endpoint_rejects_product_fields(client: TestClient):
    payload = load_predicted_example()
    payload["results"][0]["status_grade"] = "critical"

    response = client.post(
        "/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/"
        "predictive-maintenance/prediction-result-batches/validate",
        json=payload,
        headers={"X-CSRF-Token": "test"},
    )

    assert response.status_code == 422

from __future__ import annotations

import copy
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from app.dependencies import current_principal, get_identity_service, require_csrf
from app.diagnosis.runtime_router import internal_router, router
from app.diagnosis.runtime_service import PredictiveMaintenanceRuntimeService
from app.identity import AuthError, Principal
from app.identity.identity_router import identity_http_status


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "contracts" / "examples" / "prediction-result-batch" / "prediction-result-batch-v1.json"
SCHEMA = ROOT / "contracts" / "schemas" / "prediction-result-batch.schema.json"


class FakeIdentity:
    def require_permission(self, principal: Principal, permission: str) -> None:
        assert permission in principal.permissions

    def require_project(self, principal: Principal, project_id: str) -> None:
        assert project_id in principal.project_scopes

    def require_workspace(self, principal: Principal, workspace_id: str) -> None:
        assert workspace_id in principal.workspace_scopes


class FakeInboxRepository:
    def __init__(self, *, assets: set[str] | None = None) -> None:
        self.assets = assets or {"CNC-001"}
        self.batches: dict[str, str] = {}
        self.items: dict[str, str] = {}
        self.saved: list[dict[str, Any]] = []

    @staticmethod
    def clock_now() -> datetime:
        return datetime(2026, 8, 27, tzinfo=timezone.utc)

    def assets_exist_in_workspace(self, **kwargs: Any) -> set[str]:
        return set(kwargs["asset_ids"]) & self.assets

    def save_prediction_batch_inbox(self, **kwargs: Any) -> dict[str, Any]:
        batch_id = kwargs["batch_id"]
        payload_sha256 = kwargs["payload_sha256"]
        status = kwargs["validation_status"]
        reason = kwargs["rejection_reason"]
        if batch_id in self.batches:
            if self.batches[batch_id] == payload_sha256:
                status = "duplicate"
                reason = None
            else:
                status = "conflict"
                reason = "batch_payload_conflict"

        persisted = []
        for receipt in kwargs["item_receipts"]:
            event_id = receipt["event_id"]
            item_sha = receipt["payload_sha256"]
            item_status = receipt["validation_status"]
            item_reason = receipt["rejection_reason"]
            if event_id in self.items:
                if self.items[event_id] == item_sha:
                    item_status = "duplicate"
                    item_reason = None
                else:
                    item_status = "conflict"
                    item_reason = "event_payload_conflict"
            else:
                self.items[event_id] = item_sha
            persisted.append(
                {
                    "event_id": event_id,
                    "payload_sha256": item_sha,
                    "validation_status": item_status,
                    "rejection_reason": item_reason,
                }
            )

        if any(item["validation_status"] == "conflict" for item in persisted):
            status = "conflict"
            reason = reason or "one or more items conflicted"
        elif any(item["validation_status"] == "rejected" for item in persisted):
            status = "rejected"
            reason = reason or "one or more items were rejected"
        elif persisted and all(item["validation_status"] == "duplicate" for item in persisted):
            status = "duplicate"
            reason = None
        self.batches.setdefault(batch_id, payload_sha256)
        row = {
            "batch_id": batch_id,
            "payload_sha256": payload_sha256,
            "validation_status": status,
            "rejection_reason": reason,
            "raw_payload": kwargs["raw_payload"],
            "item_receipts": persisted,
        }
        self.saved.append(row)
        return row


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


def load_payload() -> dict[str, Any]:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["results"][0]["payload_sha256"] = (
        PredictiveMaintenanceRuntimeService._prediction_item_sha256(payload["results"][0])
    )
    return payload


def make_service(repository: FakeInboxRepository | None = None) -> PredictiveMaintenanceRuntimeService:
    return PredictiveMaintenanceRuntimeService(repository or FakeInboxRepository())


def add_auth_error_handler(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def auth_error_handler(_, exc: AuthError):
        return JSONResponse(
            status_code=identity_http_status(exc),
            content={"detail": exc.message},
        )


def receive(
    service: PredictiveMaintenanceRuntimeService,
    payload: dict[str, Any],
):
    return service.receive_prediction_result_batch(
        organization_id="org-ontology-demo",
        project_id="manufacturing-demo-project",
        workspace_id="manufacturing-demo",
        payload=payload,
    )


def test_prediction_inbox_accepts_valid_batch_without_product_result() -> None:
    receipt = receive(make_service(), load_payload())

    assert receipt.validation_status == "accepted"
    assert receipt.accepted_results == 1
    assert receipt.promotion_status == "not_promoted"
    assert receipt.product_result_created is False


def test_prediction_inbox_duplicate_reuses_existing_event() -> None:
    service = make_service()
    payload = load_payload()

    assert receive(service, payload).validation_status == "accepted"
    duplicate = receive(service, payload)

    assert duplicate.validation_status == "duplicate"
    assert duplicate.duplicate_results == 1


def test_prediction_inbox_conflicts_same_event_different_payload() -> None:
    service = make_service()
    payload = load_payload()
    assert receive(service, payload).validation_status == "accepted"

    changed = copy.deepcopy(payload)
    changed["batch_id"] = "batch-conflicting"
    changed["results"][0]["score"] = 0.7
    changed["results"][0]["payload_sha256"] = (
        PredictiveMaintenanceRuntimeService._prediction_item_sha256(changed["results"][0])
    )
    conflict = receive(service, changed)

    assert conflict.validation_status == "conflict"
    assert conflict.conflict_results == 1
    assert "Product" not in (conflict.rejection_reason or "")


def test_prediction_inbox_rejects_payload_sha256_mismatch() -> None:
    payload = load_payload()
    payload["results"][0]["score"] = 0.7

    receipt = receive(make_service(), payload)

    assert receipt.validation_status == "rejected"
    assert receipt.rejected_results == 1
    assert "payload_sha256_mismatch" in (receipt.rejection_reason or "")


def test_prediction_inbox_rejects_official_schema_violation_before_pydantic() -> None:
    payload = load_payload()
    payload["results"][0]["source_ref"]["sha256"] = "0" * 64
    payload["results"][0]["payload_sha256"] = (
        PredictiveMaintenanceRuntimeService._prediction_item_sha256(payload["results"][0])
    )

    receipt = receive(make_service(), payload)

    assert receipt.validation_status == "rejected"
    assert receipt.received_results == 0
    assert "schema_invalid" in (receipt.rejection_reason or "")
    assert "source_ref" in (receipt.rejection_reason or "")


def test_prediction_inbox_example_passes_schema_pydantic_receipt_roundtrip() -> None:
    payload = load_payload()
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    assert list(validator.iter_errors(payload)) == []
    receipt = receive(make_service(), payload)

    assert receipt.validation_status == "accepted"
    assert receipt.received_results == len(payload["results"])


def test_prediction_inbox_preserves_generator_source_context_and_model_set() -> None:
    repository = FakeInboxRepository()
    payload = load_payload()

    receipt = receive(make_service(repository), payload)

    assert receipt.validation_status == "accepted"
    stored_payload = repository.saved[0]["raw_payload"]
    assert stored_payload["source_context"] == payload["source_context"]
    assert stored_payload["model_set"] == payload["model_set"]
    assert stored_payload["results"][0]["label_schema_sha256"] == (
        payload["results"][0]["label_schema_sha256"]
    )


def test_prediction_inbox_records_schema_invalid_payload() -> None:
    payload = load_payload()
    payload.pop("results")

    receipt = receive(make_service(), payload)

    assert receipt.validation_status == "rejected"
    assert receipt.received_results == 0
    assert "schema_invalid" in (receipt.rejection_reason or "")


def test_prediction_inbox_rejects_asset_outside_workspace() -> None:
    payload = load_payload()
    payload["results"][0]["asset_id"] = "CNC-404"
    payload["results"][0]["payload_sha256"] = (
        PredictiveMaintenanceRuntimeService._prediction_item_sha256(payload["results"][0])
    )

    receipt = receive(make_service(), payload)

    assert receipt.validation_status == "rejected"
    assert "scope_invalid" in (receipt.rejection_reason or "")


def test_prediction_inbox_routes_return_receipt(monkeypatch) -> None:
    monkeypatch.setenv("PREDICTION_RESULT_INGEST_TOKEN", "receiver-secret")
    repository = FakeInboxRepository()
    service = make_service(repository)
    app = FastAPI()
    app.include_router(router)
    app.include_router(internal_router)
    app.dependency_overrides[current_principal] = principal
    app.dependency_overrides[get_identity_service] = lambda: FakeIdentity()
    app.dependency_overrides[require_csrf] = lambda: None
    from app.diagnosis.runtime_router import get_predictive_maintenance_runtime_service

    app.dependency_overrides[get_predictive_maintenance_runtime_service] = lambda: service

    with TestClient(app) as client:
        public = client.post(
            "/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/"
            "predictive-maintenance/prediction-result-batches",
            json=load_payload(),
            headers={"X-CSRF-Token": "test"},
        )
        internal = client.post(
            "/internal/prediction-results?project_id=manufacturing-demo-project"
            "&workspace_id=manufacturing-demo",
            json=load_payload(),
            headers={"Authorization": "Bearer receiver-secret"},
        )

    assert public.status_code == 202, public.text
    assert public.json()["product_result_created"] is False
    assert internal.status_code == 200, internal.text
    assert internal.json()["validation_status"] == "duplicate"


def test_prediction_inbox_internal_route_requires_configured_service_token(monkeypatch) -> None:
    monkeypatch.setenv("PREDICTION_RESULT_INGEST_TOKEN", "receiver-secret")
    service = make_service()
    app = FastAPI()
    add_auth_error_handler(app)
    app.include_router(internal_router)
    app.dependency_overrides[get_identity_service] = lambda: FakeIdentity()
    from app.diagnosis.runtime_router import get_predictive_maintenance_runtime_service

    app.dependency_overrides[get_predictive_maintenance_runtime_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            "/internal/prediction-results?project_id=manufacturing-demo-project"
            "&workspace_id=manufacturing-demo",
            json=load_payload(),
            headers={"Authorization": "Bearer wrong-secret"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Prediction Result service token is invalid."


def test_generator_delivery_service_reaches_backend_internal_route(monkeypatch) -> None:
    from systems.generator.app.runtime_pipeline.prediction_delivery_service import (
        PredictionDeliveryService,
    )

    class PayloadAdapter:
        batch_id = "batch-delivery-integration"

        def __init__(self) -> None:
            self.payload = load_payload()
            self.payload["batch_id"] = self.batch_id

        def model_dump_json(self) -> str:
            return json.dumps(self.payload)

        def model_dump(self, mode: str = "json") -> dict[str, Any]:
            return copy.deepcopy(self.payload)

    monkeypatch.setenv("PREDICTION_RESULT_INGEST_TOKEN", "receiver-secret")
    monkeypatch.setenv("GENERATOR_PREDICTION_RESULT_TOKEN", "receiver-secret")
    repository = FakeInboxRepository()
    service = make_service(repository)
    app = FastAPI()
    app.include_router(internal_router)
    app.dependency_overrides[get_identity_service] = lambda: FakeIdentity()
    from app.diagnosis.runtime_router import get_predictive_maintenance_runtime_service

    app.dependency_overrides[get_predictive_maintenance_runtime_service] = lambda: service

    class MockResponse:
        def __init__(self, response) -> None:
            self.response = response

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def getcode(self) -> int:
            return self.response.status_code

        def read(self) -> bytes:
            return self.response.content

    with TestClient(app) as client:
        def mock_urlopen(req, timeout=10.0):
            parsed = urllib.parse.urlsplit(req.full_url)
            path = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
            response = client.post(
                path,
                content=req.data,
                headers=dict(req.headers),
            )
            return MockResponse(response)

        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
        delivery = PredictionDeliveryService(
            endpoint_url="http://testserver/internal/prediction-results"
        )
        result = delivery.send_once(PayloadAdapter())

    assert result["delivered"] is True
    assert result["status_code"] == 202
    assert repository.saved[0]["validation_status"] == "accepted"

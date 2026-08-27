from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import current_principal, get_identity_service, require_csrf
from app.diagnosis.runtime_router import internal_router, router
from app.diagnosis.runtime_service import PredictiveMaintenanceRuntimeService
from app.identity import Principal


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "contracts" / "examples" / "prediction-result-batch" / "prediction-result-batch-v1.json"


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


def test_prediction_inbox_routes_return_receipt() -> None:
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
            headers={"X-CSRF-Token": "test"},
        )

    assert public.status_code == 202, public.text
    assert public.json()["product_result_created"] is False
    assert internal.status_code == 200, internal.text
    assert internal.json()["validation_status"] == "duplicate"

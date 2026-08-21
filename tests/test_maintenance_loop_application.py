from __future__ import annotations

import pytest

from app.infra.db.maintenance_repository import MaintenanceRepository
from app.maintenance.api_schema import (
    InspectionResultCreateRequest,
    InspectionWorkOrderCreateRequest,
    OperationsManualRecommendationCreateRequest,
    RecommendationDecisionCreateRequest,
)
from app.maintenance.maintenance_domain import IdempotencyConflict
from app.maintenance.maintenance_schema import RecommendationDisposition, WorkOrderStatus
from app.maintenance.service import MaintenanceLoopService


class Scope:
    organization_id = "org-1"
    project_id = "project-1"
    workspace_id = "workspace-1"


class Resolver:
    def resolve(
        self,
        workspace_id: str,
        *,
        expected_organization_id: str | None = None,
        expected_project_id: str | None = None,
        connection=None,
    ):
        del connection
        assert workspace_id == Scope.workspace_id
        assert expected_organization_id in {None, Scope.organization_id}
        assert expected_project_id in {None, Scope.project_id}
        return Scope()


class ProjectionQuery:
    def __init__(self, projection: dict | None = None) -> None:
        self.projection = projection if projection is not None else canonical_projection()
        self.calls: list[dict] = []

    def event_evidence_projection(self, **scope):
        self.calls.append(scope)
        return self.projection


def canonical_projection(
    *,
    event_id: str = "EVT-RESULT-001",
    asset_id: str = "CNC-001",
    asset_type: str = "cnc",
    decision: str | None = "review_shutdown",
) -> dict:
    actions = [] if decision is None else [{"action_id": decision, "basis": ["factor.1"]}]
    return {
        "schema_version": "event-evidence-projection-v1",
        "contract_type": "event_evidence_projection",
        "event_id": event_id,
        "evidence_id": f"EVD-{event_id}",
        "subject": {
            "equipment_id": asset_id,
            "asset_type": asset_type,
        },
        "artifact_reference": {
            "event_id": event_id,
            "artifact_id": "RESULT-001",
            "artifact_schema_version": "result-artifact-v1.0",
            "asset_id": asset_id,
            "asset_type": asset_type,
        },
        "assessment": {"operational_decision_kind": decision},
        "report_projection": {"recommended_actions": actions},
        "provenance": {"lineage": {"policy_version": "recommendation-policy-v1"}},
    }


def service(tmp_path, *, query: ProjectionQuery | None = None) -> MaintenanceLoopService:
    return MaintenanceLoopService(
        MaintenanceRepository(tmp_path / "maintenance.db", project_context=Resolver()),
        event_evidence_query=query or ProjectionQuery(),
    )


def inspection_request() -> InspectionWorkOrderCreateRequest:
    return InspectionWorkOrderCreateRequest(
        event_id="EVT-RESULT-001",
    )


def inspection_result(outcome: str = "maintenance_recommended") -> InspectionResultCreateRequest:
    return InspectionResultCreateRequest(
        outcome=outcome,
        checklist=(
            {"item_id": "tool-wear", "status": "fail", "note": "limit exceeded"},
        ),
        measurements=(
            {"name": "tool_wear_min", "value": 221, "unit": "min"},
        ),
        findings=("tool wear limit exceeded",),
        note="tool replacement should be reviewed",
    )


def run_completed_inspection(loop: MaintenanceLoopService) -> tuple[str, str]:
    requested = loop.request_inspection(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        payload=inspection_request(),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="inspection-request-001",
    )
    work_order_id = requested["work_order_id"]
    loop.transition_inspection(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        work_order_id=work_order_id,
        target=WorkOrderStatus.APPROVED,
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="inspection-approve-001",
    )
    loop.transition_inspection(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        work_order_id=work_order_id,
        target=WorkOrderStatus.IN_PROGRESS,
        actor_id="engineer-1",
        actor_display_name="Engineer One",
        idempotency_key="inspection-start-001",
    )
    completed = loop.complete_inspection(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        work_order_id=work_order_id,
        payload=inspection_result(),
        actor_id="engineer-1",
        actor_display_name="Engineer One",
        idempotency_key="inspection-complete-001",
    )
    assert completed["maintenance_event_id"] is None
    return work_order_id, completed["inspection_result_id"]


def test_two_stage_inspection_to_maintenance_work_order_lineage(tmp_path) -> None:
    loop = service(tmp_path)
    inspection_work_order_id, inspection_result_id = run_completed_inspection(loop)
    inspection_work_order = loop.repository.get_work_order(
        workspace_id="workspace-1",
        work_order_id=inspection_work_order_id,
    )
    assert inspection_work_order is not None
    assert inspection_work_order.authorization.model_dump(mode="json") == {
        "work_type": "inspection",
        "recommendation_id": None,
        "recommendation_decision_id": None,
        "recommendation_status": None,
        "recommendation_disposition": None,
        "operational_decision": "review_shutdown",
        "source_product_result_id": "RESULT-001",
        "source_evidence_id": "EVD-EVT-RESULT-001",
        "source_action_id": "review_shutdown",
        "source_schema_version": "result-artifact-v1.0",
        "source_policy_version": "recommendation-policy-v1",
    }

    created = loop.create_manual_recommendation(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=OperationsManualRecommendationCreateRequest(
            basis=("field engineer confirmed tool wear",)
        ),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="manual-recommendation-001",
    )
    recommendation_id = created["recommendation_id"]
    assert created["recommendation"]["recommendation_origin"] == "operations_manual"
    assert created["recommendation"]["source_product_result_id"] == "RESULT-001"
    assert created["recommendation"]["source_inspection_reference"] == inspection_result_id
    assert created["recommendation"]["asset_type"] == "cnc"

    decided = loop.decide_manual_recommendation(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        recommendation_id=recommendation_id,
        payload=RecommendationDecisionCreateRequest(
            disposition=RecommendationDisposition.ACCEPT,
            note="approve tool replacement",
        ),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="manual-decision-accept-001",
    )
    assert decided["work_order_id"] is not None

    lineage = loop.event_lineage(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        event_id="EVT-RESULT-001",
    )
    assert [item["work_type"] for item in lineage["work_orders"]] == [
        "inspection",
        "maintenance",
    ]
    assert lineage["inspection_results"][0]["work_order_id"] == inspection_work_order_id
    assert lineage["recommendations"][0]["source_product_result_id"] == "RESULT-001"
    assert lineage["decisions"][0]["recommendation_id"] == recommendation_id
    work_order_activities = [
        item for item in lineage["activities"] if item["work_order_id"] is not None
    ]
    assert {item["work_type"] for item in work_order_activities} == {
        "inspection",
        "maintenance",
    }
    assert lineage["maintenance_actions"] == []
    assert lineage["maintenance_events"] == []


def test_manual_recommendation_replay_dedupe_and_conflict(tmp_path) -> None:
    loop = service(tmp_path)
    _work_order_id, inspection_result_id = run_completed_inspection(loop)
    payload = OperationsManualRecommendationCreateRequest(basis=("replace worn tool",))

    first = loop.create_manual_recommendation(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=payload,
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="manual-recommendation-001",
    )
    replay = loop.create_manual_recommendation(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=payload,
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="manual-recommendation-001",
    )
    duplicate = loop.create_manual_recommendation(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=payload,
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="manual-recommendation-002",
    )

    assert replay["recommendation_id"] == first["recommendation_id"]
    assert replay["replayed"] is True
    assert duplicate["recommendation_id"] == first["recommendation_id"]
    assert duplicate["deduplicated"] is True
    assert loop.repository.operational_side_effect_counts()["recommendations"] == 1

    try:
        loop.create_manual_recommendation(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            inspection_result_id=inspection_result_id,
            payload=OperationsManualRecommendationCreateRequest(
                basis=("different command body",)
            ),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="manual-recommendation-001",
        )
    except IdempotencyConflict:
        pass
    else:
        raise AssertionError("reusing an idempotency key with another body must conflict")


def test_no_action_inspection_cannot_create_maintenance_recommendation(tmp_path) -> None:
    loop = service(tmp_path)
    requested = loop.request_inspection(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        payload=inspection_request(),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="inspection-request-001",
    )
    work_order_id = requested["work_order_id"]
    for target, actor, key in (
        (WorkOrderStatus.APPROVED, "manager-1", "inspection-approve-001"),
        (WorkOrderStatus.IN_PROGRESS, "engineer-1", "inspection-start-001"),
    ):
        loop.transition_inspection(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            work_order_id=work_order_id,
            target=target,
            actor_id=actor,
            actor_display_name=actor,
            idempotency_key=key,
        )
    completed = loop.complete_inspection(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        work_order_id=work_order_id,
        payload=inspection_result("no_action_required"),
        actor_id="engineer-1",
        actor_display_name="Engineer One",
        idempotency_key="inspection-complete-001",
    )

    try:
        loop.create_manual_recommendation(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            inspection_result_id=completed["inspection_result_id"],
            payload=OperationsManualRecommendationCreateRequest(basis=("replace",)),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="manual-recommendation-001",
        )
    except ValueError as exc:
        assert "maintenance_recommended" in str(exc)
    else:
        raise AssertionError("no_action_required must not create maintenance work")


def test_inspection_request_fails_closed_for_unknown_or_mismatched_projection(tmp_path) -> None:
    missing = service(tmp_path / "missing", query=ProjectionQuery(None))
    missing.event_evidence_query.projection = None
    with pytest.raises(KeyError, match="EVT-RESULT-001"):
        missing.request_inspection(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            payload=inspection_request(),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="inspection-request-001",
        )

    mismatched = service(
        tmp_path / "mismatch",
        query=ProjectionQuery(canonical_projection(event_id="EVT-OTHER")),
    )
    with pytest.raises(ValueError, match="event_id mismatch"):
        mismatched.request_inspection(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            payload=inspection_request(),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="inspection-request-001",
        )


def test_inspection_request_rejects_non_authorizing_canonical_decision(tmp_path) -> None:
    loop = service(
        tmp_path,
        query=ProjectionQuery(canonical_projection(decision="continue_monitoring")),
    )
    with pytest.raises(ValueError, match="does not authorize an inspection"):
        loop.request_inspection(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            payload=inspection_request(),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="inspection-request-001",
        )


def test_asset_type_is_preserved_from_projection_through_inspection(tmp_path) -> None:
    query = ProjectionQuery(
        canonical_projection(asset_id="CMP-001", asset_type="compressor")
    )
    loop = service(
        tmp_path,
        query=query,
    )
    requested = loop.request_inspection(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        payload=inspection_request(),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="inspection-request-001",
    )
    stored = loop.repository.get_work_order(
        workspace_id="workspace-1",
        work_order_id=requested["work_order_id"],
    )
    assert stored is not None
    assert stored.asset_type == "compressor"
    assert query.calls == [
        {
            "organization_id": "org-1",
            "project_id": "project-1",
            "workspace_id": "workspace-1",
            "event_id": "EVT-RESULT-001",
        }
    ]

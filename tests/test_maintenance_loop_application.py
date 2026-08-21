from __future__ import annotations

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


def service(tmp_path) -> MaintenanceLoopService:
    return MaintenanceLoopService(
        MaintenanceRepository(tmp_path / "maintenance.db", project_context=Resolver())
    )


def inspection_request() -> InspectionWorkOrderCreateRequest:
    return InspectionWorkOrderCreateRequest(
        event_id="EVT-RESULT-001",
        asset_id="CNC-001",
        equipment_id="CNC-001",
        asset_type="cnc",
        operational_decision_kind="review_shutdown",
        source_product_result_id="RESULT-001",
        source_evidence_id="EVIDENCE-001",
        source_action_id="recommendation-policy-v1:review_shutdown",
        source_schema_version="product-result-artifact-v1",
        source_policy_version="recommendation-policy-v1",
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

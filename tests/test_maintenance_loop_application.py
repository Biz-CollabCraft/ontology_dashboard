from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.infra.db.maintenance_repository import MaintenanceRepository
from app.maintenance.api_schema import (
    CostOptionRecommendationCreateRequest,
    InspectionResultCreateRequest,
    InspectionWorkOrderCreateRequest,
    MaintenanceActionCompleteRequest,
    MaintenanceActionStartRequest,
    MaintenanceReplayRequest,
    MaintenanceWorkOrderApproveRequest,
    OperationsManualRecommendationCreateRequest,
    RecommendationDecisionCreateRequest,
    ToolReplacementCostAnalysisCreateRequest,
)
from app.maintenance.cost_analysis_schema import ExecutionTiming
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
    def __init__(
        self,
        projection: dict | None = None,
        *,
        replay_binding: dict | None = None,
        replay_error: ValueError | None = None,
    ) -> None:
        self.projection = projection if projection is not None else canonical_projection()
        self.calls: list[dict] = []
        self.replay_binding = replay_binding
        self.replay_error = replay_error
        self.replay_calls: list[dict] = []

    def event_evidence_projection(self, **scope):
        self.calls.append(scope)
        return self.projection

    def resolve_maintenance_replay_session(self, **values):
        self.replay_calls.append(values)
        if self.replay_error is not None:
            raise self.replay_error
        if self.replay_binding is not None:
            return self.replay_binding
        return {
            "simulation_session_id": values["session_id"],
            "organization_id": values["organization_id"],
            "project_id": values["project_id"],
            "workspace_id": values["workspace_id"],
            "equipment_id": values["equipment_id"],
        }


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
    provider = query or ProjectionQuery()
    return MaintenanceLoopService(
        MaintenanceRepository(tmp_path / "maintenance.db", project_context=Resolver()),
        event_evidence_query=provider,
        replay_session_query=provider,
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


def cost_analysis_request(
    *, missing_parts_cost: bool = False
) -> ToolReplacementCostAnalysisCreateRequest:
    scenarios = []
    for timing in ExecutionTiming:
        scenarios.append(
            {
                "execution_timing": timing,
                "parts_cost": (
                    None
                    if missing_parts_cost
                    else {"low_minor": 45000, "base_minor": 50000, "high_minor": 60000}
                ),
                "labor_duration": {
                    "low_minutes": 20,
                    "base_minutes": 30,
                    "high_minutes": 40,
                },
                "labor_rate_per_minute": {
                    "low_minor_per_minute": 800,
                    "base_minor_per_minute": 1000,
                    "high_minor_per_minute": 1200,
                },
                "external_service_cost": {
                    "low_minor": 0,
                    "base_minor": 0,
                    "high_minor": 0,
                },
                "expected_downtime": {
                    "low_minutes": 30,
                    "base_minutes": 45,
                    "high_minutes": 60,
                },
                "production_loss_rate_per_minute": {
                    "low_minor_per_minute": 900,
                    "base_minor_per_minute": 1100,
                    "high_minor_per_minute": 1300,
                },
                "expected_failure_loss": {
                    "low_minor": 10000,
                    "base_minor": 25000,
                    "high_minor": 50000,
                },
                "confidence": "medium",
            }
        )
    return ToolReplacementCostAnalysisCreateRequest(
        sop_id="SOP-DEMO-CNC-ROTATING-ASSEMBLY-001",
        sop_version="demo-2026-08-28",
        currency="KRW",
        currency_minor_unit=0,
        scenarios=tuple(scenarios),
        assumptions=("Failure loss is a sensitivity input.",),
        input_sources=(
            {
                "input_name": "tool_replacement_quote",
                "source_kind": "quoted",
                "source_reference": "quote/tool-replacement/2026-08",
                "confidence": "medium",
            },
        ),
        price_version="maintenance-price-2026-08",
        calculation_policy_version="maintenance-cost-policy-v1",
    )


def run_completed_inspection(
    loop: MaintenanceLoopService,
    *,
    outcome: str = "maintenance_recommended",
    result_payload: InspectionResultCreateRequest | None = None,
) -> tuple[str, str]:
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
        payload=result_payload or inspection_result(outcome),
        actor_id="engineer-1",
        actor_display_name="Engineer One",
        idempotency_key="inspection-complete-001",
    )
    assert completed["maintenance_event_id"] is None
    return work_order_id, completed["inspection_result_id"]


def run_requested_maintenance(loop: MaintenanceLoopService) -> str:
    _inspection_work_order_id, inspection_result_id = run_completed_inspection(loop)
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
    decided = loop.decide_manual_recommendation(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        recommendation_id=created["recommendation_id"],
        payload=RecommendationDecisionCreateRequest(
            disposition=RecommendationDisposition.ACCEPT,
            note="approve tool replacement",
        ),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="manual-decision-accept-001",
    )
    assert decided["work_order_id"] is not None
    return decided["work_order_id"]


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


def test_maintenance_execution_uses_persisted_lineage_and_emits_replay_events(tmp_path) -> None:
    diagnosis = ProjectionQuery()
    loop = service(tmp_path, query=diagnosis)
    work_order_id = run_requested_maintenance(loop)
    started_at = datetime(2026, 8, 24, 9, 0, tzinfo=timezone.utc)
    completed_at = started_at + timedelta(minutes=30)
    restart_at = completed_at + timedelta(minutes=5)

    approved = loop.approve_maintenance_work_order(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        work_order_id=work_order_id,
        payload=MaintenanceWorkOrderApproveRequest(
            simulation_session_id="SIMULATION-SESSION-001"
        ),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="maintenance-approve-001",
        approved_at=started_at - timedelta(minutes=5),
    )
    action_id = approved["maintenance_action_id"]
    assert approved["maintenance_action_status"] == "planned"
    assert diagnosis.replay_calls == [
        {
            "organization_id": "org-1",
            "project_id": "project-1",
            "workspace_id": "workspace-1",
            "session_id": "SIMULATION-SESSION-001",
            "equipment_id": "CNC-001",
        }
    ]

    started = loop.start_maintenance(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        maintenance_action_id=action_id,
        payload=MaintenanceActionStartRequest(),
        actor_id="technician-1",
        actor_display_name="Technician One",
        idempotency_key="maintenance-start-001",
        started_at=started_at,
    )
    completed = loop.complete_maintenance(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        maintenance_action_id=action_id,
        payload=MaintenanceActionCompleteRequest(outcome="tool replaced"),
        actor_id="technician-1",
        actor_display_name="Technician One",
        idempotency_key="maintenance-complete-001",
        completed_at=completed_at,
    )
    replay = loop.request_maintenance_replay(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        maintenance_event_id=completed["maintenance_event_id"],
        payload=MaintenanceReplayRequest(restart_at=restart_at),
        actor_id="technician-1",
        actor_display_name="Technician One",
        idempotency_key="maintenance-replay-001",
    )

    assert started["status"] == "in_progress"
    assert completed["status"] == "completed"
    assert replay["status"] == "replay_requested"

    lineage = loop.event_lineage(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        event_id="EVT-RESULT-001",
    )
    assert len(lineage["maintenance_actions"]) == 1
    assert lineage["maintenance_actions"][0]["simulation_session_id"] == (
        "SIMULATION-SESSION-001"
    )
    assert lineage["maintenance_actions"][0]["lifecycle_state_version"] == 3
    assert len(lineage["maintenance_events"]) == 1
    assert lineage["maintenance_events"][0]["state_patch"] == {
        "tool_wear_min": {"operation": "reset", "unit": "min", "value": 0}
    }
    equipment_state = loop.repository.equipment_state(
        workspace_id="workspace-1",
        equipment_id="CNC-001",
    )
    assert equipment_state is not None
    assert equipment_state["state"] == {
        "tool_wear_min": {"unit": "min", "value": 0}
    }

    with loop.repository._connect() as connection:
        outbox = connection.execute(
            "SELECT id,event_type,payload_json FROM transactional_outbox "
            "WHERE event_type LIKE 'maintenance.%' ORDER BY id"
        ).fetchall()
    assert all(str(uuid.UUID(row["id"])) == row["id"] for row in outbox)
    assert {
        row["event_type"]: json.loads(row["payload_json"])["state_version"]
        for row in outbox
    } == {
        "maintenance.started": 1,
        "maintenance.completed": 2,
        "maintenance.replay_requested": 3,
    }
    assert all("SIMULATION-SESSION-001" in row["payload_json"] for row in outbox)


def test_maintenance_approval_fails_closed_when_diagnosis_rejects_replay(tmp_path) -> None:
    diagnosis = ProjectionQuery(
        replay_error=ValueError("replay session is not available in the requested scope")
    )
    loop = service(tmp_path, query=diagnosis)
    work_order_id = run_requested_maintenance(loop)

    with pytest.raises(ValueError, match="not available in the requested scope"):
        loop.approve_maintenance_work_order(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            work_order_id=work_order_id,
            payload=MaintenanceWorkOrderApproveRequest(
                simulation_session_id="FORGED-SESSION"
            ),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="maintenance-approve-rejected-001",
        )

    lineage = loop.event_lineage(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        event_id="EVT-RESULT-001",
    )
    assert lineage["maintenance_actions"] == []


def test_maintenance_approval_fails_closed_until_diagnosis_provider_is_wired(
    tmp_path,
) -> None:
    loop = MaintenanceLoopService(
        MaintenanceRepository(tmp_path / "maintenance.db", project_context=Resolver()),
        event_evidence_query=ProjectionQuery(),
    )
    work_order_id = run_requested_maintenance(loop)

    with pytest.raises(ValueError, match="validation is unavailable"):
        loop.approve_maintenance_work_order(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            work_order_id=work_order_id,
            payload=MaintenanceWorkOrderApproveRequest(
                simulation_session_id="SIMULATION-SESSION-001"
            ),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="maintenance-approve-provider-missing-001",
        )

    assert loop.repository.operational_side_effect_counts()["maintenance_actions"] == 0


@pytest.mark.parametrize(
    ("field", "invalid_value", "message"),
    (
        ("project_id", "another-project", "project_id scope mismatch"),
        ("equipment_id", "CNC-999", "equipment identity mismatch"),
        (
            "simulation_session_id",
            "ANOTHER-SESSION",
            "canonical identity mismatch",
        ),
    ),
)
def test_maintenance_approval_rejects_noncanonical_replay_binding(
    tmp_path, field: str, invalid_value: str, message: str
) -> None:
    binding = {
        "simulation_session_id": "SIMULATION-SESSION-001",
        "organization_id": "org-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "equipment_id": "CNC-001",
    }
    binding[field] = invalid_value
    loop = service(tmp_path, query=ProjectionQuery(replay_binding=binding))
    work_order_id = run_requested_maintenance(loop)

    with pytest.raises(ValueError, match=message):
        loop.approve_maintenance_work_order(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            work_order_id=work_order_id,
            payload=MaintenanceWorkOrderApproveRequest(
                simulation_session_id="SIMULATION-SESSION-001"
            ),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key=f"maintenance-approve-{field}-001",
        )


def test_maintenance_execution_commands_are_idempotent(tmp_path) -> None:
    loop = service(tmp_path)
    work_order_id = run_requested_maintenance(loop)
    approve_payload = MaintenanceWorkOrderApproveRequest(
        simulation_session_id="SIMULATION-SESSION-001"
    )
    command = {
        "organization_id": "org-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "work_order_id": work_order_id,
        "payload": approve_payload,
        "actor_id": "manager-1",
        "actor_display_name": "Manager One",
        "idempotency_key": "maintenance-approve-001",
    }
    first = loop.approve_maintenance_work_order(**command)
    second = loop.approve_maintenance_work_order(**command)

    assert second["maintenance_action_id"] == first["maintenance_action_id"]
    assert second["replayed"] is True
    assert loop.repository.operational_side_effect_counts()["maintenance_actions"] == 1

    with pytest.raises(IdempotencyConflict):
        loop.approve_maintenance_work_order(
            **{
                **command,
                "payload": MaintenanceWorkOrderApproveRequest(
                    simulation_session_id="ANOTHER-SIMULATION-SESSION"
                ),
            }
        )


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


def test_cost_analysis_resolves_lineage_and_persists_read_only_snapshot(tmp_path) -> None:
    loop = service(tmp_path)
    inspection_work_order_id, inspection_result_id = run_completed_inspection(loop)
    calculated_at = datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc)

    created = loop.calculate_tool_replacement_cost(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=cost_analysis_request(),
        actor_id="manager-1",
        idempotency_key="cost-analysis-request-001",
        calculated_at=calculated_at,
    )

    result = created["cost_analysis"]
    assert created["calculation_status"] == "calculated"
    assert created["replayed"] is False
    assert result["asset_id"] == result["equipment_id"] == "CNC-001"
    assert result["based_on"] == {
        "product_result_id": "RESULT-001",
        "evidence_id": "EVD-EVT-RESULT-001",
        "inspection_work_order_id": inspection_work_order_id,
        "inspection_result_id": inspection_result_id,
        "sop_id": "SOP-DEMO-CNC-ROTATING-ASSEMBLY-001",
        "sop_version": "demo-2026-08-28",
    }
    assert {
        option["action_candidate_id"] for option in result["options"]
    } == {
        loop._stable_id(
            "ACTION-CANDIDATE",
            "org-1",
            "project-1",
            "workspace-1",
            inspection_result_id,
            "TOOL_REPLACEMENT",
        )
    }

    loaded = loop.get_cost_analysis(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        analysis_id=created["analysis_id"],
    )
    listed = loop.list_cost_analyses(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
    )
    assert loaded == result
    assert listed == {
        "inspection_result_id": inspection_result_id,
        "items": [result],
    }
    side_effects = loop.repository.operational_side_effect_counts()
    assert side_effects["recommendations"] == 0
    assert side_effects["decisions"] == 0
    assert side_effects["maintenance_actions"] == 0
    assert side_effects["maintenance_events"] == 0

    with sqlite3.connect(loop.repository.database) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE closed_loop_maintenance_cost_analyses "
                "SET result_json='{}' WHERE analysis_id=?",
                (created["analysis_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM closed_loop_maintenance_cost_analyses WHERE analysis_id=?",
                (created["analysis_id"],),
            )

    assert loop.get_cost_analysis(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        analysis_id=created["analysis_id"],
    ) == result


def test_cost_analysis_is_idempotent_but_new_request_appends_snapshot(tmp_path) -> None:
    loop = service(tmp_path)
    _work_order_id, inspection_result_id = run_completed_inspection(loop)
    payload = cost_analysis_request()
    command = {
        "organization_id": "org-1",
        "project_id": "project-1",
        "workspace_id": "workspace-1",
        "inspection_result_id": inspection_result_id,
        "payload": payload,
        "actor_id": "manager-1",
        "idempotency_key": "cost-analysis-request-001",
        "calculated_at": datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc),
    }

    first = loop.calculate_tool_replacement_cost(**command)
    replay = loop.calculate_tool_replacement_cost(**command)
    second_snapshot = loop.calculate_tool_replacement_cost(
        **{
            **command,
            "idempotency_key": "cost-analysis-request-002",
            "calculated_at": datetime(2026, 8, 31, 1, 5, tzinfo=timezone.utc),
        }
    )

    assert replay == {**first, "replayed": True}
    assert second_snapshot["analysis_id"] != first["analysis_id"]
    assert len(
        loop.repository.list_cost_analyses(
            workspace_id="workspace-1",
            inspection_result_id=inspection_result_id,
        )
    ) == 2

    with pytest.raises(IdempotencyConflict, match="idempotency_key_conflict"):
        loop.calculate_tool_replacement_cost(
            **{
                **command,
                "payload": payload.model_copy(
                    update={"price_version": "maintenance-price-2026-09"}
                ),
            }
        )


def test_insufficient_cost_analysis_is_preserved_without_operational_effects(
    tmp_path,
) -> None:
    loop = service(tmp_path)
    _work_order_id, inspection_result_id = run_completed_inspection(loop)

    created = loop.calculate_tool_replacement_cost(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=cost_analysis_request(missing_parts_cost=True),
        actor_id="manager-1",
        idempotency_key="cost-analysis-insufficient-001",
    )

    assert created["calculation_status"] == "insufficient"
    assert created["cost_analysis"]["lowest_calculated_cost_option_id"] is None
    assert created["cost_analysis"]["missing_inputs"] == ["parts_cost"]
    assert loop.repository.operational_side_effect_counts()["recommendations"] == 0


def test_cost_analysis_rejects_no_action_inspection_without_persisting(tmp_path) -> None:
    loop = service(tmp_path)
    _work_order_id, inspection_result_id = run_completed_inspection(
        loop,
        outcome="no_action_required",
    )

    with pytest.raises(ValueError, match="maintenance_recommended"):
        loop.calculate_tool_replacement_cost(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            inspection_result_id=inspection_result_id,
            payload=cost_analysis_request(),
            actor_id="manager-1",
            idempotency_key="cost-analysis-request-001",
        )

    assert loop.repository.list_cost_analyses(
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
    ) == ()


def test_cost_analysis_rejects_unrelated_maintenance_candidate_without_persisting(
    tmp_path,
) -> None:
    loop = service(tmp_path)
    _work_order_id, inspection_result_id = run_completed_inspection(
        loop,
        result_payload=InspectionResultCreateRequest(
            outcome="maintenance_recommended",
            checklist=(
                {
                    "item_id": "cooling-path",
                    "status": "fail",
                    "note": "coolant flow is restricted",
                },
            ),
            measurements=(
                {"name": "coolant_temperature_c", "value": 92, "unit": "C"},
            ),
            findings=("cooling path requires maintenance",),
            note="tool wear was not confirmed",
        ),
    )

    with pytest.raises(ValueError, match="TOOL_REPLACEMENT candidate requires"):
        loop.calculate_tool_replacement_cost(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            inspection_result_id=inspection_result_id,
            payload=cost_analysis_request(),
            actor_id="manager-1",
            idempotency_key="cost-analysis-request-001",
        )

    assert loop.repository.list_cost_analyses(
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
    ) == ()


def test_human_selected_cost_option_creates_only_proposed_recommendation(tmp_path) -> None:
    loop = service(tmp_path)
    _work_order_id, inspection_result_id = run_completed_inspection(loop)
    analysis = loop.calculate_tool_replacement_cost(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=cost_analysis_request(),
        actor_id="manager-1",
        idempotency_key="cost-analysis-request-001",
    )["cost_analysis"]
    selected = next(
        option
        for option in analysis["options"]
        if option["execution_timing"] == "immediate"
    )

    created = loop.create_recommendation_from_cost_option(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        analysis_id=analysis["analysis_id"],
        option_id=selected["option_id"],
        payload=CostOptionRecommendationCreateRequest(
            basis=("manager selected immediate tool replacement",)
        ),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="cost-option-recommendation-001",
    )
    replay = loop.create_recommendation_from_cost_option(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        analysis_id=analysis["analysis_id"],
        option_id=selected["option_id"],
        payload=CostOptionRecommendationCreateRequest(
            basis=("manager selected immediate tool replacement",)
        ),
        actor_id="manager-1",
        actor_display_name="Manager One",
        idempotency_key="cost-option-recommendation-001",
    )

    recommendation = created["recommendation"]
    assert replay == {**created, "replayed": True}
    assert recommendation["status"] == "proposed"
    assert recommendation["source_inspection_reference"] == inspection_result_id
    assert recommendation["source_cost_analysis_id"] == analysis["analysis_id"]
    assert recommendation["source_cost_option_id"] == selected["option_id"]
    assert (
        recommendation["source_action_candidate_id"]
        == selected["action_candidate_id"]
    )
    assert recommendation["action_code"] == "TOOL_REPLACEMENT"
    assert "execution_timing:immediate" in recommendation["basis"]
    side_effects = loop.repository.operational_side_effect_counts()
    assert side_effects == {
        "recommendations": 1,
        "decisions": 0,
        "work_orders": 1,
        "maintenance_actions": 0,
        "maintenance_events": 0,
    }

    planned = next(
        option
        for option in analysis["options"]
        if option["execution_timing"] == "planned_window"
    )
    with pytest.raises(IdempotencyConflict, match="idempotency_key_conflict"):
        loop.create_recommendation_from_cost_option(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            analysis_id=analysis["analysis_id"],
            option_id=planned["option_id"],
            payload=CostOptionRecommendationCreateRequest(
                basis=("manager selected planned tool replacement",)
            ),
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="cost-option-recommendation-001",
        )


def test_non_executable_or_insufficient_cost_option_cannot_create_recommendation(
    tmp_path,
) -> None:
    loop = service(tmp_path)
    _work_order_id, inspection_result_id = run_completed_inspection(loop)
    analysis = loop.calculate_tool_replacement_cost(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=cost_analysis_request(),
        actor_id="manager-1",
        idempotency_key="cost-analysis-request-001",
    )["cost_analysis"]
    request = CostOptionRecommendationCreateRequest(basis=("human selection",))

    for timing in ("reinspect_after", "no_action_baseline"):
        selected = next(
            option
            for option in analysis["options"]
            if option["execution_timing"] == timing
        )
        with pytest.raises(ValueError, match="cannot create a maintenance recommendation"):
            loop.create_recommendation_from_cost_option(
                organization_id="org-1",
                project_id="project-1",
                workspace_id="workspace-1",
                analysis_id=analysis["analysis_id"],
                option_id=selected["option_id"],
                payload=request,
                actor_id="manager-1",
                actor_display_name="Manager One",
                idempotency_key=f"cost-option-{timing}",
            )

    with pytest.raises(ValueError, match="does not belong"):
        loop.create_recommendation_from_cost_option(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            analysis_id=analysis["analysis_id"],
            option_id="FORGED-OPTION",
            payload=request,
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="cost-option-forged",
        )

    insufficient = loop.calculate_tool_replacement_cost(
        organization_id="org-1",
        project_id="project-1",
        workspace_id="workspace-1",
        inspection_result_id=inspection_result_id,
        payload=cost_analysis_request(missing_parts_cost=True),
        actor_id="manager-1",
        idempotency_key="cost-analysis-insufficient-001",
    )["cost_analysis"]
    insufficient_option = next(
        option
        for option in insufficient["options"]
        if option["execution_timing"] == "immediate"
    )
    with pytest.raises(ValueError, match="insufficient cost option"):
        loop.create_recommendation_from_cost_option(
            organization_id="org-1",
            project_id="project-1",
            workspace_id="workspace-1",
            analysis_id=insufficient["analysis_id"],
            option_id=insufficient_option["option_id"],
            payload=request,
            actor_id="manager-1",
            actor_display_name="Manager One",
            idempotency_key="cost-option-insufficient",
        )

    assert loop.repository.operational_side_effect_counts()["recommendations"] == 0

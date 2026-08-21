"""Canonical Maintenance application service for the two-stage human loop."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from app.diagnosis.ports import EventEvidenceProjectionQueryPort

from .api_schema import (
    InspectionResultCreateRequest,
    InspectionWorkOrderCreateRequest,
    OperationsManualRecommendationCreateRequest,
    RecommendationDecisionCreateRequest,
)
from .maintenance_domain import (
    apply_recommendation_decision,
    create_inspection_work_order,
    create_operations_manual_recommendation,
    create_work_order_for_recommendation,
    transition_work_order,
)
from .maintenance_schema import (
    EquipmentIdentity,
    InspectionOutcome,
    InspectionResult,
    OperationalDecisionKind,
    RecommendationDecision,
    RecommendationDisposition,
    WorkOrderStatus,
    WorkOrderType,
)
from .ports import MaintenanceCommandRepositoryPort


class MaintenanceLoopService:
    def __init__(
        self,
        repository: MaintenanceCommandRepositoryPort,
        *,
        event_evidence_query: EventEvidenceProjectionQueryPort,
    ) -> None:
        self.repository = repository
        self.event_evidence_query = event_evidence_query

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        source = ":".join(parts)
        return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, source)}"

    @staticmethod
    def _fingerprint(command: str, payload: Any) -> str:
        body = (
            payload.model_dump(mode="json")
            if hasattr(payload, "model_dump")
            else payload
        )
        encoded = json.dumps(
            {"command": command, "payload": body},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _require_scope(record: Any, *, organization_id: str, project_id: str, workspace_id: str) -> None:
        for field, expected in (
            ("organization_id", organization_id),
            ("project_id", project_id),
            ("workspace_id", workspace_id),
        ):
            if getattr(record, field) != expected:
                raise ValueError(f"{field} scope mismatch")

    @staticmethod
    def _required_text(values: Mapping[str, Any], field: str) -> str:
        value = values.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Event Evidence Projection requires {field}")
        return value

    def _inspection_source(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        event_id: str,
    ) -> tuple[EquipmentIdentity, OperationalDecisionKind, dict[str, str]]:
        projection = self.event_evidence_query.event_evidence_projection(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            event_id=event_id,
        )
        if projection is None:
            raise KeyError(event_id)
        if projection.get("contract_type") != "event_evidence_projection":
            raise ValueError("Diagnosis query returned a non-canonical evidence contract")
        if projection.get("schema_version") != "event-evidence-projection-v1":
            raise ValueError("unsupported Event Evidence Projection schema version")
        if self._required_text(projection, "event_id") != event_id:
            raise ValueError("Event Evidence Projection event_id mismatch")

        subject = projection.get("subject")
        artifact = projection.get("artifact_reference")
        assessment = projection.get("assessment")
        report = projection.get("report_projection")
        provenance = projection.get("provenance")
        if not all(
            isinstance(value, Mapping)
            for value in (subject, artifact, assessment, report, provenance)
        ):
            raise ValueError("Event Evidence Projection is missing authorization sections")

        asset_id = self._required_text(artifact, "asset_id")
        asset_type = self._required_text(artifact, "asset_type")
        if self._required_text(artifact, "event_id") != event_id:
            raise ValueError("Event Evidence Projection artifact event_id mismatch")
        equipment_id = self._required_text(subject, "equipment_id")
        if equipment_id != asset_id:
            raise ValueError("Event Evidence Projection equipment identity mismatch")
        subject_asset_type = self._required_text(subject, "asset_type")
        if subject_asset_type != asset_type:
            raise ValueError("Event Evidence Projection asset_type mismatch")

        decision_raw = assessment.get("operational_decision_kind")
        try:
            decision = OperationalDecisionKind(decision_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Event Evidence Projection has no supported operational decision"
            ) from exc
        if decision not in {
            OperationalDecisionKind.REQUEST_INSPECTION,
            OperationalDecisionKind.REVIEW_SHUTDOWN,
        }:
            raise ValueError(
                "Event Evidence Projection does not authorize an inspection"
            )

        actions = report.get("recommended_actions")
        if not isinstance(actions, list) or len(actions) != 1:
            raise ValueError(
                "Event Evidence Projection requires one canonical recommendation"
            )
        action = actions[0]
        if not isinstance(action, Mapping):
            raise ValueError("Event Evidence Projection recommendation must be an object")
        source_action_id = self._required_text(action, "action_id")
        if source_action_id != decision.value:
            raise ValueError(
                "Event Evidence Projection decision does not match its source action"
            )

        lineage = provenance.get("lineage")
        if not isinstance(lineage, Mapping):
            raise ValueError("Event Evidence Projection provenance.lineage is required")
        source = {
            "source_product_result_id": self._required_text(artifact, "artifact_id"),
            "source_evidence_id": self._required_text(projection, "evidence_id"),
            "source_action_id": source_action_id,
            "source_schema_version": self._required_text(
                artifact, "artifact_schema_version"
            ),
            "source_policy_version": self._required_text(lineage, "policy_version"),
        }
        return (
            EquipmentIdentity(
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                asset_id=asset_id,
                equipment_id=equipment_id,
                asset_type=asset_type,
            ),
            decision,
            source,
        )

    def request_inspection(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        payload: InspectionWorkOrderCreateRequest,
        actor_id: str,
        actor_display_name: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        identity, operational_decision, source = self._inspection_source(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            event_id=payload.event_id,
        )
        work_order_id = self._stable_id(
            "INSPECTION-WO",
            organization_id,
            project_id,
            workspace_id,
            payload.event_id,
            identity.equipment_id,
            source["source_product_result_id"],
            source["source_action_id"],
        )
        work_order = create_inspection_work_order(
            work_order_id=work_order_id,
            identity=identity,
            event_id=payload.event_id,
            operational_decision=operational_decision,
            source_product_result_id=source["source_product_result_id"],
            source_evidence_id=source["source_evidence_id"],
            source_action_id=source["source_action_id"],
            source_schema_version=source["source_schema_version"],
            source_policy_version=source["source_policy_version"],
            idempotency_key=idempotency_key,
        )
        return self.repository.create_inspection_work_order(
            work_order=work_order,
            actor_id=actor_id,
            actor_display_name=actor_display_name,
            request_idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint(
                "inspection.request",
                {"payload": payload.model_dump(mode="json"), "actor_id": actor_id},
            ),
        )

    def transition_inspection(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        work_order_id: str,
        target: WorkOrderStatus,
        actor_id: str,
        actor_display_name: str,
        idempotency_key: str,
        transitioned_at: datetime | None = None,
    ) -> dict[str, Any]:
        work_order = self.repository.get_work_order(
            workspace_id=workspace_id,
            work_order_id=work_order_id,
        )
        if work_order is None:
            raise KeyError(work_order_id)
        self._require_scope(
            work_order,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if work_order.work_type is not WorkOrderType.INSPECTION:
            raise ValueError("work order is not an inspection")
        transitioned = work_order.model_copy(
            update={"status": transition_work_order(work_order.status, target)}
        )
        return self.repository.transition_inspection_work_order(
            work_order=transitioned,
            actor_id=actor_id,
            actor_display_name=actor_display_name,
            transitioned_at=transitioned_at or datetime.now(timezone.utc),
            request_idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint(
                f"inspection.{target.value}",
                {
                    "work_order_id": work_order_id,
                    "target": target.value,
                    "actor_id": actor_id,
                },
            ),
        )

    def complete_inspection(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        work_order_id: str,
        payload: InspectionResultCreateRequest,
        actor_id: str,
        actor_display_name: str,
        idempotency_key: str,
        recorded_at: datetime | None = None,
    ) -> dict[str, Any]:
        work_order = self.repository.get_work_order(
            workspace_id=workspace_id,
            work_order_id=work_order_id,
        )
        if work_order is None:
            raise KeyError(work_order_id)
        self._require_scope(
            work_order,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        completed_at = recorded_at or datetime.now(timezone.utc)
        completed = work_order.model_copy(
            update={
                "status": transition_work_order(
                    work_order.status,
                    WorkOrderStatus.COMPLETED,
                )
            }
        )
        inspection_result = InspectionResult(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            inspection_result_id=self._stable_id(
                "INSPECTION-RESULT",
                organization_id,
                project_id,
                workspace_id,
                work_order_id,
            ),
            work_order_id=work_order_id,
            event_id=work_order.event_id,
            asset_id=work_order.asset_id,
            equipment_id=work_order.equipment_id,
            asset_type=work_order.asset_type,
            outcome=payload.outcome,
            checklist=payload.checklist,
            measurements=payload.measurements,
            findings=payload.findings,
            note=payload.note,
            recorded_by=actor_id,
            recorded_at=completed_at,
        )
        return self.repository.complete_inspection(
            work_order=completed,
            inspection_result=inspection_result,
            actor_display_name=actor_display_name,
            request_idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint(
                "inspection.complete",
                {
                    "work_order_id": work_order_id,
                    "payload": payload.model_dump(mode="json"),
                    "actor_id": actor_id,
                },
            ),
        )

    def create_manual_recommendation(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        inspection_result_id: str,
        payload: OperationsManualRecommendationCreateRequest,
        actor_id: str,
        actor_display_name: str,
        idempotency_key: str,
        authored_at: datetime | None = None,
    ) -> dict[str, Any]:
        inspection_result = self.repository.get_inspection_result(
            workspace_id=workspace_id,
            inspection_result_id=inspection_result_id,
        )
        if inspection_result is None:
            raise KeyError(inspection_result_id)
        self._require_scope(
            inspection_result,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if inspection_result.outcome is not InspectionOutcome.MAINTENANCE_RECOMMENDED:
            raise ValueError(
                "operations manual recommendation requires maintenance_recommended inspection outcome"
            )
        inspection_work_order = self.repository.get_work_order(
            workspace_id=workspace_id,
            work_order_id=inspection_result.work_order_id,
        )
        if inspection_work_order is None:
            raise KeyError(inspection_result.work_order_id)
        authorization = inspection_work_order.authorization
        recommendation = create_operations_manual_recommendation(
            identity=EquipmentIdentity(
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                asset_id=inspection_result.asset_id,
                equipment_id=inspection_result.equipment_id,
                asset_type=inspection_result.asset_type,
            ),
            event_id=inspection_result.event_id,
            source_product_result_id=str(authorization.source_product_result_id),
            source_evidence_id=str(authorization.source_evidence_id),
            source_schema_version=str(authorization.source_schema_version),
            source_inspection_work_order_id=inspection_result.work_order_id,
            source_inspection_reference=inspection_result.inspection_result_id,
            authored_by=actor_id,
            authored_at=authored_at or datetime.now(timezone.utc),
            basis=(
                f"inspection_result:{inspection_result.inspection_result_id}",
                *payload.basis,
            ),
        )
        return self.repository.create_manual_recommendation(
            recommendation=recommendation,
            actor_display_name=actor_display_name,
            request_idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint(
                "operations_manual.create",
                {
                    "inspection_result_id": inspection_result_id,
                    "payload": payload.model_dump(mode="json"),
                    "actor_id": actor_id,
                },
            ),
        )

    def decide_manual_recommendation(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        recommendation_id: str,
        payload: RecommendationDecisionCreateRequest,
        actor_id: str,
        actor_display_name: str,
        idempotency_key: str,
        decided_at: datetime | None = None,
    ) -> dict[str, Any]:
        recommendation = self.repository.get_recommendation(
            workspace_id=workspace_id,
            recommendation_id=recommendation_id,
        )
        if recommendation is None:
            raise KeyError(recommendation_id)
        self._require_scope(
            recommendation,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if recommendation.recommendation_origin != "operations_manual":
            raise ValueError("only operations_manual recommendations use this command")
        timestamp = decided_at or datetime.now(timezone.utc)
        decision = RecommendationDecision(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            decision_id=self._stable_id(
                "RECOMMENDATION-DECISION",
                organization_id,
                project_id,
                workspace_id,
                recommendation_id,
                idempotency_key,
            ),
            event_id=recommendation.event_id,
            recommendation_id=recommendation_id,
            disposition=payload.disposition,
            actor_id=actor_id,
            decided_at=timestamp,
            note=payload.note,
        )
        decided = apply_recommendation_decision(recommendation, decision)
        work_order = None
        if payload.disposition is RecommendationDisposition.ACCEPT:
            work_order = create_work_order_for_recommendation(
                work_order_id=self._stable_id(
                    "MAINTENANCE-WO",
                    organization_id,
                    project_id,
                    workspace_id,
                    recommendation_id,
                ),
                recommendation=decided,
                decision=decision,
                idempotency_key=idempotency_key,
            )
        return self.repository.decide_recommendation(
            recommendation=decided,
            decision=decision,
            work_order=work_order,
            request_idempotency_key=idempotency_key,
            request_fingerprint=self._fingerprint(
                "recommendation.decision",
                {
                    "recommendation_id": recommendation_id,
                    "payload": payload.model_dump(mode="json"),
                    "actor_id": actor_id,
                },
            ),
            actor_display_name=actor_display_name,
        )

    def event_lineage(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str,
        event_id: str,
    ) -> dict[str, Any]:
        lineage = self.repository.event_lineage(
            workspace_id=workspace_id,
            event_id=event_id,
        )
        for collection in (
            "recommendations",
            "decisions",
            "work_orders",
            "inspection_results",
            "maintenance_actions",
            "maintenance_events",
            "activities",
        ):
            for record in lineage[collection]:
                for field, expected in (
                    ("organization_id", organization_id),
                    ("project_id", project_id),
                    ("workspace_id", workspace_id),
                ):
                    if record.get(field) != expected:
                        raise ValueError(f"{field} scope mismatch")
        return lineage


__all__ = ["MaintenanceLoopService"]

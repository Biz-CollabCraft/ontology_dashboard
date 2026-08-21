"""Canonical Maintenance value objects for recommendation materialization."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OperationalDecisionKind(StrEnum):
    CONTINUE_MONITORING = "continue_monitoring"
    REQUEST_INSPECTION = "request_inspection"
    REVIEW_SHUTDOWN = "review_shutdown"
    HOLD_FOR_DATA_CHECK = "hold_for_data_check"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopedRecord(FrozenModel):
    organization_id: str = Field(min_length=1, max_length=160)
    project_id: str = Field(min_length=1, max_length=160)
    workspace_id: str = Field(min_length=1, max_length=160)


class RecommendationStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"


class RecommendationDisposition(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    DEFER = "defer"


class WorkOrderType(StrEnum):
    INSPECTION = "inspection"
    MAINTENANCE = "maintenance"


class WorkOrderStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MaintenanceActionStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MaterializationStrategy(StrEnum):
    RUNTIME_GENERATED = "runtime_generated"
    IMPORTED_PRECOMPUTED = "imported_precomputed"


class EquipmentIdentity(ScopedRecord):
    asset_id: str = Field(min_length=1, max_length=240)
    equipment_id: str = Field(min_length=1, max_length=240)
    asset_type: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def require_mvp_identity(self) -> EquipmentIdentity:
        if self.asset_id != self.equipment_id:
            raise ValueError("MVP identity requires equipment_id = asset_id")
        return self


class OperationalRecommendedAction(ScopedRecord):
    recommendation_id: str = Field(min_length=1, max_length=240)
    recommendation_origin: Literal["product_result_projection"] = "product_result_projection"
    status: RecommendationStatus = RecommendationStatus.PROPOSED
    materialization_strategy: Literal[MaterializationStrategy.RUNTIME_GENERATED] = (
        MaterializationStrategy.RUNTIME_GENERATED
    )
    asset_id: str = Field(min_length=1, max_length=240)
    equipment_id: str = Field(min_length=1, max_length=240)
    event_id: str = Field(min_length=1, max_length=240)
    source_action_id: str = Field(min_length=1, max_length=240)
    source_product_result_id: str = Field(min_length=1, max_length=240)
    source_evidence_id: str = Field(min_length=1, max_length=240)
    source_schema_version: str = Field(min_length=1, max_length=160)
    source_policy_version: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=500)
    kind: str = Field(min_length=1, max_length=128)
    requires_human_approval: bool
    basis: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_mvp_identity(self) -> OperationalRecommendedAction:
        if self.asset_id != self.equipment_id:
            raise ValueError("MVP recommendation requires equipment_id = asset_id")
        return self

    @property
    def materialization_key(self) -> str:
        return f"{self.source_product_result_id}:{self.source_action_id}"


class RecommendationDecision(ScopedRecord):
    decision_id: str = Field(min_length=1, max_length=240)
    event_id: str = Field(min_length=1, max_length=240)
    recommendation_id: str = Field(min_length=1, max_length=240)
    disposition: RecommendationDisposition
    actor_id: str = Field(min_length=1, max_length=240)
    decided_at: datetime
    note: str = Field(default="", max_length=4000)


class WorkOrder(ScopedRecord):
    work_order_id: str = Field(min_length=1, max_length=240)
    event_id: str = Field(min_length=1, max_length=240)
    asset_id: str = Field(min_length=1, max_length=240)
    equipment_id: str = Field(min_length=1, max_length=240)
    work_type: WorkOrderType
    status: WorkOrderStatus = WorkOrderStatus.REQUESTED


class MaintenanceAction(ScopedRecord):
    maintenance_action_id: str = Field(min_length=1, max_length=240)
    work_order_id: str = Field(min_length=1, max_length=240)
    event_id: str = Field(min_length=1, max_length=240)
    recommendation_id: str = Field(min_length=1, max_length=240)
    recommendation_decision_id: str = Field(min_length=1, max_length=240)
    status: MaintenanceActionStatus = MaintenanceActionStatus.PLANNED


class MaintenanceEvent(ScopedRecord):
    maintenance_event_id: str = Field(min_length=1, max_length=240)
    maintenance_action_id: str = Field(min_length=1, max_length=240)
    work_order_id: str = Field(min_length=1, max_length=240)
    event_id: str = Field(min_length=1, max_length=240)
    recommendation_id: str = Field(min_length=1, max_length=240)
    recommendation_decision_id: str = Field(min_length=1, max_length=240)
    completed_at: datetime
    outcome: str = Field(min_length=1, max_length=4000)

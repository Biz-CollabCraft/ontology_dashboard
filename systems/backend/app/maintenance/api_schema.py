"""Product-facing command contracts for the canonical Maintenance loop."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .maintenance_schema import (
    InspectionChecklistItem,
    InspectionMeasurement,
    InspectionOutcome,
    RecommendationDisposition,
)


class StrictCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectionWorkOrderCreateRequest(StrictCommand):
    """Request an inspection for an existing canonical Diagnosis event.

    Every authorization and equipment-lineage field is resolved server-side
    from the Diagnosis-owned Event Evidence Projection.  Accepting those
    fields from a caller would let the caller forge the authorization basis.
    """

    event_id: str = Field(min_length=1, max_length=240)


class InspectionResultCreateRequest(StrictCommand):
    outcome: InspectionOutcome
    checklist: tuple[InspectionChecklistItem, ...] = Field(min_length=1)
    measurements: tuple[InspectionMeasurement, ...] = ()
    findings: tuple[str, ...] = Field(min_length=1)
    note: str = Field(default="", max_length=4000)


class OperationsManualRecommendationCreateRequest(StrictCommand):
    action_code: Literal["TOOL_REPLACEMENT"] = "TOOL_REPLACEMENT"
    basis: tuple[str, ...] = Field(min_length=1)


class RecommendationDecisionCreateRequest(StrictCommand):
    disposition: RecommendationDisposition
    note: str = Field(default="", max_length=4000)


class MaintenanceWorkOrderApproveRequest(StrictCommand):
    """Bind an approved maintenance action to the active simulation context."""

    simulation_session_id: str = Field(min_length=1, max_length=240)


class MaintenanceActionStartRequest(StrictCommand):
    """The target action and canonical lineage are resolved from the route ID."""


class MaintenanceActionCompleteRequest(StrictCommand):
    outcome: str = Field(min_length=1, max_length=4000)


class MaintenanceReplayRequest(StrictCommand):
    restart_at: datetime

    @field_validator("restart_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("restart_at must include timezone")
        return value


__all__ = [
    "InspectionResultCreateRequest",
    "InspectionWorkOrderCreateRequest",
    "MaintenanceActionCompleteRequest",
    "MaintenanceActionStartRequest",
    "MaintenanceReplayRequest",
    "MaintenanceWorkOrderApproveRequest",
    "OperationsManualRecommendationCreateRequest",
    "RecommendationDecisionCreateRequest",
]

"""Product-facing command contracts for the canonical Maintenance loop."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .maintenance_schema import (
    InspectionChecklistItem,
    InspectionMeasurement,
    InspectionOutcome,
    OperationalDecisionKind,
    RecommendationDisposition,
)


class StrictCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InspectionWorkOrderCreateRequest(StrictCommand):
    event_id: str = Field(min_length=1, max_length=240)
    asset_id: str = Field(min_length=1, max_length=240)
    equipment_id: str = Field(min_length=1, max_length=240)
    asset_type: Literal["cnc"] = "cnc"
    operational_decision_kind: OperationalDecisionKind
    source_product_result_id: str = Field(min_length=1, max_length=240)
    source_evidence_id: str = Field(min_length=1, max_length=240)
    source_action_id: str = Field(min_length=1, max_length=240)
    source_schema_version: str = Field(min_length=1, max_length=160)
    source_policy_version: str = Field(min_length=1, max_length=160)


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


__all__ = [
    "InspectionResultCreateRequest",
    "InspectionWorkOrderCreateRequest",
    "OperationsManualRecommendationCreateRequest",
    "RecommendationDecisionCreateRequest",
]

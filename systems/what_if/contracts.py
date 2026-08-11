"""Contracts for the synthetic preventive What-if result producer.

This package deliberately emits structured analysis only. Role-aware prose and
UI rendering remain consumers of this contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActionCode(str, Enum):
    TOOL_REPLACEMENT = "TOOL_REPLACEMENT"
    CUTTING_LOAD_REDUCTION = "CUTTING_LOAD_REDUCTION"
    COOLING_SYSTEM_RESTORE = "COOLING_SYSTEM_RESTORE"


class EffectScope(str, Enum):
    SYNTHETIC_COUNTERFACTUAL_SIMULATION = "synthetic_counterfactual_simulation"


class LimitationCode(str, Enum):
    SYNTHETIC_DATA_ONLY = "SYNTHETIC_DATA_ONLY"
    NOT_CAUSAL_PROOF = "NOT_CAUSAL_PROOF"
    NOT_REAL_WORLD_EFFECT_GUARANTEE = "NOT_REAL_WORLD_EFFECT_GUARANTEE"
    CONTRACT_FIXTURE_ONLY = "CONTRACT_FIXTURE_ONLY"


class IndicatorDirection(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    RISK_UP = "risk_up"
    RISK_DOWN = "risk_down"


class SourceReference(StrictModel):
    source: str = Field(min_length=1)
    source_field: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    period_from: datetime | None = None
    period_to: datetime | None = None

    @model_validator(mode="after")
    def validate_period(self) -> SourceReference:
        if self.period_from and self.period_to and self.period_to < self.period_from:
            raise ValueError("period_to must not precede period_from")
        return self


class RiseEvent(StrictModel):
    started_at: datetime
    peak_at: datetime
    baseline_probability: float = Field(ge=0, le=1)
    peak_probability: float = Field(ge=0, le=1)
    probability_delta: float = Field(ge=0, le=1)
    duration_hours: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_rise(self) -> RiseEvent:
        if self.peak_at < self.started_at:
            raise ValueError("peak_at must not precede started_at")
        expected = self.peak_probability - self.baseline_probability
        if abs(expected - self.probability_delta) > 1e-9:
            raise ValueError("probability_delta must equal peak minus baseline")
        return self


class LeadingIndicator(StrictModel):
    feature: str = Field(min_length=1)
    direction: IndicatorDirection
    baseline_value: float
    risk_window_value: float
    change_percent: float | None = None
    signed_contribution: float | None = None
    source_reference: SourceReference


class Intervention(StrictModel):
    action_code: ActionCode
    parameters: dict[str, Any]
    estimated_downtime_minutes: int | None = Field(default=None, ge=0)
    policy_version: str = Field(min_length=1)


class ProbabilityEffect(StrictModel):
    baseline_probability: float = Field(ge=0, le=1)
    intervention_probability: float = Field(ge=0, le=1)
    estimated_probability_reduction: float = Field(ge=-1, le=1)

    @model_validator(mode="after")
    def validate_reduction(self) -> ProbabilityEffect:
        expected = self.baseline_probability - self.intervention_probability
        if abs(expected - self.estimated_probability_reduction) > 1e-9:
            raise ValueError("estimated_probability_reduction must equal baseline minus intervention")
        return self


class EconomicEffect(StrictModel):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    intervention_cost: float | None = Field(default=None, ge=0)
    baseline_expected_loss: float | None = Field(default=None, ge=0)
    intervention_expected_loss: float | None = Field(default=None, ge=0)
    estimated_net_benefit: float | None = None
    calculation_scope: Literal["synthetic_scenario_estimate"]
    price_version: str = Field(min_length=1)


class Limitation(StrictModel):
    code: LimitationCode


class WhatIfProvenance(StrictModel):
    dataset_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    simulation_policy_version: str = Field(min_length=1)
    source_type: Literal["contract_fixture", "simulation_output"]
    canonical_source_mutated: Literal[False] = False


class WhatIfResult(StrictModel):
    schema_version: Literal["what-if-result-v1.0"]
    simulation_id: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    asset_type: Literal["cnc", "compressor"]
    decision_at: datetime
    rise_event: RiseEvent
    leading_indicators: list[LeadingIndicator] = Field(min_length=1)
    intervention: Intervention
    effect: ProbabilityEffect
    economic_effect: EconomicEffect | None = None
    effect_scope: EffectScope
    limitations: list[Limitation] = Field(min_length=1)
    provenance: WhatIfProvenance

    @model_validator(mode="after")
    def validate_required_limitations(self) -> WhatIfResult:
        codes = {item.code for item in self.limitations}
        required = {
            LimitationCode.SYNTHETIC_DATA_ONLY,
            LimitationCode.NOT_CAUSAL_PROOF,
            LimitationCode.NOT_REAL_WORLD_EFFECT_GUARANTEE,
        }
        if not required.issubset(codes):
            raise ValueError("synthetic What-if results must expose all safety limitations")
        return self


class ToolReplacementPolicy(StrictModel):
    policy_version: str = Field(min_length=1)
    action_code: Literal[ActionCode.TOOL_REPLACEMENT]
    asset_type: Literal["cnc"]
    tool_wear_after: float = Field(ge=0)
    default_duration_minutes: int = Field(gt=0)
    requires_shutdown: Literal[True]
    applicable_failure_modes: list[Literal["tool_wear_failure", "overstrain_failure"]]
    cost_source_type: Literal["missing", "synthetic_assumption", "actual_transaction"]
    default_parts_cost: float | None = Field(default=None, ge=0)
    default_labor_cost: float | None = Field(default=None, ge=0)


def preventive_what_if_schema() -> dict[str, Any]:
    schema = WhatIfResult.model_json_schema(
        ref_template="#/$defs/{model}",
        mode="validation",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://ontology-dashboard.local/schemas/preventive-what-if.schema.json",
        **schema,
    }

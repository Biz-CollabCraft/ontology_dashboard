"""Contracts for the bounded manufacturing decision-support agent.

These models are intentionally separate from closed-loop mutation contracts.
They describe what the agent may observe and recommend, not what it may execute.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.operations.operational_context_contract import OperationalRequestIdentity


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionAction(StrEnum):
    MONITOR = "MONITOR"
    REQUEST_ADDITIONAL_DIAGNOSIS = "REQUEST_ADDITIONAL_DIAGNOSIS"
    REQUEST_INSPECTION = "REQUEST_INSPECTION"
    REQUEST_MAINTENANCE = "REQUEST_MAINTENANCE"
    REVIEW_PLANNED_MAINTENANCE = "REVIEW_PLANNED_MAINTENANCE"


class DecisionSessionStatus(StrEnum):
    CREATED = "created"
    ASSESSING = "assessing"
    WAITING_FOR_TOOL = "waiting_for_tool"
    READY_FOR_REVIEW = "ready_for_review"
    ABSTAINED = "abstained"
    STALE = "stale"
    FAILED = "failed"
    CLOSED = "closed"


class DecisionConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DecisionFact(FrozenModel):
    fact_type: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    source_refs: tuple[str, ...] = Field(min_length=1)
    owner_domain: str = Field(min_length=1, max_length=120)
    as_of: datetime | None = None


class DecisionConflict(FrozenModel):
    conflict_type: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    source_refs: tuple[str, ...] = Field(min_length=1)
    values: dict[str, Any] = Field(default_factory=dict)


class DecisionProposal(FrozenModel):
    schema_version: str = "manufacturing-decision-proposal-v1.0"
    recommended_action: DecisionAction | None
    alternative_actions: tuple[DecisionAction, ...] = ()
    confidence: DecisionConfidence
    reasoning_summary: str = Field(min_length=1, max_length=3000)
    confirmed_facts: tuple[DecisionFact, ...] = ()
    uncertainties: tuple[str, ...] = ()
    conflicts: tuple[DecisionConflict, ...] = ()
    additional_information_needed: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    human_approval_required: bool = True
    abstain_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_recommendation_shape(self) -> "DecisionProposal":
        if not self.human_approval_required:
            raise ValueError("decision proposals must require human approval")
        if self.recommended_action is None and not self.abstain_reason:
            raise ValueError("abstaining proposals require abstain_reason")
        if self.recommended_action is not None and self.abstain_reason:
            raise ValueError("recommended proposals must not include abstain_reason")
        if self.recommended_action in self.alternative_actions:
            raise ValueError("recommended_action must not be repeated as an alternative")
        if len(set(self.alternative_actions)) != len(self.alternative_actions):
            raise ValueError("alternative_actions must be unique")
        return self


class DecisionToolCall(FrozenModel):
    tool_call_id: str = Field(min_length=1, max_length=240)
    tool_name: str = Field(min_length=1, max_length=160)
    started_at: datetime
    completed_at: datetime | None = None
    attempt: int = Field(ge=1)
    status: str = Field(min_length=1, max_length=80)
    retryable: bool = False
    source_refs: tuple[str, ...] = ()
    error_code: str | None = Field(default=None, max_length=160)


class DecisionSession(FrozenModel):
    schema_version: str = "manufacturing-decision-session-v1.0"
    decision_session_id: str = Field(min_length=1, max_length=240)
    identity: OperationalRequestIdentity
    actor_role: str = Field(min_length=1, max_length=120)
    status: DecisionSessionStatus
    allowed_actions: tuple[DecisionAction, ...] = ()
    tool_calls: tuple[DecisionToolCall, ...] = ()
    proposal: DecisionProposal | None = None
    created_at: datetime
    updated_at: datetime
    retry_budget_remaining: int = Field(ge=0, le=20)
    mutation_attempted: bool = False

    @model_validator(mode="after")
    def validate_session_boundary(self) -> "DecisionSession":
        if self.mutation_attempted:
            raise ValueError("decision agent session must remain read-only")
        if self.proposal and self.proposal.recommended_action is not None:
            if self.proposal.recommended_action not in self.allowed_actions:
                raise ValueError("proposal action must be allowed by deterministic policy")
            if any(action not in self.allowed_actions for action in self.proposal.alternative_actions):
                raise ValueError("proposal alternatives must be allowed by deterministic policy")
        if self.status is DecisionSessionStatus.READY_FOR_REVIEW and self.proposal is None:
            raise ValueError("ready_for_review requires a proposal")
        if self.status is DecisionSessionStatus.ABSTAINED and (
            self.proposal is None or self.proposal.recommended_action is not None
        ):
            raise ValueError("abstained session requires an abstaining proposal")
        return self

"""Structured LLM planner for the bounded manufacturing decision agent.

The planner can choose which read-only tool to inspect next and rank actions
inside a deterministic allowlist. It never owns identity, authorization, action
eligibility, or mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.common.llm_contract import LLMProvider
from app.operations.decision_policy import DecisionPolicyFacts
from app.operations.decision_support_contract import DecisionAction, DecisionConfidence
from app.operations.decision_tools import DecisionToolName, DecisionToolResult
from app.operations.decision_evidence import evidence_notes


TOOL_SELECTION_SYSTEM_PROMPT = """You are a bounded manufacturing decision-support planner.
Choose at most one additional READ-ONLY tool that is necessary for the current human decision.
Use only a tool listed in available_tools. Do not request mutation, approval, work-order creation,
production schedule changes, equipment stop, procurement, or any action outside the supplied list.
Return a JSON object matching the provided schema. The runtime supplies only remaining relevant evidence lookups. Choose one of them; it stops calling you when required context is complete.
Do not invent facts. Missing information can justify one more read-only lookup or abstention.
"""

ACTION_RANKING_SYSTEM_PROMPT = """
Action meanings: REQUEST_MAINTENANCE asks a human to review maintenance need; it is
not an immediate stop, approved work order, or proof that resources are ready.
REVIEW_PLANNED_MAINTENANCE asks a human to compare timing, production and resources.
Both can be reasonable for confirmed maintenance need. MONITOR does not resolve
an outstanding measurement requirement. REQUEST_ADDITIONAL_DIAGNOSIS gathers
missing measurements; REQUEST_INSPECTION asks for physical inspection.
Prefer diagnosis when a source explicitly requires additional measurement; persistent
worsening supports inspection. Never imply available execution from reserved stock,
future replenishment, or an unsuitable window. Due pressure is not equipment urgency.
Source recommendation_blockers mean human reconciliation is required before ranking.

You are a bounded manufacturing decision-support reviewer.
Rank only actions in allowed_actions using only supplied verified tool results and policy facts.
You are advising a human; you do not execute anything. If evidence is insufficient or conflicting,
return recommended_action=null and explain why. Never create a new action or claim an unverified
fact. Return a JSON object matching the provided schema. Keep the reasoning concise and suitable for a manufacturing operator workspace.
"""


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ToolSelection(FrozenModel):
    next_tool: DecisionToolName | None
    reason: str = Field(min_length=1, max_length=600)


class ActionRanking(FrozenModel):
    recommended_action: DecisionAction | None
    alternative_actions: tuple[DecisionAction, ...]
    confidence: DecisionConfidence
    reasoning_summary: str = Field(min_length=1, max_length=2000)
    abstain_reason: str | None = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_shape(self) -> "ActionRanking":
        if self.recommended_action is None and not self.abstain_reason:
            raise ValueError("abstaining ranking requires abstain_reason")
        if self.recommended_action is not None and self.abstain_reason:
            raise ValueError("recommended ranking must not carry abstain_reason")
        if self.recommended_action in self.alternative_actions:
            raise ValueError("recommended action must not be duplicated as an alternative")
        if len(set(self.alternative_actions)) != len(self.alternative_actions):
            raise ValueError("alternative actions must be unique")
        return self


class DecisionPlannerError(RuntimeError):
    pass


class DecisionPlanner(Protocol):
    name: str

    def select_next_tool(
        self,
        *,
        policy_facts: DecisionPolicyFacts,
        allowed_actions: tuple[DecisionAction, ...],
        available_tools: tuple[DecisionToolName, ...],
        results: dict[DecisionToolName, DecisionToolResult],
    ) -> ToolSelection: ...

    def rank_actions(
        self,
        *,
        policy_facts: DecisionPolicyFacts,
        allowed_actions: tuple[DecisionAction, ...],
        results: dict[DecisionToolName, DecisionToolResult],
    ) -> ActionRanking: ...


@dataclass
class StructuredLLMDecisionPlanner:
    provider: LLMProvider
    name: str = "structured-llm-decision-planner-v1"

    def select_next_tool(
        self,
        *,
        policy_facts: DecisionPolicyFacts,
        allowed_actions: tuple[DecisionAction, ...],
        available_tools: tuple[DecisionToolName, ...],
        results: dict[DecisionToolName, DecisionToolResult],
    ) -> ToolSelection:
        if not available_tools:
            return ToolSelection(next_tool=None, reason="No remaining relevant tools")
        schema = ToolSelection.model_json_schema()
        schema["properties"]["next_tool"] = {"type": "string", "enum": [t.value for t in available_tools]}
        payload = {
            "policy_facts": policy_facts.model_dump(mode="json"),
            "allowed_actions": [action.value for action in allowed_actions],
            "available_tools": [tool.value for tool in available_tools],
            "observations": _compact_results(results),
            "verified_constraints": list(evidence_notes(results)),
        }
        try:
            raw = self.provider.generate_json(
                TOOL_SELECTION_SYSTEM_PROMPT,
                payload,
                response_schema=schema,
                response_schema_name="decision_tool_selection",
            )
            selection = ToolSelection.model_validate(raw)
        except (ValidationError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise DecisionPlannerError(f"tool_selection_failed:{type(exc).__name__}") from exc
        if selection.next_tool is not None and selection.next_tool not in available_tools:
            raise DecisionPlannerError("tool_selection_outside_allowlist")
        return selection

    def rank_actions(
        self,
        *,
        policy_facts: DecisionPolicyFacts,
        allowed_actions: tuple[DecisionAction, ...],
        results: dict[DecisionToolName, DecisionToolResult],
    ) -> ActionRanking:
        payload = {
            "policy_facts": policy_facts.model_dump(mode="json"),
            "allowed_actions": [action.value for action in allowed_actions],
            "observations": _compact_results(results),
            "verified_constraints": list(evidence_notes(results)),
        }
        try:
            raw = self.provider.generate_json(
                ACTION_RANKING_SYSTEM_PROMPT,
                payload,
                response_schema=ActionRanking.model_json_schema(),
                response_schema_name="decision_action_ranking",
            )
            ranking = ActionRanking.model_validate(raw)
        except (ValidationError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            raise DecisionPlannerError(f"action_ranking_failed:{type(exc).__name__}") from exc
        allowed = set(allowed_actions)
        if ranking.recommended_action is not None and ranking.recommended_action not in allowed:
            raise DecisionPlannerError("recommended_action_outside_policy")
        if any(action not in allowed for action in ranking.alternative_actions):
            raise DecisionPlannerError("alternative_action_outside_policy")
        return ranking


def _compact_results(results: dict[DecisionToolName, DecisionToolResult]) -> dict[str, Any]:
    return {
        name.value: {
            "status": result.status,
            "as_of": result.as_of.isoformat(),
            "data": result.data,
            "limitations": list(result.limitations),
            "recommendation_blockers": list(result.recommendation_blockers),
            "source_refs": list(result.source_refs),
        }
        for name, result in results.items()
    }

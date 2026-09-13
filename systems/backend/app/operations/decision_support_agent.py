"""LangGraph-backed bounded decision-support agent.

The graph owns dynamic read-only tool selection. Deterministic policy still owns
which actions are eligible, and the resulting proposal always requires a human
review before any closed-loop command can run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.operations.decision_policy import (
    DecisionPolicyFacts,
    DecisionPolicyGuard,
    DecisionPolicyResult,
)
from app.operations.decision_retry import DecisionRetryPolicy, RetryFailureKind
from app.operations.decision_support_contract import (
    DecisionAction,
    DecisionConfidence,
    DecisionConflict,
    DecisionFact,
    DecisionProposal,
    DecisionSession,
    DecisionSessionStatus,
    DecisionToolCall,
)
from app.operations.decision_tools import (
    DecisionToolFailure,
    DecisionToolName,
    DecisionToolResult,
    ManufacturingDecisionTools,
)
from app.operations.operational_context_contract import OperationalRequestIdentity


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionAgentRequest(FrozenModel):
    identity: OperationalRequestIdentity
    actor_role: str = Field(min_length=1, max_length=120)
    policy_facts: DecisionPolicyFacts
    retry_budget: int = Field(default=3, ge=0, le=20)
    max_tool_calls: int = Field(default=5, ge=1, le=8)


class DecisionAgentRunResult(FrozenModel):
    engine: str
    session: DecisionSession
    policy: DecisionPolicyResult
    tool_results: dict[str, DecisionToolResult]


@dataclass
class DecisionToolRuntime:
    tools: ManufacturingDecisionTools
    retry_policy: DecisionRetryPolicy = DecisionRetryPolicy()
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def execute(
        self,
        *,
        tool_name: DecisionToolName,
        identity: OperationalRequestIdentity,
        retry_budget_remaining: int,
    ) -> tuple[DecisionToolResult | None, tuple[DecisionToolCall, ...], int, RetryFailureKind | None]:
        calls: list[DecisionToolCall] = []
        attempt = 1
        budget = retry_budget_remaining
        while True:
            started = self.now()
            call_id = f"{tool_name.value}:{uuid4()}"
            try:
                result = self.tools.call(
                    tool_name=tool_name,
                    identity=identity,
                    retrieved_at=started,
                )
                calls.append(
                    DecisionToolCall(
                        tool_call_id=call_id,
                        tool_name=tool_name.value,
                        started_at=started,
                        completed_at=self.now(),
                        attempt=attempt,
                        status=result.status,
                        retryable=False,
                        source_refs=result.source_refs,
                    )
                )
                return result, tuple(calls), budget, None
            except DecisionToolFailure as exc:
                directive = self.retry_policy.directive(exc.kind)
                retry = self.retry_policy.may_retry(
                    exc.kind,
                    attempt=attempt,
                    retry_budget_remaining=budget,
                )
                calls.append(
                    DecisionToolCall(
                        tool_call_id=call_id,
                        tool_name=tool_name.value,
                        started_at=started,
                        completed_at=self.now(),
                        attempt=attempt,
                        status="failed",
                        retryable=retry,
                        error_code=exc.kind.value,
                    )
                )
                if not retry:
                    return None, tuple(calls), budget, exc.kind
                budget -= directive.consume_budget
                self.sleep(self.retry_policy.delay_seconds(exc.kind, attempt, seed=attempt))
                attempt += 1


@dataclass
class ManufacturingDecisionAgent:
    tools: ManufacturingDecisionTools
    policy_guard: DecisionPolicyGuard = DecisionPolicyGuard()
    retry_policy: DecisionRetryPolicy = DecisionRetryPolicy()
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    def run(self, request: DecisionAgentRequest) -> DecisionAgentRunResult:
        policy = self.policy_guard.evaluate(request.policy_facts)
        created_at = self.now()
        if policy.recommendation_blocked:
            proposal = self._abstain("deterministic policy blocked recommendation")
            return DecisionAgentRunResult(
                engine="policy-only",
                policy=policy,
                tool_results={},
                session=DecisionSession(
                    decision_session_id=f"DS-{uuid4()}",
                    identity=request.identity,
                    actor_role=request.actor_role,
                    status=DecisionSessionStatus.ABSTAINED,
                    allowed_actions=policy.allowed_actions,
                    proposal=proposal,
                    created_at=created_at,
                    updated_at=self.now(),
                    retry_budget_remaining=request.retry_budget,
                ),
            )

        runtime = DecisionToolRuntime(
            tools=self.tools,
            retry_policy=self.retry_policy,
            sleep=self.sleep,
            now=self.now,
        )
        try:
            from langgraph.graph import END, StateGraph
        except Exception as exc:  # pragma: no cover - runtime dependency guard
            proposal = self._abstain(f"langgraph unavailable: {type(exc).__name__}")
            return DecisionAgentRunResult(
                engine="unavailable",
                policy=policy,
                tool_results={},
                session=DecisionSession(
                    decision_session_id=f"DS-{uuid4()}",
                    identity=request.identity,
                    actor_role=request.actor_role,
                    status=DecisionSessionStatus.ABSTAINED,
                    allowed_actions=policy.allowed_actions,
                    proposal=proposal,
                    created_at=created_at,
                    updated_at=self.now(),
                    retry_budget_remaining=request.retry_budget,
                ),
            )

        graph = StateGraph(dict)

        def assess(state: dict[str, Any]) -> dict[str, Any]:
            state["next_tool"] = self._select_next_tool(request, state["tool_results"])
            if state["next_tool"] is None:
                state["proposal"] = self._build_proposal(
                    request=request,
                    allowed=policy.allowed_actions,
                    results=state["tool_results"],
                    failures=state["failures"],
                )
            return state

        def execute_tool(state: dict[str, Any]) -> dict[str, Any]:
            tool_name = state["next_tool"]
            if tool_name in state["tool_results"]:
                state["failures"].append((tool_name, RetryFailureKind.REPEATED_FAILURE))
                state["next_tool"] = None
                return state
            if len(state["tool_calls"]) >= request.max_tool_calls:
                state["failures"].append((tool_name, RetryFailureKind.REPEATED_FAILURE))
                state["next_tool"] = None
                return state
            result, calls, budget, failure = runtime.execute(
                tool_name=tool_name,
                identity=request.identity,
                retry_budget_remaining=state["retry_budget"],
            )
            state["tool_calls"].extend(calls)
            state["retry_budget"] = budget
            if result is not None:
                state["tool_results"][tool_name] = result
            if failure is not None:
                state["failures"].append((tool_name, failure))
                if failure is RetryFailureKind.STALE_SNAPSHOT:
                    state["stale"] = True
            state["next_tool"] = None
            return state

        def route_after_assess(state: dict[str, Any]):
            return "tool" if state.get("next_tool") is not None else "final"

        def route_after_tool(state: dict[str, Any]):
            return "final" if state.get("stale") else "assess"

        def finalize(state: dict[str, Any]) -> dict[str, Any]:
            if state.get("stale"):
                state["proposal"] = self._abstain("snapshot changed; start a new DecisionSession")
                state["session_status"] = DecisionSessionStatus.STALE
            elif state.get("proposal") is None:
                state["proposal"] = self._build_proposal(
                    request=request,
                    allowed=policy.allowed_actions,
                    results=state["tool_results"],
                    failures=state["failures"],
                )
            if state.get("session_status") is None:
                state["session_status"] = (
                    DecisionSessionStatus.ABSTAINED
                    if state["proposal"].recommended_action is None
                    else DecisionSessionStatus.READY_FOR_REVIEW
                )
            return state

        graph.add_node("assess", assess)
        graph.add_node("tool", execute_tool)
        graph.add_node("final", finalize)
        graph.set_entry_point("assess")
        graph.add_conditional_edges("assess", route_after_assess, {"tool": "tool", "final": "final"})
        graph.add_conditional_edges("tool", route_after_tool, {"assess": "assess", "final": "final"})
        graph.add_edge("final", END)
        state = graph.compile().invoke(
            {
                "tool_results": {},
                "tool_calls": [],
                "failures": [],
                "retry_budget": request.retry_budget,
                "stale": False,
                "proposal": None,
                "session_status": None,
            }
        )
        proposal: DecisionProposal = state["proposal"]
        # Final policy check is enforced again by DecisionSession validation.
        session = DecisionSession(
            decision_session_id=f"DS-{uuid4()}",
            identity=request.identity,
            actor_role=request.actor_role,
            status=state["session_status"],
            allowed_actions=policy.allowed_actions,
            tool_calls=tuple(state["tool_calls"]),
            proposal=proposal,
            created_at=created_at,
            updated_at=self.now(),
            retry_budget_remaining=state["retry_budget"],
        )
        return DecisionAgentRunResult(
            engine="langgraph",
            session=session,
            policy=policy,
            tool_results={name.value: result for name, result in state["tool_results"].items()},
        )

    def _select_next_tool(
        self,
        request: DecisionAgentRequest,
        results: dict[DecisionToolName, DecisionToolResult],
    ) -> DecisionToolName | None:
        facts = request.policy_facts
        if facts.maintenance_recommended:
            for name in (
                DecisionToolName.GET_MAINTENANCE_CONTEXT,
                DecisionToolName.GET_PRODUCTION_CONTEXT,
                DecisionToolName.GET_RESOURCE_READINESS,
            ):
                if name not in results:
                    return name
            return None
        if not facts.inspection_result_available:
            if DecisionToolName.GET_ASSET_CONDITION not in results:
                return DecisionToolName.GET_ASSET_CONDITION
            if DecisionToolName.GET_INSPECTION_CONTEXT not in results:
                return DecisionToolName.GET_INSPECTION_CONTEXT
            return None
        if DecisionToolName.GET_ASSET_CONDITION not in results:
            return DecisionToolName.GET_ASSET_CONDITION
        return None

    def _build_proposal(
        self,
        *,
        request: DecisionAgentRequest,
        allowed: tuple[DecisionAction, ...],
        results: dict[DecisionToolName, DecisionToolResult],
        failures: list[tuple[DecisionToolName, RetryFailureKind]],
    ) -> DecisionProposal:
        if failures:
            return self._abstain(
                "required decision context could not be verified: "
                + ", ".join(f"{tool.value}:{kind.value}" for tool, kind in failures)
            )
        facts = request.policy_facts
        confirmed = self._confirmed_facts(results)
        evidence_refs = tuple(dict.fromkeys(ref for result in results.values() for ref in result.source_refs))
        uncertainties = tuple(
            limitation
            for result in results.values()
            for limitation in result.limitations
        )
        if facts.maintenance_recommended:
            preferred = DecisionAction.REVIEW_PLANNED_MAINTENANCE
            fallback = DecisionAction.REQUEST_MAINTENANCE
            recommended = preferred if preferred in allowed else fallback if fallback in allowed else None
            alternatives = (fallback,) if recommended is preferred and fallback in allowed else ()
            if recommended is None:
                return self._abstain("maintenance action is not allowed by current policy")
            conflicts = self._planning_conflicts(results)
            return DecisionProposal(
                recommended_action=recommended,
                alternative_actions=alternatives,
                confidence=DecisionConfidence.MEDIUM if uncertainties or conflicts else DecisionConfidence.HIGH,
                reasoning_summary=(
                    "정비 필요성이 확인되어 생산 영향과 정비 준비 상태를 함께 비교했습니다. "
                    "계획 정비 조건을 우선 검토하고, 즉시 정비 요청은 대안으로 남깁니다."
                ),
                confirmed_facts=confirmed,
                uncertainties=uncertainties,
                conflicts=conflicts,
                evidence_refs=evidence_refs,
            )
        risk = (facts.risk_status or "").lower()
        if not facts.inspection_result_available and risk in {"warning", "critical"}:
            recommended = DecisionAction.REQUEST_INSPECTION if DecisionAction.REQUEST_INSPECTION in allowed else None
            alternative = DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS
            if recommended is None:
                return self._abstain("inspection is not allowed by current policy")
            return DecisionProposal(
                recommended_action=recommended,
                alternative_actions=(alternative,) if alternative in allowed else (),
                confidence=DecisionConfidence.MEDIUM,
                reasoning_summary="이상 신호와 점검 기준을 확인했으며 현장 점검 결과가 없어 점검 요청을 우선 제안합니다.",
                confirmed_facts=confirmed,
                uncertainties=uncertainties,
                evidence_refs=evidence_refs,
            )
        recommended = DecisionAction.MONITOR if DecisionAction.MONITOR in allowed else None
        if recommended is None:
            return self._abstain("monitoring is not allowed by current policy")
        return DecisionProposal(
            recommended_action=recommended,
            alternative_actions=(),
            confidence=DecisionConfidence.MEDIUM,
            reasoning_summary="현재 근거에서는 즉시 점검·정비로 전환할 조건이 확인되지 않아 계속 모니터링을 제안합니다.",
            confirmed_facts=confirmed,
            uncertainties=uncertainties,
            evidence_refs=evidence_refs,
        )

    def _confirmed_facts(
        self, results: dict[DecisionToolName, DecisionToolResult]
    ) -> tuple[DecisionFact, ...]:
        facts: list[DecisionFact] = []
        for name, result in results.items():
            if result.status != "available" or not result.source_refs:
                continue
            facts.append(
                DecisionFact(
                    fact_type=name.value,
                    summary=f"{name.value} 조회 결과가 현재 판단 시점에 사용 가능합니다.",
                    source_refs=result.source_refs,
                    owner_domain=name.value,
                    as_of=result.as_of,
                )
            )
        return tuple(facts)

    def _planning_conflicts(
        self, results: dict[DecisionToolName, DecisionToolResult]
    ) -> tuple[DecisionConflict, ...]:
        production = results.get(DecisionToolName.GET_PRODUCTION_CONTEXT)
        readiness = results.get(DecisionToolName.GET_RESOURCE_READINESS)
        if production is None or readiness is None:
            return ()
        impact = production.data.get("event_impact") or {}
        planning_minutes = impact.get("estimated_downtime_minutes")
        windows = readiness.data.get("maintenance_windows") or []
        maintenance_minutes = windows[0].get("expected_duration_minutes") if windows else None
        if (
            isinstance(planning_minutes, (int, float))
            and isinstance(maintenance_minutes, (int, float))
            and planning_minutes != maintenance_minutes
        ):
            refs = tuple(dict.fromkeys((*production.source_refs, *readiness.source_refs)))
            return (
                DecisionConflict(
                    conflict_type="downtime_assumption_mismatch",
                    summary="생산 영향 계산의 정지시간과 정비 작업 예상시간이 다릅니다.",
                    source_refs=refs,
                    values={
                        "planning_minutes": planning_minutes,
                        "maintenance_minutes": maintenance_minutes,
                    },
                ),
            )
        return ()

    def _abstain(self, reason: str) -> DecisionProposal:
        return DecisionProposal(
            recommended_action=None,
            alternative_actions=(),
            confidence=DecisionConfidence.LOW,
            reasoning_summary="현재 근거만으로 다음 행동을 안전하게 추천하지 않습니다.",
            abstain_reason=reason,
            human_approval_required=True,
        )

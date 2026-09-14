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
from app.operations.decision_llm_planner import DecisionPlanner, DecisionPlannerError
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
from app.operations.decision_evidence import remaining_tools, recommendation_blockers, measurement_required, evidence_notes
from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter, TextInterpretationError, collect_excerpts


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
    planner: DecisionPlanner | None = None
    text_interpreter: StructuredTextEvidenceInterpreter | None = None
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
            text_proposal, reason = self._text_interpretation_proposal(
                state["text_interpretations"], state["text_errors"], state["tool_results"], policy.allowed_actions,
            )
            if text_proposal is not None:
                state["proposal"] = text_proposal
                state["text_gate_reason"] = reason
                state["next_tool"] = None
                return state
            if state["failures"] or len(state["tool_calls"]) >= request.max_tool_calls and remaining_tools(request.policy_facts, state["tool_results"]):
                state["proposal"] = self._abstain("required context unavailable within tool budget")
                state["next_tool"] = None
                return state
            state["next_tool"] = self._planned_next_tool(
                request=request,
                allowed=policy.allowed_actions,
                results=state["tool_results"],
                planner_errors=state["planner_errors"],
            )
            if state["next_tool"] is None:
                state["proposal"] = self._planned_proposal(
                    request=request,
                    allowed=policy.allowed_actions,
                    results=state["tool_results"],
                    failures=state["failures"],
                    planner_errors=state["planner_errors"],
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
            effective_budget = min(state["retry_budget"], request.max_tool_calls - len(state["tool_calls"]) - 1)
            result, calls, budget, failure = runtime.execute(
                tool_name=tool_name,
                identity=request.identity,
                retry_budget_remaining=effective_budget,
            )
            state["tool_calls"].extend(calls)
            state["retry_budget"] -= effective_budget - budget
            if result is not None:
                state["tool_results"][tool_name] = result
                if self.text_interpreter is not None and self._evidence_gate_reason(state["tool_results"]) is None:
                    try:
                        excerpts = collect_excerpts(state["tool_results"])
                        state["text_interpretations"] = self.text_interpreter.interpret(excerpts, cache=state["text_cache"])
                    except TextInterpretationError as exc:
                        state["text_errors"].append(str(exc))
            if failure is not None:
                state["failures"].append((tool_name, failure))
                if failure is RetryFailureKind.STALE_SNAPSHOT:
                    state["stale"] = True
            state["next_tool"] = None
            return state

        def route_after_assess(state: dict[str, Any]):
            return "tool" if state.get("next_tool") is not None else "final"

        def route_after_tool(state: dict[str, Any]):
            return "final" if state.get("stale") or state["failures"] else "assess"

        def finalize(state: dict[str, Any]) -> dict[str, Any]:
            if state.get("stale"):
                state["proposal"] = self._abstain("snapshot changed; start a new DecisionSession")
                state["session_status"] = DecisionSessionStatus.STALE
            elif state.get("proposal") is None:
                state["proposal"] = self._planned_proposal(
                    request=request,
                    allowed=policy.allowed_actions,
                    results=state["tool_results"],
                    failures=state["failures"],
                    planner_errors=state["planner_errors"],
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
                "planner_errors": [],
                "text_interpretations": (),
                "text_cache": {},
                "text_errors": [],
                "text_gate_reason": None,
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
            planner_errors=tuple(state["planner_errors"]),
            recommendation_gate_reason=self._evidence_gate_reason(state["tool_results"]) or state["text_gate_reason"],
            text_interpretations=state["text_interpretations"],
            text_interpretation_errors=tuple(state["text_errors"]),
        )
        return DecisionAgentRunResult(
            engine=("langgraph+llm" if self.planner is not None else "langgraph") + ("+text-llm" if self.text_interpreter is not None else ""),
            session=session,
            policy=policy,
            tool_results={name.value: result for name, result in state["tool_results"].items()},
        )

    def _text_interpretation_proposal(self, interpretations, errors, results, allowed):
        if errors:
            reason = "text_interpretation_unverified"
            return self._evidence_abstain(reason, results), reason
        positives = [item for item in interpretations if item.unresolved_conflict or item.measurement_required or item.uncertain]
        if not positives:
            return None, None
        refs = tuple(dict.fromkeys(ref for item in positives for ref in item.source_refs))
        notes = tuple(f"문구 해석(사람 확인 필요): {item.quote}" for item in positives)
        if any(item.unresolved_conflict or item.uncertain for item in positives):
            reason = "text_interpretation_requires_human_review"
            proposal = self._evidence_abstain(reason, results).model_copy(update={
                "uncertainties": (*evidence_notes(results), *notes), "evidence_refs": refs,
            })
            return proposal, reason
        if DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS not in allowed:
            reason = "text_measurement_action_not_allowed"
            return self._evidence_abstain(reason, results), reason
        return DecisionProposal(
            recommended_action=DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS,
            alternative_actions=(), confidence=DecisionConfidence.LOW,
            reasoning_summary="원문이 추가 측정을 요구하는 것으로 해석되어 진단 보강을 제안합니다. 담당자의 원문 확인이 필요합니다.",
            confirmed_facts=(), uncertainties=(*evidence_notes(results), *notes),
            evidence_refs=refs, human_approval_required=True,
        ), "text_interpretation_measurement_required"

    def _planned_next_tool(
        self,
        *,
        request: DecisionAgentRequest,
        allowed: tuple[DecisionAction, ...],
        results: dict[DecisionToolName, DecisionToolResult],
        planner_errors: list[str],
    ) -> DecisionToolName | None:
        available = remaining_tools(request.policy_facts, results)
        if not available:
            return None
        if self.planner is None:
            return available[0]
        try:
            selection = self.planner.select_next_tool(
                policy_facts=request.policy_facts,
                allowed_actions=allowed,
                available_tools=available,
                results=results,
            )
            if selection.next_tool is None:
                planner_errors.append("premature_stop_missing_context")
                return available[0]
            if selection.next_tool not in available:
                raise DecisionPlannerError("tool_selection_outside_allowlist")
            return selection.next_tool
        except DecisionPlannerError as exc:
            planner_errors.append(str(exc))
            return self._select_next_tool(request, results)

    def _planned_proposal(
        self,
        *,
        request: DecisionAgentRequest,
        allowed: tuple[DecisionAction, ...],
        results: dict[DecisionToolName, DecisionToolResult],
        failures: list[tuple[DecisionToolName, RetryFailureKind]],
        planner_errors: list[str],
    ) -> DecisionProposal:
        gate = self._evidence_gate_reason(results)
        if gate:
            return self._evidence_abstain(gate, results)
        if failures or self.planner is None:
            return self._build_proposal(
                request=request,
                allowed=allowed,
                results=results,
                failures=failures,
            )
        try:
            ranking = self.planner.rank_actions(
                policy_facts=request.policy_facts,
                allowed_actions=allowed,
                results=results,
            )
        except DecisionPlannerError as exc:
            planner_errors.append(str(exc))
            return self._build_proposal(
                request=request,
                allowed=allowed,
                results=results,
                failures=failures,
            )
        if ranking.recommended_action is None:
            return DecisionProposal(
                recommended_action=None,
                alternative_actions=(),
                confidence=ranking.confidence,
                reasoning_summary=ranking.reasoning_summary,
                confirmed_facts=self._confirmed_facts(results),
                uncertainties=evidence_notes(results),
                conflicts=self._planning_conflicts(results),
                evidence_refs=tuple(dict.fromkeys(
                    ref for result in results.values() for ref in result.source_refs
                )),
                abstain_reason=ranking.abstain_reason,
                human_approval_required=True,
            )
        return DecisionProposal(
            recommended_action=ranking.recommended_action,
            alternative_actions=ranking.alternative_actions,
            confidence=ranking.confidence,
            reasoning_summary=ranking.reasoning_summary,
            confirmed_facts=self._confirmed_facts(results),
            uncertainties=evidence_notes(results),
            conflicts=self._planning_conflicts(results),
            evidence_refs=tuple(dict.fromkeys(
                ref for result in results.values() for ref in result.source_refs
            )),
            human_approval_required=True,
        )

    def _select_next_tool(
        self,
        request: DecisionAgentRequest,
        results: dict[DecisionToolName, DecisionToolResult],
    ) -> DecisionToolName | None:
        available = remaining_tools(request.policy_facts, results)
        return available[0] if available else None

    def _evidence_gate_reason(self, results):
        blockers = recommendation_blockers(results)
        if blockers:
            return "source_requires_human_review: " + "; ".join(blockers)
        unavailable = [name.value for name, result in results.items() if result.status != "available"]
        if unavailable:
            return "unverified_context: " + ", ".join(unavailable)
        return None

    def _evidence_abstain(self, reason, results):
        return self._abstain(reason).model_copy(update={
            "evidence_refs": tuple(dict.fromkeys(ref for r in results.values() for ref in r.source_refs)),
            "uncertainties": (*evidence_notes(results), *recommendation_blockers(results)),
        })

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
        uncertainties = evidence_notes(results)
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
                    "일정·자원 제약을 검토하고, 담당자에게 정비 필요성 검토를 요청하는 것을 대안으로 남깁니다. 어느 제안도 작업 실행이나 승인 완료를 의미하지 않습니다."
                ),
                confirmed_facts=confirmed,
                uncertainties=uncertainties,
                conflicts=conflicts,
                evidence_refs=evidence_refs,
            )
        if measurement_required(results):
            if DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS not in allowed:
                return self._abstain("additional diagnosis is not allowed by policy")
            return DecisionProposal(
                recommended_action=DecisionAction.REQUEST_ADDITIONAL_DIAGNOSIS,
                alternative_actions=(), confidence=DecisionConfidence.MEDIUM,
                reasoning_summary="근거 제공자가 추가 측정 필요성을 명시하여 진단 보강을 제안합니다.",
                confirmed_facts=confirmed, uncertainties=uncertainties, evidence_refs=evidence_refs,
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
                reasoning_summary="위험 상태가 경고 또는 심각으로 확인됐고, 제공된 근거에 현장 점검 결과가 없어 점검 요청을 우선 제안합니다.",
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
                    summary={
                        DecisionToolName.GET_ASSET_CONDITION: "설비 상태 조회 결과를 확인했습니다.",
                        DecisionToolName.GET_INSPECTION_CONTEXT: "선택한 사건의 점검 기록 조회 결과를 확인했습니다.",
                        DecisionToolName.GET_MAINTENANCE_CONTEXT: "선택한 사건의 정비 기록 조회 결과를 확인했습니다.",
                        DecisionToolName.GET_PRODUCTION_CONTEXT: "생산 영향 조회 결과를 확인했습니다.",
                        DecisionToolName.GET_RESOURCE_READINESS: "정비 준비 상태 조회 결과를 확인했습니다.",
                    }[name],
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

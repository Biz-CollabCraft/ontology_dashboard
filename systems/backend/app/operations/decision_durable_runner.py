"""Bounded parallel reads with application-owned durable LangGraph checkpoints.

An in-flight read may run again after a crash. Its reserved attempt still counts.
No checkpoint authorizes a manufacturing mutation.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
from threading import Event, Thread
from uuid import uuid4

from app.operations.decision_run_store import DecisionRunStore, DecisionRunLeaseLost
from app.operations.decision_support_agent import DecisionAgentRequest, DecisionAgentRunResult, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionSession, DecisionSessionStatus, DecisionToolCall, DecisionTextInterpretation
from app.operations.decision_tools import DecisionToolName, DecisionToolResult, DecisionToolFailure
from app.operations.decision_retry import RetryFailureKind
from app.operations.decision_evidence import relevant_tools
from app.operations.decision_text_interpreter import collect_excerpts, TextInterpretationError, TEXT_INTERPRETATION_PROMPT

WORKFLOW_VERSION = "parallel-durable-decision-v1"


def configuration_binding(agent, request):
    components = []
    for component in (agent.planner, agent.text_interpreter):
        provider = getattr(component, "provider", None)
        components.append({"type": type(component).__qualname__, "name": getattr(component, "name", None),
            "provider": type(provider).__qualname__,
            "settings": {key: getattr(provider, key, None) for key in
                         ("model", "base_url", "reasoning_effort", "max_completion_tokens")}})
    payload = {"workflow": WORKFLOW_VERSION, "context_fingerprint": agent.context_fingerprint, "request": request.model_dump(mode="json"),
        "policy": agent.policy_guard.policy_version, "retry": agent.retry_policy.policy_version,
        "prompt": sha256(TEXT_INTERPRETATION_PROMPT.encode()).hexdigest(), "components": components}
    return sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class DurableDecisionRunner:
    def __init__(self, agent: ManufacturingDecisionAgent, store: DecisionRunStore, *, max_workers=3):
        if not 1 <= max_workers <= 3:
            raise ValueError("decision parallelism must be between 1 and 3")
        self.agent, self.store, self.max_workers = agent, store, max_workers

    @staticmethod
    def initial_state(request: DecisionAgentRequest, *, evidence_binding: str = "") -> dict:
        return {
            "request": request.model_dump(mode="json"),
            "created_at": request.identity.decision_as_of.isoformat(),
            "phase": "gather",
            "results": {},
            "calls": [],
            "budget": request.retry_budget,
            "interpretations": [],
            "text_errors": [],
            "planner_errors": [],
            "result": None,
            "evidence_binding": evidence_binding,
        }

    def run(self, request: DecisionAgentRequest, session_id: str, *, evidence_binding: str = ""):
        from langgraph.graph import END, StateGraph
        agent, store = self.agent, self.store
        policy = agent.policy_guard.evaluate(request.policy_facts)
        initial = self.initial_state(request, evidence_binding=evidence_binding)
        initial["created_at"] = agent.now().isoformat()
        state, token = store.claim(session_id, request.identity, sha256((configuration_binding(agent, request) + evidence_binding).encode()).hexdigest(), initial)
        if token is None:
            return DecisionAgentRunResult.model_validate(state["result"])
        stopped, lost = Event(), Event()

        def save():
            if lost.is_set():
                raise DecisionRunLeaseLost("decision_run_lease_lost")
            store.save(session_id, request.identity, token, state)

        def heartbeat():
            while not stopped.wait(min(5, store.lease_seconds / 3)):
                try:
                    store.heartbeat(session_id, request.identity, token)
                except Exception:
                    lost.set()
                    return

        keeper = Thread(target=heartbeat, daemon=True)
        keeper.start()
        required = relevant_tools(request.policy_facts) if not policy.recommendation_blocked else ()

        def gather(_):
            if state["phase"] != "gather":
                return {}
            # A reservation without a persisted result has unknown outcome after a crash.
            for call in state["calls"]:
                if call["status"] == "running":
                    call.update(status="failed", error_code=RetryFailureKind.NETWORK.value,
                                completed_at=agent.now().isoformat(), retryable=True)
            save()
            while True:
                batch = []
                for tool in required:
                    if tool.value in state["results"]:
                        continue
                    prior = [c for c in state["calls"] if c["tool_name"] == tool.value]
                    if len(state["calls"]) >= request.max_tool_calls:
                        break
                    if prior:
                        kind = RetryFailureKind(prior[-1]["error_code"])
                        if not agent.retry_policy.may_retry(kind, attempt=len(prior), retry_budget_remaining=state["budget"]):
                            continue
                        state["budget"] -= agent.retry_policy.directive(kind).consume_budget
                        delay = agent.retry_policy.delay_seconds(kind, len(prior), seed=len(prior))
                    else:
                        delay = 0
                    call = DecisionToolCall(tool_call_id=f"{tool.value}:{uuid4()}", tool_name=tool.value,
                        started_at=agent.now(), attempt=len(prior)+1, status="running").model_dump(mode="json")
                    state["calls"].append(call)
                    batch.append((tool, call, delay))
                if not batch:
                    break
                # Reserve every attempt and retry debit before any external read begins.
                save()

                def execute(tool, delay):
                    if delay:
                        agent.sleep(delay)
                    if lost.is_set():
                        raise DecisionRunLeaseLost("decision_run_lease_lost")
                    return agent.tools.call(tool_name=tool, identity=request.identity, retrieved_at=agent.now())

                with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                    pending = {pool.submit(execute, tool, delay): (tool, call) for tool, call, delay in batch}
                    for future in as_completed(pending):
                        tool, call = pending[future]
                        try:
                            result = future.result()
                        except DecisionRunLeaseLost:
                            raise
                        except Exception as exc:
                            kind = exc.kind if isinstance(exc, DecisionToolFailure) else RetryFailureKind.NON_RETRYABLE
                            call.update(status="failed", error_code=kind.value,
                                retryable=agent.retry_policy.may_retry(kind, attempt=call["attempt"], retry_budget_remaining=state["budget"]))
                        else:
                            state["results"][tool.value] = result.model_dump(mode="json")
                            call.update(status=result.status, source_refs=list(result.source_refs), retryable=False)
                        call["completed_at"] = agent.now().isoformat()
                        save()
            state["phase"] = "interpret"
            save()
            return {}

        def results():
            # Stable policy order independent of which parallel response arrived first.
            return {tool: DecisionToolResult.model_validate(state["results"][tool.value])
                    for tool in required if tool.value in state["results"]}

        def interpret(_):
            if state["phase"] != "interpret":
                return {}
            complete = len(results()) == len(required)
            if complete and not policy.recommendation_blocked and agent._evidence_gate_reason(results()) is None and agent.text_interpreter is not None:
                try:
                    items = agent.text_interpreter.interpret(collect_excerpts(results()), cache={})
                    state["interpretations"] = [item.model_dump(mode="json") for item in items]
                except TextInterpretationError as exc:
                    state["text_errors"].append(str(exc))
            state["phase"] = "final"
            save()
            return {}

        def finalize(_):
            if state["result"] is not None:
                return {}
            values = results()
            interpretations = tuple(DecisionTextInterpretation.model_validate(i) for i in state["interpretations"])
            stale = any(c.get("error_code") == RetryFailureKind.STALE_SNAPSHOT.value for c in state["calls"])
            reason = agent._evidence_gate_reason(values)
            if policy.recommendation_blocked:
                proposal = agent._abstain("deterministic policy blocked recommendation")
            elif stale:
                proposal = agent._abstain("snapshot changed; start a new DecisionSession")
            elif len(values) != len(required):
                reason = "required_context_incomplete"
                proposal = agent._evidence_abstain(reason, values)
            elif reason:
                proposal = agent._evidence_abstain(reason, values)
            else:
                proposal, reason = agent._text_interpretation_proposal(interpretations, state["text_errors"], values, policy.allowed_actions)
                if proposal is None:
                    proposal = agent._planned_proposal(request=request, allowed=policy.allowed_actions,
                        results=values, failures=[], planner_errors=state["planner_errors"])
            status = DecisionSessionStatus.STALE if stale else DecisionSessionStatus.ABSTAINED if proposal.recommended_action is None else DecisionSessionStatus.READY_FOR_REVIEW
            session = DecisionSession(decision_session_id=session_id, identity=request.identity, actor_role=request.actor_role,
                status=status, allowed_actions=policy.allowed_actions, proposal=proposal,
                created_at=state["created_at"], updated_at=agent.now(), retry_budget_remaining=state["budget"],
                tool_calls=tuple(DecisionToolCall.model_validate(c) for c in state["calls"]),
                text_interpretations=interpretations, text_interpretation_errors=tuple(state["text_errors"]),
                planner_errors=tuple(state["planner_errors"]), recommendation_gate_reason=reason)
            result = DecisionAgentRunResult(engine="langgraph+durable+parallel" + ("+llm-ranking" if agent.planner else "") + ("+text-llm" if agent.text_interpreter else ""),
                session=session, policy=policy, tool_results={k.value: v for k,v in values.items()})
            state["result"] = result.model_dump(mode="json")
            state["phase"] = "completed"
            save()
            return {}

        try:
            graph = StateGraph(dict)
            for name, handler in (("gather", gather), ("interpret", interpret), ("final", finalize)):
                graph.add_node(name, handler)
            graph.set_entry_point("gather")
            graph.add_edge("gather", "interpret")
            graph.add_edge("interpret", "final")
            graph.add_edge("final", END)
            graph.compile().invoke({})
            return DecisionAgentRunResult.model_validate(state["result"])
        finally:
            stopped.set()
            keeper.join(timeout=2)
            store.release(session_id, request.identity, token)

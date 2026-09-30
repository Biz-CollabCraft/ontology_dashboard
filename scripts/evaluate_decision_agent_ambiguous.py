#!/usr/bin/env python3
"""Frozen ambiguous tool-fixture benchmark. No domain mutations or gold in prompts."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import time

from evaluate_decision_agent_planner import IDENTITY, NOW, Port, packet, RecordingProvider, usage_total
from app.infra.llm.provider import OpenAICompatibleProvider
from app.operations.decision_llm_planner import StructuredLLMDecisionPlanner, DecisionPlannerError
from app.operations.decision_text_interpreter import StructuredTextEvidenceInterpreter
from app.operations.decision_policy import DecisionPolicyFacts, DecisionPolicyGuard
from app.operations.decision_support_agent import DecisionAgentRequest, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionAction as A
from app.operations.decision_tools import DecisionToolName as T, ManufacturingDecisionTools

CONDITION = (T.GET_ASSET_CONDITION, T.GET_INSPECTION_CONTEXT)
PLANNING = (T.GET_MAINTENANCE_CONTEXT, T.GET_PRODUCTION_CONTEXT, T.GET_RESOURCE_READINESS)
WARNING = DecisionPolicyFacts(risk_status="warning", inspection_result_available=False)
MAINTENANCE = DecisionPolicyFacts(risk_status="warning", inspection_result_available=True,
    maintenance_recommended=True, production_impact_known=True,
    maintenance_window_known=True, resource_readiness_known=True)

@dataclass(frozen=True)
class Case:
    id: str
    group: str
    facts: DecisionPolicyFacts
    required: tuple[T, ...]
    optional: tuple[T, ...]
    actions: tuple[A | None, ...]
    rationale: str
    packet_data: dict
    production: dict
    readiness: dict
    limitations: tuple[str, ...] = ()
    preferred_actions: tuple[A | None, ...] = ()


def make_case(id, *, maintenance=False, trend="stable", persistence="transient",
              measurement=None, pressure="low", slack=480, reservation="available",
              suitability="suitable", limitations=(), actions=(), rationale=""):
    data = packet()
    data["condition_decision_signals"] = {"trend_severity": trend, "persistence": persistence}
    data["inspection_decision_signals"] = {"completeness": "complete" if maintenance else "pending",
                                            "additional_measurement_required": measurement}
    # Keep source packet and caller policy facts consistent.
    if maintenance:
        data["maintenance_history_summary"]["inspection_results"] = [
            {"inspection_id": "INSP-1", "outcome": "maintenance_recommended"}]
    data["limitations"] = list(limitations)
    production = {"due_pressure": pressure, "schedule_slack_minutes": slack,
        "event_impact": {"estimated_downtime_minutes": 120, "estimated_lost_units": 25},
        "production_orders": [{"order_id": "PO-1"}]}
    available = 1 if reservation == "available" else 0
    reserved = 1 if reservation == "fully_reserved" else 0
    readiness = {
        "maintenance_windows": [{"window_id": "MW-1", "expected_duration_minutes": 120,
            "suitability": suitability, "active_work_order_conflict": False,
            "conflict_reason": "No production release within the candidate window" if suitability == "unsuitable" else None}],
        "concurrent_work_checks": [],
        "part_requirements": [{"part_requirement_id": "PR-1", "part_id": "P-1", "required_quantity": 1}],
        "inventory_snapshots": [{"part_id": "P-1", "on_hand_quantity": available + reserved,
            "reserved_quantity": reserved, "available_quantity": available,
            "reservation_state": reservation,
            "expected_replenishment_at": "2026-09-14T08:00:00+00:00" if reservation == "unavailable" else None}],
        "technician_readiness": [{"technician_id": "T-1", "available": True}],
        "blocking_reasons": ["Reservation ownership for this maintenance is unverified"] if reserved else [],
    }
    return Case(id, "maintenance" if maintenance else "warning", MAINTENANCE if maintenance else WARNING,
        PLANNING if maintenance else CONDITION, (T.GET_ASSET_CONDITION, T.GET_INSPECTION_CONTEXT) if maintenance else (),
        actions, rationale, data, production, readiness, tuple(limitations))

CASES = (
    make_case("A1_PERSISTENT_RAPID", trend="rapidly_worsening", persistence="persistent", measurement=False,
        actions=(A.REQUEST_INSPECTION,), rationale="Persistent rapid deterioration with no inspection supports a human inspection request."),
    make_case("A2_TRANSIENT_MEASUREMENT", measurement=True,
        actions=(A.REQUEST_ADDITIONAL_DIAGNOSIS,), rationale="Stable transient signal explicitly requires another measurement before physical inspection."),
    make_case("A3_RESERVED_UNSUITABLE", maintenance=True, pressure="high", slack=30,
        reservation="fully_reserved", suitability="unsuitable", actions=(A.REVIEW_PLANNED_MAINTENANCE, None),
        rationale="High due pressure is not equipment urgency. Reserved stock ownership is unknown and the candidate window is unsuitable; review constraints or abstain."),
    make_case("A4_READY_PLANNED", maintenance=True, actions=(A.REVIEW_PLANNED_MAINTENANCE,),
        rationale="Low pressure, 480 minutes slack and available stock support planned review, still requiring human approval."),
    make_case("A5_REPLENISHMENT", maintenance=True, reservation="unavailable",
        actions=(A.REVIEW_PLANNED_MAINTENANCE, None),
        rationale="Future replenishment is not current availability. Review a future plan or abstain pending confirmed resources."),
    make_case("A6_CONFLICT", maintenance=True, limitations=(
        "Two current maintenance sources disagree about whether operation can continue; severity cannot be reconciled by any available tool.",),
        actions=(None,), rationale="Unresolvable safety-relevant evidence conflict requires human reconciliation before ranking."),
    make_case("A7_UNKNOWN", trend="unknown", persistence="unknown", measurement=None,
        limitations=("Sensor calibration is unverified; warning cannot be confirmed. Further measurement is required.",),
        actions=(A.REQUEST_ADDITIONAL_DIAGNOSIS, None), rationale="Unverified warning supports additional diagnosis or abstention, not an unqualified inspection recommendation."),
)

# A conclusive limitation can justify stopping early; further reads remain permissible.
CASES = tuple(replace(c, required=(T.GET_MAINTENANCE_CONTEXT,),
    optional=(T.GET_PRODUCTION_CONTEXT, T.GET_RESOURCE_READINESS, *CONDITION)) if c.id == "A6_CONFLICT"
    else replace(c, required=(T.GET_ASSET_CONDITION,), optional=(T.GET_INSPECTION_CONTEXT,))
    if c.id == "A7_UNKNOWN" else c for c in CASES)

# v2: acceptable recommendations are separate from planning preferences.
# Explicit source-owned blockers are inputs to the server evidence gate, not gold labels.
CASES = tuple(replace(c, preferred_actions=c.actions,
    actions=(A.REQUEST_INSPECTION, A.REQUEST_ADDITIONAL_DIAGNOSIS) if c.id in {"A1_PERSISTENT_RAPID", "A2_TRANSIENT_MEASUREMENT"}
    else (A.REQUEST_MAINTENANCE, *c.actions) if c.id in {"A3_RESERVED_UNSUITABLE", "A4_READY_PLANNED", "A5_REPLENISHMENT"}
    else c.actions,
    readiness={**c.readiness, "recommendation_blockers": ["Operating safety evidence is conflicting; source owner reconciliation required"]}
        if c.id == "A6_CONFLICT" else c.readiness,
    packet_data={**c.packet_data, "condition_decision_signals": {
        **c.packet_data["condition_decision_signals"], "additional_measurement_required": True}}
        if c.id == "A7_UNKNOWN" else c.packet_data,
) for c in CASES)

class LimitedPort(Port):
    def __init__(self, domain, data, limitations):
        super().__init__(domain, data)
        self.limitations = limitations

    def lookup(self, **kwargs):
        return super().lookup(**kwargs).model_copy(update={"limitations": self.limitations})


def build_tools(case):
    return ManufacturingDecisionTools(packet_loader=lambda _: deepcopy(case.packet_data), operational_ports={
        "production": LimitedPort("production", deepcopy(case.production), case.limitations),
        "maintenance_readiness": LimitedPort("maintenance_readiness", deepcopy(case.readiness), case.limitations),
    })

class HTTPRecordingProvider(OpenAICompatibleProvider):
    def __init__(self):
        super().__init__()
        self.http_attempts = []

    def _post_chat_completion(self, request_body):
        attempt = {"format": request_body["response_format"]["type"], "status": None}
        self.http_attempts.append(attempt)
        response = super()._post_chat_completion(request_body)
        attempt["status"] = response.status_code
        return response


class AuditedPlanner(StructuredLLMDecisionPlanner):
    """Observe actual fallback triggers without changing planner or production agent."""
    def __init__(self, provider):
        super().__init__(provider)
        self.errors = []

    def select_next_tool(self, **kwargs):
        try:
            return super().select_next_tool(**kwargs)
        except DecisionPlannerError as exc:
            self.errors.append(str(exc))
            raise

    def rank_actions(self, **kwargs):
        try:
            return super().rank_actions(**kwargs)
        except DecisionPlannerError as exc:
            self.errors.append(str(exc))
            raise


def score(case, calls, action, *, operational_error=False):
    attempted = [call.tool_name for call in calls]
    available = [call.tool_name for call in calls if call.status == "available"]
    required = [tool.value for tool in case.required]
    permitted = set(required) | {tool.value for tool in case.optional}
    counts = Counter(attempted)
    extra = sum(n if name not in permitted else max(0, n - 1) for name, n in counts.items())
    missing = sum(name not in available for name in required)
    # Tool order is not causal here: allow permutations and explicitly optional diagnostic lookups.
    path = not operational_error and missing == 0 and extra == 0
    abstained = action is None
    return {"tool_path_acceptable": path, "canonical_path_exact": available == required,
        "unnecessary_tool_calls": extra, "missing_required_tools": missing,
        "action_acceptable": not operational_error and action in case.actions,
        "preference_match": not operational_error and action in (case.preferred_actions or case.actions),
        "abstained": abstained,
        "abstain_appropriate": not operational_error and (None in case.actions if abstained else case.actions != (None,)),
        "joint_success": path and action in case.actions and not operational_error}


def run(case, arm, iteration):
    provider = HTTPRecordingProvider() if arm != "deterministic" else None
    recording = RecordingProvider(provider) if provider else None
    planner = AuditedPlanner(recording) if arm.startswith("llm") else None
    interpreter = StructuredTextEvidenceInterpreter(recording) if arm.endswith("+text") else None
    started = time.perf_counter()
    error = None
    result = None
    try:
        result = ManufacturingDecisionAgent(tools=build_tools(case), planner=planner, text_interpreter=interpreter, sleep=lambda _: None).run(
            DecisionAgentRequest(identity=IDENTITY, actor_role="process_manager" if case.group == "maintenance" else "process_engineer",
                                 policy_facts=case.facts))
    except Exception as exc:
        error = type(exc).__name__  # Do not persist provider bodies or credentials.
    elapsed = time.perf_counter() - started
    calls = recording.calls if recording else []
    proposal = result.session.proposal if result else None
    action = proposal.recommended_action if proposal else None
    failed = error is not None or (result is not None and result.engine == "unavailable") or bool(result and result.session.text_interpretation_errors)
    text_calls = [c for c in calls if c["response_schema_name"] == "decision_text_interpretation"]
    planner_calls = [c for c in calls if c["response_schema_name"] != "decision_text_interpretation"]
    metrics = score(case, result.session.tool_calls if result else (), action, operational_error=failed)
    return {"case": case.id, "arm": arm, "iteration": iteration, **metrics,
        "action": action.value if action else None, "terminal_status": result.session.status.value if result else "error",
        "engine": result.engine if result else "error", "error": error,
        "proposal": proposal.model_dump(mode="json") if proposal else None,
        "tool_calls": [c.model_dump(mode="json") for c in result.session.tool_calls] if result else [],
        "observations": {k: v.model_dump(mode="json") for k, v in result.tool_results.items()} if result else {},
        "fallback_errors": list(result.session.planner_errors) if result else (planner.errors if planner else []),
        "evidence_gate_reason": result.session.recommendation_gate_reason if result else None,
        "text_interpretation_errors": list(result.session.text_interpretation_errors) if result else [],
        "text_interpretations": [x.model_dump(mode="json") for x in result.session.text_interpretations] if result else [],
        "provider_error_count": sum(bool(c.get("error")) for c in calls),
        "latency_seconds": elapsed, "planner_api_latency_seconds": sum(c["latency_seconds"] for c in planner_calls),
        "text_api_calls": len(text_calls), "llm_api_calls": len(calls),
        "text_total_tokens": usage_total(text_calls, "total_tokens"),
        "api_phases": [c["response_schema_name"] for c in calls],
        "planner_api_calls": len(planner_calls),
        "http_requests": len(provider.http_attempts) if provider else 0,
        "http_attempts": provider.http_attempts if provider else [], "total_tokens": usage_total(calls, "total_tokens"),
        "prompt_tokens": usage_total(calls, "prompt_tokens"), "completion_tokens": usage_total(calls, "completion_tokens"),
        "human_approval_required": proposal.human_approval_required if proposal else None,
        "policy_contained": bool(result) and (action is None or action in result.policy.allowed_actions)}


def aggregate(rows):
    def summarize(subset):
        if not subset:
            return {}
        rates = ("tool_path_acceptable", "canonical_path_exact", "action_acceptable", "abstain_appropriate", "joint_success", "preference_match")
        numeric = ("unnecessary_tool_calls", "missing_required_tools", "latency_seconds", "planner_api_calls", "planner_api_latency_seconds", "http_requests", "text_api_calls", "llm_api_calls")
        tokens = [r["total_tokens"] for r in subset if r["total_tokens"] is not None]
        return {"runs": len(subset), **{k + "_rate": statistics.mean(r[k] for r in subset) for k in rates},
            **{"mean_" + k: statistics.mean(r[k] for r in subset) for k in numeric},
            "mean_total_tokens": statistics.mean(tokens) if tokens else None, "token_measured_runs": len(tokens),
            "fallback_runs": sum(bool(r["fallback_errors"]) for r in subset),
            "evidence_gate_runs": sum(bool(r.get("evidence_gate_reason")) for r in subset),
            "provider_errors": sum(r["provider_error_count"] for r in subset),
            "text_error_runs": sum(bool(r.get("text_interpretation_errors")) for r in subset),
            "operational_errors": sum(r["error"] is not None or r["engine"] == "unavailable" for r in subset),
            "abstained": sum(r["abstained"] for r in subset),
            "actions": dict(Counter(r["action"] or "ABSTAIN" for r in subset))}
    arms = tuple(dict.fromkeys(r["arm"] for r in rows))
    return {arm: summarize([r for r in rows if r["arm"] == arm]) for arm in arms} | {
        "by_case": {c.id: {arm: summarize([r for r in rows if r["arm"] == arm and r["case"] == c.id])
                              for arm in arms} for c in CASES}}


def manifest():
    return [{"id": c.id, "policy_group": c.group, "policy_facts": c.facts.model_dump(mode="json"),
        "required_tools": [t.value for t in c.required], "optional_tools": [t.value for t in c.optional],
        "acceptable_actions": [a.value if a else None for a in c.actions],
        "preferred_actions": [a.value if a else None for a in c.preferred_actions], "rationale": c.rationale,
        "packet": c.packet_data, "production": c.production, "readiness": c.readiness,
        "limitations": c.limitations} for c in CASES]


def main():
    global CASES
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-file", type=Path, help="Replay a frozen raw artifact manifest without changing evidence or gold")
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--arm", choices=("both", "deterministic", "text-comparison"), default="both")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.manifest_file:
        source = json.loads(args.manifest_file.read_text())
        CASES = tuple(Case(c["id"], c["policy_group"], DecisionPolicyFacts.model_validate(c["policy_facts"]),
            tuple(T(t) for t in c["required_tools"]), tuple(T(t) for t in c["optional_tools"]),
            tuple(A(a) if a else None for a in c["acceptable_actions"]), c["rationale"], c["packet"],
            c["production"], c["readiness"], tuple(c["limitations"]),
            tuple(A(a) if a else None for a in c.get("preferred_actions", []))) for c in source["manifest"])
    if args.iterations < 1 or args.workers < 1:
        parser.error("iterations and workers must be positive")
    if args.env_file:
        from dotenv import load_dotenv
        load_dotenv(args.env_file, override=True)
    if args.arm != "deterministic":
        from urllib.parse import urlparse
        if (urlparse(os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")).hostname != "api.openai.com"
                or os.getenv("LLM_MODEL") != "gpt-4o-mini"
                or os.getenv("LLM_PROVIDER", "").lower() not in {"openai", "openai-compatible", "openai_compatible"}):
            parser.error("This fixture evaluation is scoped to OpenAI gpt-4o-mini; check configuration")
        if not (os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")):
            parser.error("Configured API key is missing")
    # Warm graph imports before latency timing in either arm.
    from langgraph.graph import StateGraph
    cases = manifest()
    artifact = {"scope": "Synthetic tool-projection fixtures with actual LLM API calls; no live backend or factory outcome measurement",
        "evaluation_version": "v2" if not args.manifest_file else "frozen-manifest-replay",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "iterations": args.iterations, "workers": args.workers,
        "model": os.getenv("LLM_MODEL") if args.arm != "deterministic" else None,
        "manifest_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
        "manifest": cases, "rows": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    arms = ("deterministic", "deterministic+text", "llm+text") if args.arm == "text-comparison" else (("deterministic", "llm") if args.arm == "both" else ("deterministic",))
    jobs = [(c, arm, i) for c in CASES for i in range(1, args.iterations + 1)
            for arm in arms]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for row in pool.map(lambda job: run(*job), jobs):
            artifact["rows"].append(row)
            args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
            print(f'{row["case"]} {row["arm"]} {row["iteration"]}: {row["action"] or "ABSTAIN"}', flush=True)
    artifact["aggregate"] = aggregate(artifact["rows"])
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k:v for k,v in artifact["aggregate"].items() if k != "by_case"}, indent=2))

if __name__ == "__main__":
    main()

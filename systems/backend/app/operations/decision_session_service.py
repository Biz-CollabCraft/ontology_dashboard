"""Application service for manufacturing DecisionSession runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from hashlib import sha256
import json
from copy import deepcopy
import re
from uuid import uuid4

from app.operations.decision_run_store import DecisionRunStore
from app.operations.decision_durable_runner import DurableDecisionRunner
from typing import Callable

from app.operations.decision_policy import DecisionPolicyGuard, decision_policy_facts_from_packet
from app.operations.decision_support_agent import DecisionAgentRequest, DecisionAgentRunResult, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionSession
from app.operations.operational_context_contract import OperationalRequestIdentity

PacketLoader = Callable[[OperationalRequestIdentity], dict]
AgentFactory = Callable[[OperationalRequestIdentity], ManufacturingDecisionAgent]


@dataclass
class DecisionSessionApplicationService:
    packet_loader: PacketLoader
    agent_factory: AgentFactory
    run_store: DecisionRunStore | None = None
    _sessions: dict[str, DecisionSession] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def create(self, *, identity: OperationalRequestIdentity, actor_role: str, request_id: str | None = None, actor_id: str = "") -> DecisionAgentRunResult:
        packet = self.packet_loader(identity)
        self._validate_packet_identity(packet, identity)
        policy_facts = decision_policy_facts_from_packet(packet)
        request = DecisionAgentRequest(identity=identity, actor_role=actor_role, policy_facts=policy_facts)
        agent = self.agent_factory(identity)
        if self.run_store is not None:
            if request_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
                raise ValueError("invalid decision request_id")
            key = json.dumps([identity.model_dump(mode="json"), actor_id, actor_role, request_id or uuid4().hex], sort_keys=True)
            session_id = "DS-" + sha256(key.encode()).hexdigest()
            # Bind the server-owned evidence contents, not just the client snapshot label.
            stable_packet = deepcopy(packet)
            # This field records retrieval time, not a source revision.
            if isinstance(stable_packet.get("evidence_context"), dict):
                stable_packet["evidence_context"].pop("relation_retrieved_at", None)
            evidence_binding = sha256(json.dumps(stable_packet, sort_keys=True, default=str).encode()).hexdigest()
            result = DurableDecisionRunner(agent, self.run_store).run(request, session_id, evidence_binding=evidence_binding)
        else:
            if request_id is not None:
                raise ValueError("durable decision storage unavailable")
            result = agent.run(request)
        with self._lock:
            self._sessions[result.session.decision_session_id] = result.session
        return result

    def get(self, *, decision_session_id: str, identity: OperationalRequestIdentity) -> DecisionSession | None:
        if self.run_store is not None:
            state = self.run_store.load(decision_session_id, identity)
            if state is None:
                return None
            if state.get("result") is not None:
                return DecisionAgentRunResult.model_validate(state["result"]).session
            request = DecisionAgentRequest.model_validate(state["request"])
            policy = DecisionPolicyGuard().evaluate(request.policy_facts)
            from app.operations.decision_support_contract import DecisionToolCall, DecisionSessionStatus
            return DecisionSession(decision_session_id=decision_session_id, identity=identity,
                actor_role=request.actor_role, status=DecisionSessionStatus.WAITING_FOR_TOOL,
                allowed_actions=policy.allowed_actions, created_at=state["created_at"], updated_at=state["created_at"],
                retry_budget_remaining=state["budget"], tool_calls=tuple(DecisionToolCall.model_validate(c) for c in state["calls"]))
        with self._lock:
            session = self._sessions.get(decision_session_id)
        if session is None or session.identity != identity:
            return None
        return session

    @staticmethod
    def _validate_packet_identity(packet: dict, identity: OperationalRequestIdentity) -> None:
        basis = packet.get("snapshot_basis") or {}
        if packet.get("asset_id") != identity.asset_id:
            raise ValueError("decision_session_asset_mismatch")
        if basis.get("artifact_id") != identity.evidence_snapshot_id:
            raise ValueError("decision_session_snapshot_mismatch")

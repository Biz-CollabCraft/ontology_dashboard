"""Application service for manufacturing DecisionSession runs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from threading import Lock
from typing import Callable
from uuid import uuid4

from app.operations.decision_durable_runner import DurableDecisionRunner, configuration_binding
from app.operations.decision_worker import DecisionWorkerSupervisor, WorkerHandle
from app.operations.decision_policy import DecisionPolicyGuard, decision_policy_facts_from_packet
from app.operations.decision_run_store import DecisionRunStore
from app.operations.decision_support_agent import DecisionAgentRequest, DecisionAgentRunResult, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionSession, DecisionSessionStatus, DecisionToolCall
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
    _packets: dict[str, dict] = field(default_factory=dict)
    worker_supervisor: DecisionWorkerSupervisor | None = None

    def __post_init__(self) -> None:
        if self.run_store is not None and self.worker_supervisor is None:
            self.worker_supervisor = DecisionWorkerSupervisor(max_workers=2)

    def enqueue(
        self,
        *,
        identity: OperationalRequestIdentity,
        actor_role: str,
        request_id: str,
        actor_id: str = "",
    ) -> tuple[str, WorkerHandle | None, DecisionAgentRunResult | None]:
        """Durably register a run, then dispatch it to the server-owned worker."""
        if self.run_store is None:
            raise ValueError("durable decision storage unavailable")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
            raise ValueError("invalid decision request_id")
        packet = deepcopy(self.packet_loader(identity))
        self._validate_packet_identity(packet, identity)
        request = DecisionAgentRequest(
            identity=identity,
            actor_role=actor_role,
            policy_facts=decision_policy_facts_from_packet(packet),
        )
        agent = self.agent_factory(identity)
        key = json.dumps(
            [identity.model_dump(mode="json"), actor_id, actor_role, request_id],
            sort_keys=True,
        )
        session_id = "DS-" + sha256(key.encode()).hexdigest()
        binding = _packet_binding(packet)
        initial = DurableDecisionRunner.initial_state(request, evidence_binding=binding)
        initial["created_at"] = agent.now().isoformat()
        state, token = self.run_store.claim(
            session_id,
            identity,
            sha256((configuration_binding(agent, request) + binding).encode()).hexdigest(),
            initial,
        )
        if token is not None:
            self.run_store.release(session_id, identity, token)
        if state.get("result") is not None:
            return session_id, None, DecisionAgentRunResult.model_validate(state["result"])
        supervisor = self.worker_supervisor
        if supervisor is None:
            raise RuntimeError("decision_worker_supervisor_unavailable")
        handle = supervisor.submit(
            lambda: self.create(
                identity=identity,
                actor_role=actor_role,
                request_id=request_id,
                actor_id=actor_id,
            )
        )
        return session_id, handle, None

    def resume(
        self,
        *,
        session_id: str,
        identity: OperationalRequestIdentity,
    ) -> WorkerHandle | None:
        """Dispatch a persisted, incomplete run after a process restart."""
        if self.run_store is None:
            raise ValueError("durable decision storage unavailable")
        state = self.run_store.load(session_id, identity)
        if state is None:
            raise ValueError("decision_session_not_found")
        if state.get("result") is not None:
            return None
        request = DecisionAgentRequest.model_validate(state["request"])
        packet = deepcopy(self.packet_loader(identity))
        self._validate_packet_identity(packet, identity)
        binding = _packet_binding(packet)
        if state.get("evidence_binding") != binding:
            raise ValueError("decision_session_context_changed")
        agent = self.agent_factory(identity)
        supervisor = self.worker_supervisor
        if supervisor is None:
            raise RuntimeError("decision_worker_supervisor_unavailable")
        return supervisor.submit(
            lambda: DurableDecisionRunner(agent, self.run_store).run(
                request,
                session_id,
                evidence_binding=binding,
            )
        )

    def resume_pending(
        self,
        *,
        identity: OperationalRequestIdentity,
        limit: int = 50,
    ) -> list[WorkerHandle]:
        """Requeue expired/incomplete runs for one tenant/project scope."""
        if self.run_store is None:
            raise ValueError("durable decision storage unavailable")
        pending = self.run_store.list_pending(identity, limit=limit)
        handles: list[WorkerHandle] = []
        for session_id, state in pending:
            request = DecisionAgentRequest.model_validate(state["request"])
            if request.identity != identity:
                continue
            handle = self.resume(session_id=session_id, identity=identity)
            if handle is not None:
                handles.append(handle)
        return handles

    def stop_workers(self, *, wait: bool = True) -> None:
        if self.worker_supervisor is not None:
            self.worker_supervisor.stop(wait=wait)

    def create(
        self,
        *,
        identity: OperationalRequestIdentity,
        actor_role: str,
        request_id: str | None = None,
        actor_id: str = "",
    ) -> DecisionAgentRunResult:
        packet = deepcopy(self.packet_loader(identity))
        self._validate_packet_identity(packet, identity)
        policy_facts = decision_policy_facts_from_packet(packet)
        request = DecisionAgentRequest(identity=identity, actor_role=actor_role, policy_facts=policy_facts)
        agent = self.agent_factory(identity)
        if self.run_store is not None:
            if request_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", request_id):
                raise ValueError("invalid decision request_id")
            key = json.dumps(
                [identity.model_dump(mode="json"), actor_id, actor_role, request_id or uuid4().hex],
                sort_keys=True,
            )
            session_id = "DS-" + sha256(key.encode()).hexdigest()
            result = DurableDecisionRunner(agent, self.run_store).run(
                request,
                session_id,
                evidence_binding=_packet_binding(packet),
            )
        else:
            if request_id is not None:
                raise ValueError("durable decision storage unavailable")
            result = agent.run(request)
        # Re-read after exploration: a changed packet invalidates the proposal.
        latest = self.packet_loader(identity)
        self._validate_packet_identity(latest, identity)
        if _decision_revision(latest) != _decision_revision(packet):
            raise ValueError("decision_session_context_changed")
        result = _attach_application_binding(result, packet)
        with self._lock:
            self._sessions[result.session.decision_session_id] = result.session
            self._packets[result.session.decision_session_id] = packet
            expired = [key for key, value in self._sessions.items()
                       if value.expires_at and value.expires_at <= datetime.now(timezone.utc)]
            for key in expired:
                self._sessions.pop(key, None)
                self._packets.pop(key, None)
        return result

    def get(self, *, decision_session_id: str, identity: OperationalRequestIdentity) -> DecisionSession | None:
        if self.run_store is not None:
            state = self.run_store.load(decision_session_id, identity)
            if state is None:
                return None
            packet = self.packet_loader(identity)
            self._validate_packet_identity(packet, identity)
            if state.get("evidence_binding") and state["evidence_binding"] != _packet_binding(packet):
                raise ValueError("decision_session_context_changed")
            if state.get("result") is not None:
                session = _attach_application_binding(
                    DecisionAgentRunResult.model_validate(state["result"]),
                    packet,
                ).session
                self._validate_saved_session(session, identity)
                return session
            request = DecisionAgentRequest.model_validate(state["request"])
            policy = DecisionPolicyGuard().evaluate(request.policy_facts)
            session = DecisionSession(
                decision_session_id=decision_session_id,
                identity=identity,
                actor_role=request.actor_role,
                status=DecisionSessionStatus.WAITING_FOR_TOOL,
                allowed_actions=policy.allowed_actions,
                created_at=state["created_at"],
                updated_at=state["created_at"],
                retry_budget_remaining=state["budget"],
                tool_calls=tuple(DecisionToolCall.model_validate(call) for call in state["calls"]),
                snapshot_basis=dict(packet.get("snapshot_basis") or {}),
                expires_at=datetime.fromisoformat(str(state["created_at"]).replace("Z", "+00:00")) + timedelta(minutes=5),
            )
            self._validate_saved_session(session, identity)
            return session
        with self._lock:
            session = self._sessions.get(decision_session_id)
        if session is None or session.identity != identity:
            return None
        self._validate_saved_session(session, identity, original_packet=self._packets.get(decision_session_id) or {})
        return session

    @staticmethod
    def _validate_packet_identity(packet: dict, identity: OperationalRequestIdentity) -> None:
        basis = packet.get("snapshot_basis") or {}
        if packet.get("asset_id") != identity.asset_id:
            raise ValueError("decision_session_asset_mismatch")
        if basis.get("artifact_id") != identity.evidence_snapshot_id:
            raise ValueError("decision_session_snapshot_mismatch")
        observed_at = datetime.fromisoformat(str(basis.get("observed_at", "")).replace("Z", "+00:00"))
        if observed_at.tzinfo is None or observed_at > identity.decision_as_of:
            raise ValueError("decision_session_as_of_mismatch")

    def _validate_saved_session(
        self,
        session: DecisionSession,
        identity: OperationalRequestIdentity,
        *,
        original_packet: dict | None = None,
    ) -> None:
        if session.identity != identity:
            raise ValueError("decision_session_scope_mismatch")
        if session.expires_at is None or session.expires_at <= datetime.now(timezone.utc):
            raise ValueError("decision_session_expired")
        latest = self.packet_loader(identity)
        self._validate_packet_identity(latest, identity)
        if original_packet is None:
            if dict(latest.get("snapshot_basis") or {}) != dict(session.snapshot_basis or {}):
                raise ValueError("decision_session_context_changed")
            return
        if _decision_revision(latest) != _decision_revision(original_packet):
            raise ValueError("decision_session_context_changed")


def _decision_revision(packet: dict) -> dict:
    # Retrieval timestamps change on every read. Preserve source times and facts.
    transient = {"relation_retrieved_at", "retrieved_at", "validated_at"}
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k not in transient}
        if isinstance(value, (tuple, list)):
            return [stable(v) for v in value]
        return value
    return stable(packet)


def _packet_binding(packet: dict) -> str:
    return sha256(json.dumps(_decision_revision(packet), sort_keys=True, default=str).encode()).hexdigest()


def _attach_application_binding(result: DecisionAgentRunResult, packet: dict) -> DecisionAgentRunResult:
    session = result.session
    return result.model_copy(
        update={
            "session": session.model_copy(
                update={
                    "snapshot_basis": dict(packet.get("snapshot_basis") or {}),
                    "expires_at": session.created_at + timedelta(minutes=5),
                }
            )
        }
    )

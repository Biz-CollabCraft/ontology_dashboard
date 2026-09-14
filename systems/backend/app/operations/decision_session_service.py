"""Application service for manufacturing DecisionSession runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Callable

from app.operations.decision_policy import decision_policy_facts_from_packet
from app.operations.decision_support_agent import DecisionAgentRequest, DecisionAgentRunResult, ManufacturingDecisionAgent
from app.operations.decision_support_contract import DecisionSession
from app.operations.operational_context_contract import OperationalRequestIdentity

PacketLoader = Callable[[OperationalRequestIdentity], dict]
AgentFactory = Callable[[OperationalRequestIdentity], ManufacturingDecisionAgent]


@dataclass
class DecisionSessionApplicationService:
    packet_loader: PacketLoader
    agent_factory: AgentFactory
    _sessions: dict[str, DecisionSession] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)
    _packets: dict[str, dict] = field(default_factory=dict)

    def create(self, *, identity: OperationalRequestIdentity, actor_role: str) -> DecisionAgentRunResult:
        packet = deepcopy(self.packet_loader(identity))
        self._validate_packet_identity(packet, identity)
        policy_facts = decision_policy_facts_from_packet(packet)
        result = self.agent_factory(identity).run(
            DecisionAgentRequest(identity=identity, actor_role=actor_role, policy_facts=policy_facts)
        )
        # Re-read after exploration: a changed packet invalidates the proposal.
        latest = self.packet_loader(identity)
        self._validate_packet_identity(latest, identity)
        if _decision_revision(latest) != _decision_revision(packet):
            raise ValueError("decision_session_context_changed")
        session = result.session.model_copy(update={
            "snapshot_basis": dict(packet.get("snapshot_basis") or {}),
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
        })
        result = result.model_copy(update={"session": session})
        with self._lock:
            self._sessions[session.decision_session_id] = session
            self._packets[session.decision_session_id] = packet
            expired = [key for key, value in self._sessions.items()
                       if value.expires_at and value.expires_at <= datetime.now(timezone.utc)]
            for key in expired:
                self._sessions.pop(key, None)
                self._packets.pop(key, None)
        return result

    def get(self, *, decision_session_id: str, identity: OperationalRequestIdentity) -> DecisionSession | None:
        with self._lock:
            session = self._sessions.get(decision_session_id)
        if session is None or session.identity != identity:
            return None
        if session.expires_at is None or session.expires_at <= datetime.now(timezone.utc):
            raise ValueError("decision_session_expired")
        latest = self.packet_loader(identity)
        self._validate_packet_identity(latest, identity)
        if _decision_revision(latest) != _decision_revision(self._packets.get(decision_session_id) or {}):
            raise ValueError("decision_session_context_changed")
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

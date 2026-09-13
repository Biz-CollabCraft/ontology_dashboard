"""Application service for manufacturing DecisionSession runs."""

from __future__ import annotations

from dataclasses import dataclass, field
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

    def create(self, *, identity: OperationalRequestIdentity, actor_role: str) -> DecisionAgentRunResult:
        packet = self.packet_loader(identity)
        self._validate_packet_identity(packet, identity)
        policy_facts = decision_policy_facts_from_packet(packet)
        result = self.agent_factory(identity).run(
            DecisionAgentRequest(identity=identity, actor_role=actor_role, policy_facts=policy_facts)
        )
        with self._lock:
            self._sessions[result.session.decision_session_id] = result.session
        return result

    def get(self, *, decision_session_id: str, identity: OperationalRequestIdentity) -> DecisionSession | None:
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

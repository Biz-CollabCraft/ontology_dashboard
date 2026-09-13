"""Read-only tool facade for the manufacturing decision-support agent.

The facade projects existing trusted backend sources into five bounded tool
contracts. It does not own domain truth and it never exposes mutation methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.operations.decision_retry import RetryFailureKind
from app.operations.operational_context_contract import (
    OperationalContextEnvelope,
    OperationalContextStatus,
    OperationalRequestIdentity,
    require_matching_scope,
)
from app.operations.operational_context_ports import OperationalContextReadPort


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DecisionToolName(StrEnum):
    GET_ASSET_CONDITION = "get_asset_condition"
    GET_INSPECTION_CONTEXT = "get_inspection_context"
    GET_MAINTENANCE_CONTEXT = "get_maintenance_context"
    GET_PRODUCTION_CONTEXT = "get_production_context"
    GET_RESOURCE_READINESS = "get_resource_readiness"


class DecisionToolResult(FrozenModel):
    tool_name: DecisionToolName
    status: str = Field(min_length=1, max_length=80)
    source_version: str | None = Field(default=None, max_length=240)
    source_refs: tuple[str, ...] = ()
    as_of: datetime
    data: dict[str, Any] = Field(default_factory=dict)
    limitations: tuple[str, ...] = ()


class DecisionToolFailure(RuntimeError):
    def __init__(self, kind: RetryFailureKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


PacketLoader = Callable[[OperationalRequestIdentity], dict[str, Any]]


@dataclass(frozen=True)
class ManufacturingDecisionTools:
    """Project existing trusted sources into the five MVP read-only tools."""

    packet_loader: PacketLoader
    operational_ports: Mapping[str, OperationalContextReadPort]

    @property
    def names(self) -> tuple[DecisionToolName, ...]:
        return tuple(DecisionToolName)

    def call(
        self,
        *,
        tool_name: DecisionToolName,
        identity: OperationalRequestIdentity,
        retrieved_at: datetime,
    ) -> DecisionToolResult:
        if tool_name is DecisionToolName.GET_ASSET_CONDITION:
            return self._asset_condition(identity)
        if tool_name is DecisionToolName.GET_INSPECTION_CONTEXT:
            return self._inspection_context(identity)
        if tool_name is DecisionToolName.GET_MAINTENANCE_CONTEXT:
            return self._maintenance_context(identity, retrieved_at)
        if tool_name is DecisionToolName.GET_PRODUCTION_CONTEXT:
            return self._domain_context(
                tool_name=tool_name,
                domain="production",
                identity=identity,
                retrieved_at=retrieved_at,
            )
        if tool_name is DecisionToolName.GET_RESOURCE_READINESS:
            envelope = self._lookup("maintenance_readiness", identity, retrieved_at)
            data = envelope.data
            return DecisionToolResult(
                tool_name=tool_name,
                status=envelope.status.value,
                source_version=envelope.source_version,
                source_refs=envelope.source_refs,
                as_of=envelope.as_of,
                data={
                    "part_requirements": data.get("part_requirements") or [],
                    "inventory_snapshots": data.get("inventory_snapshots") or [],
                    "technician_readiness": data.get("technician_readiness") or [],
                    "maintenance_windows": data.get("maintenance_windows") or [],
                    "concurrent_work_checks": data.get("concurrent_work_checks") or [],
                } if envelope.status is OperationalContextStatus.AVAILABLE else {},
                limitations=envelope.limitations,
            )
        raise DecisionToolFailure(RetryFailureKind.NON_RETRYABLE, f"unknown tool: {tool_name}")

    def _packet(self, identity: OperationalRequestIdentity) -> dict[str, Any]:
        try:
            packet = self.packet_loader(identity)
        except TimeoutError as exc:
            raise DecisionToolFailure(RetryFailureKind.TIMEOUT, str(exc)) from exc
        except ValueError as exc:
            raise DecisionToolFailure(RetryFailureKind.SCHEMA_VALIDATION, str(exc)) from exc
        except RuntimeError as exc:
            raise DecisionToolFailure(RetryFailureKind.NETWORK, str(exc)) from exc
        basis = packet.get("snapshot_basis") or {}
        if packet.get("asset_id") != identity.asset_id:
            raise DecisionToolFailure(RetryFailureKind.STALE_SNAPSHOT, "packet asset mismatch")
        if basis.get("artifact_id") != identity.evidence_snapshot_id:
            raise DecisionToolFailure(RetryFailureKind.STALE_SNAPSHOT, "packet snapshot mismatch")
        observed_at = basis.get("observed_at")
        if observed_at:
            parsed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            if parsed > identity.decision_as_of:
                raise DecisionToolFailure(RetryFailureKind.STALE_SNAPSHOT, "packet observed after decision_as_of")
        return packet

    def _asset_condition(self, identity: OperationalRequestIdentity) -> DecisionToolResult:
        packet = self._packet(identity)
        risk = packet.get("risk_summary") or {}
        model = packet.get("model_expression_context") or {}
        return DecisionToolResult(
            tool_name=DecisionToolName.GET_ASSET_CONDITION,
            status="available",
            source_version=str((packet.get("snapshot_basis") or {}).get("artifact_id") or identity.evidence_snapshot_id),
            source_refs=tuple(dict.fromkeys(packet.get("source_refs") or model.get("source_refs") or (identity.evidence_snapshot_id,))),
            as_of=identity.decision_as_of,
            data={
                "risk_summary": risk,
                "top_factors": model.get("top_factors") or [],
                "review_priority": packet.get("review_priority") or {},
                "evidence_gaps": packet.get("evidence_gaps") or [],
            },
            limitations=tuple(str(x) for x in packet.get("limitations") or ()),
        )

    def _inspection_context(self, identity: OperationalRequestIdentity) -> DecisionToolResult:
        packet = self._packet(identity)
        history = packet.get("maintenance_history_summary") or {}
        return DecisionToolResult(
            tool_name=DecisionToolName.GET_INSPECTION_CONTEXT,
            status="available",
            source_version=str((packet.get("snapshot_basis") or {}).get("artifact_id") or identity.evidence_snapshot_id),
            source_refs=tuple(dict.fromkeys(packet.get("source_refs") or (identity.evidence_snapshot_id,))),
            as_of=identity.decision_as_of,
            data={
                "inspection_targets": packet.get("inspection_targets") or [],
                "sop_guidance": packet.get("sop_guidance") or [],
                "inspection_results": history.get("inspection_results") or [],
                "evidence_gaps": packet.get("evidence_gaps") or [],
            },
        )

    def _maintenance_context(
        self,
        identity: OperationalRequestIdentity,
        retrieved_at: datetime,
    ) -> DecisionToolResult:
        packet = self._packet(identity)
        history = packet.get("maintenance_history_summary") or {}
        envelope = self._lookup_optional("maintenance_readiness", identity, retrieved_at)
        source_refs = list(packet.get("source_refs") or (identity.evidence_snapshot_id,))
        readiness: dict[str, Any] = {}
        limitations: list[str] = []
        version = str((packet.get("snapshot_basis") or {}).get("artifact_id") or identity.evidence_snapshot_id)
        if envelope is not None:
            source_refs.extend(envelope.source_refs)
            limitations.extend(envelope.limitations)
            if envelope.status is OperationalContextStatus.AVAILABLE:
                readiness = {
                    "maintenance_windows": envelope.data.get("maintenance_windows") or [],
                    "concurrent_work_checks": envelope.data.get("concurrent_work_checks") or [],
                }
                version = f"{version}:{envelope.source_version}"
        return DecisionToolResult(
            tool_name=DecisionToolName.GET_MAINTENANCE_CONTEXT,
            status="available",
            source_version=version,
            source_refs=tuple(dict.fromkeys(source_refs)),
            as_of=identity.decision_as_of,
            data={
                "work_orders": history.get("work_orders") or [],
                "maintenance_actions": history.get("maintenance_actions") or [],
                "maintenance_events": history.get("maintenance_events") or [],
                "recent_equipment_history": history.get("recent_equipment_history") or [],
                **readiness,
            },
            limitations=tuple(limitations),
        )

    def _domain_context(
        self,
        *,
        tool_name: DecisionToolName,
        domain: str,
        identity: OperationalRequestIdentity,
        retrieved_at: datetime,
    ) -> DecisionToolResult:
        envelope = self._lookup(domain, identity, retrieved_at)
        return DecisionToolResult(
            tool_name=tool_name,
            status=envelope.status.value,
            source_version=envelope.source_version,
            source_refs=envelope.source_refs,
            as_of=envelope.as_of,
            data=envelope.data,
            limitations=envelope.limitations,
        )

    def _lookup_optional(
        self,
        domain: str,
        identity: OperationalRequestIdentity,
        retrieved_at: datetime,
    ) -> OperationalContextEnvelope | None:
        if domain not in self.operational_ports:
            return None
        return self._lookup(domain, identity, retrieved_at)

    def _lookup(
        self,
        domain: str,
        identity: OperationalRequestIdentity,
        retrieved_at: datetime,
    ) -> OperationalContextEnvelope:
        port = self.operational_ports.get(domain)
        if port is None:
            raise DecisionToolFailure(RetryFailureKind.NON_RETRYABLE, f"{domain} context is not connected")
        try:
            envelope = port.lookup(identity=identity, retrieved_at=retrieved_at)
        except TimeoutError as exc:
            raise DecisionToolFailure(RetryFailureKind.TIMEOUT, str(exc)) from exc
        except ValueError as exc:
            raise DecisionToolFailure(RetryFailureKind.SCHEMA_VALIDATION, str(exc)) from exc
        except RuntimeError as exc:
            raise DecisionToolFailure(RetryFailureKind.NETWORK, str(exc)) from exc
        require_matching_scope(identity, envelope)
        if envelope.status is OperationalContextStatus.STALE:
            raise DecisionToolFailure(RetryFailureKind.STALE_SNAPSHOT, f"{domain} context is stale")
        return envelope

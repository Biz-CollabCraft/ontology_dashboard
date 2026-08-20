from __future__ import annotations

from typing import Any, Literal, Protocol, Sequence

from .integration import ToolReplacementStatePatch
from .maintenance_schema import MaintenanceEvent, WorkOrder


class DiagnosisResultQueryPort(Protocol):
    """Inbound query boundary for Diagnosis-owned Product Result/Evidence."""

    def product_result(self, product_result_id: str, **scope: Any) -> Any: ...


class EquipmentStatePatchPort(Protocol):
    """Equipment-owned concurrency/apply boundary consumed by Maintenance."""

    def apply_state_patch(
        self,
        *,
        equipment_id: str,
        expected_state_version: int,
        patch: ToolReplacementStatePatch,
        **scope: Any,
    ) -> int: ...


class MaintenanceReadPort(Protocol):
    def work_orders(self, **scope: Any) -> Sequence[WorkOrder]: ...
    def maintenance_events(self, **scope: Any) -> Sequence[MaintenanceEvent]: ...


class MaintenanceEventAccessPort(Protocol):
    """Compatibility event/read-model boundary used by Maintenance HTTP transport."""

    def project_id_for_event(self, event_id: str) -> str: ...
    def ensure_event(self, event_id: str) -> None: ...
    def event_activity(self, event_id: str) -> list[dict[str, Any]]: ...


class MaintenanceActionExecutionPort(Protocol):
    """Outbound command boundary for publishing governed Maintenance actions."""

    def execute(
        self,
        *,
        action_type: str,
        target_kind: Literal["risk_event", "inspection"],
        target_id: str,
        workspace_id: str,
        parameters: dict[str, Any],
        idempotency_key: str,
        principal: Any,
    ) -> dict[str, Any]: ...


__all__ = [
    "DiagnosisResultQueryPort",
    "EquipmentStatePatchPort",
    "MaintenanceActionExecutionPort",
    "MaintenanceEventAccessPort",
    "MaintenanceReadPort",
]

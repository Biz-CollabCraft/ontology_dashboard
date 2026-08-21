from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence

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


class LiveMaintenanceOverlayPort(Protocol):
    def active_asset_ids(self, *, stream_root: str | Path) -> set[str]: ...
    def process_available(self, batch: dict[str, Any]) -> list[dict[str, Any]]: ...


__all__ = [
    "DiagnosisResultQueryPort",
    "EquipmentStatePatchPort",
    "MaintenanceReadPort",
    "LiveMaintenanceOverlayPort",
]

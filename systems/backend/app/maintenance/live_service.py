"""Application service for live predictive-maintenance worker orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class LivePredictiveMaintenanceRuntimePort(Protocol):
    def ingest_once(self, *, stream_root: str | Path) -> dict[str, Any]: ...


class LivePredictiveMaintenanceService:
    def __init__(self, runtime: LivePredictiveMaintenanceRuntimePort) -> None:
        self.runtime = runtime

    def ingest_once(self, *, stream_root: str | Path) -> dict[str, Any]:
        return self.runtime.ingest_once(stream_root=stream_root)


__all__ = [
    "LivePredictiveMaintenanceRuntimePort",
    "LivePredictiveMaintenanceService",
]

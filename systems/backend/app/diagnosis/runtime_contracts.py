from __future__ import annotations

from pathlib import Path
from typing import Any

from app.diagnosis.contracts import (
    CompleteFileTickNotFound,
    filesystem_event_artifact as _contract_filesystem_event_artifact,
    latest_complete_file_tick as _contract_latest_complete_file_tick,
)


def latest_complete_file_tick() -> tuple[
    Path,
    str,
    list[dict[str, Any]],
    list[tuple[str, dict[str, dict[str, Any]]]],
]:
    from app.diagnosis.demo_scenarios import selected_window

    scenario = selected_window()
    if scenario is not None:
        return scenario
    return _contract_latest_complete_file_tick()


def filesystem_event_artifact(
    *, run_id: str, observed_at: str, record: dict[str, Any], event_id: str
) -> dict[str, Any]:
    return _contract_filesystem_event_artifact(
        run_id=run_id,
        observed_at=observed_at,
        record=record,
        event_id=event_id,
    )


__all__ = [
    "CompleteFileTickNotFound",
    "filesystem_event_artifact",
    "latest_complete_file_tick",
]

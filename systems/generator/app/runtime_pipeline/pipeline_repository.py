"""Repository for atomically persisting and retrieving PipelineRunState and AnomalySignalPayload."""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineRecoveryError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    AnomalySignalPayload,
    NotificationEventState,
    PipelineRunState,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


class PipelineRepository:

    """File-based persistent repository for pipeline run states and event payloads."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        if base_dir is None:
            preprocessed_dir = getattr(PATHS, "data_preprocessed_dir", Path("data_preprocessed"))
            self.base_dir = Path(preprocessed_dir)
        else:
            self.base_dir = Path(base_dir)

        self.runs_dir = self.base_dir / "pipeline_runs"
        self.events_dir = self.base_dir / "pipeline_events"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.events_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write_json(self, target_path: Path, data: dict[str, Any]) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.parent / f".tmp_{uuid.uuid4().hex}_{target_path.name}"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            temp_path.replace(target_path)
        except Exception as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise exc

    def save_run_state(self, state: PipelineRunState) -> None:
        """Atomically persist PipelineRunState to disk."""
        target_file = self.runs_dir / f"{state.run_id}.json"
        try:
            self._atomic_write_json(target_file, state.model_dump())
        except Exception as exc:
            logger.exception(f"[PipelineRepository] Failed to save run state '{state.run_id}': {exc}")
            raise PipelineRecoveryError(f"실행 상태 저장 실패: {exc}") from exc

    def get_run_state(self, run_id: str) -> Optional[PipelineRunState]:
        """Fetch PipelineRunState by run ID."""
        clean_id = Path(run_id).name
        target_file = self.runs_dir / f"{clean_id}.json"
        if not target_file.is_file():
            return None
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PipelineRunState.model_validate(data)
        except Exception as exc:
            logger.warning(f"[PipelineRepository] Failed to load run state '{run_id}': {exc}")
            return None

    def save_event(self, event: AnomalySignalPayload) -> None:
        """Atomically persist AnomalySignalPayload to disk."""
        target_file = self.events_dir / f"{event.event_id}.json"
        try:
            self._atomic_write_json(target_file, event.model_dump())
        except Exception as exc:
            logger.warning(f"[PipelineRepository] Failed to save anomaly event '{event.event_id}': {exc}")

    def get_event(self, event_id: str) -> Optional[AnomalySignalPayload]:
        """Fetch AnomalySignalPayload by event ID."""
        clean_id = Path(event_id).name
        target_file = self.events_dir / f"{clean_id}.json"
        if not target_file.is_file():
            return None
        try:
            with open(target_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AnomalySignalPayload.model_validate(data)
        except Exception as exc:
            logger.warning(f"[PipelineRepository] Failed to load anomaly event '{event_id}': {exc}")
            return None

    def list_run_states(self, limit: int = 50) -> list[PipelineRunState]:
        """List recently saved run states."""
        runs = []
        files = sorted(self.runs_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
        for f in files[:limit]:
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                runs.append(PipelineRunState.model_validate(data))
            except Exception:
                continue
        return runs

    def update_notification_event(
        self,
        *,
        run_id: str,
        event_id: str,
        asset_id: str,
        status: Literal["pending", "sending", "retry_wait", "sent", "failed"],
        attempt: int,
        max_attempts: int = 5,
        next_retry_at: Optional[str] = None,
        last_error_code: Optional[str] = None,
        last_error_message: Optional[str] = None,
    ) -> Optional[PipelineRunState]:
        """Atomically update a specific notification event state and aggregate overall notification_status."""
        state = self.get_run_state(run_id)
        if not state:
            return None

        found = False
        updated_events = []
        for ev in state.notification_events:
            if ev.event_id == event_id:
                found = True
                updated_events.append(
                    NotificationEventState(
                        event_id=event_id,
                        asset_id=asset_id or ev.asset_id,
                        status=status,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        next_retry_at=next_retry_at,
                        last_error_code=last_error_code,
                        last_error_message=last_error_message,
                        updated_at=now_utc_iso(),
                    )
                )
            else:
                updated_events.append(ev)

        if not found:
            updated_events.append(
                NotificationEventState(
                    event_id=event_id,
                    asset_id=asset_id,
                    status=status,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    next_retry_at=next_retry_at,
                    last_error_code=last_error_code,
                    last_error_message=last_error_message,
                    updated_at=now_utc_iso(),
                )
            )

        state.notification_events = updated_events

        # Re-aggregate overall notification_status
        if not state.notification_events:
            state.notification_status = "not_required"
        else:
            statuses = {ev.status for ev in state.notification_events}
            if len(state.notification_events) < len(state.notification_event_ids):
                state.notification_status = "pending"
            elif any(s == "failed" for s in statuses):
                state.notification_status = "failed"
            elif all(s == "sent" for s in statuses):
                state.notification_status = "sent"
            else:
                state.notification_status = "pending"

        self.save_run_state(state)
        return state

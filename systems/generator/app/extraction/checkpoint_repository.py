"""Mutable run state and atomic checkpoint repository for extraction runs."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS

logger = logging.getLogger(__name__)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


import time


def _atomic_write_json(file_path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON data using a temporary file with flush/fsync and os.replace."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_name(f".tmp_{file_path.name}_{os.getpid()}_{time.time_ns()}")
    content = json.dumps(data, indent=2, ensure_ascii=False)
    with open(temp_path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    for attempt in range(5):
        try:
            os.replace(str(temp_path), str(file_path))
            return
        except (PermissionError, OSError):
            if attempt < 4:
                time.sleep(0.01)
    # Direct write fallback if Windows file locking persists
    file_path.write_text(content, encoding="utf-8")
    if temp_path.exists():
        try:
            temp_path.unlink()
        except OSError:
            pass


class CheckpointRepository:
    """Manages mutable extraction run state and step checkpoints atomically."""

    def __init__(self, runs_root: Optional[Path] = None) -> None:
        self.runs_root = runs_root or (PATHS.data_preprocessed / "extraction_runs")

    def _get_run_dir(self, run_id: str) -> Path:
        p = self.runs_root / run_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_run_state(
        self,
        run_id: str,
        status: str,
        stage: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Path:
        """Persist high-level run state (e.g. running, staging, succeeded, failed)."""
        run_dir = self._get_run_dir(run_id)
        state_file = run_dir / "run_state.json"
        payload = {
            "run_id": run_id,
            "status": status,
            "stage": stage,
            "updated_at": now_utc_iso(),
            "metadata": metadata or {},
        }
        _atomic_write_json(state_file, payload)
        return state_file

    def get_run_state(self, run_id: str) -> Optional[dict[str, Any]]:
        """Load run state if exists."""
        state_file = self._get_run_dir(run_id) / "run_state.json"
        if not state_file.is_file():
            return None
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_checkpoint(
        self,
        run_id: str,
        source_identity: str,
        source_offset: int,
        last_sequence: Optional[int] = None,
        last_committed_batch_id: Optional[str] = None,
        processed_count: int = 0,
        rejected_count: int = 0,
        duplicate_count: int = 0,
    ) -> Path:
        """Advance checkpoint only after observations and dedup are committed."""
        run_dir = self._get_run_dir(run_id)
        chk_file = run_dir / "checkpoint.json"
        payload = {
            "run_id": run_id,
            "source_identity": source_identity,
            "source_offset": source_offset,
            "last_sequence": last_sequence,
            "last_committed_batch_id": last_committed_batch_id,
            "processed_count": processed_count,
            "rejected_count": rejected_count,
            "duplicate_count": duplicate_count,
            "updated_at": now_utc_iso(),
        }
        _atomic_write_json(chk_file, payload)
        return chk_file

    def get_checkpoint(self, run_id: str) -> Optional[dict[str, Any]]:
        """Load checkpoint if exists."""
        chk_file = self._get_run_dir(run_id) / "checkpoint.json"
        if not chk_file.is_file():
            return None
        try:
            return json.loads(chk_file.read_text(encoding="utf-8"))
        except Exception:
            return None

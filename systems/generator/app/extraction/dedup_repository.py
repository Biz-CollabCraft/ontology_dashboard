"""Persistent deduplication ledger, idempotency repository, and single-writer lock management."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.extraction.extraction_exception import (
    ExtractionAlreadyRunningError,
    ExtractionIdempotencyConflictError,
)

logger = logging.getLogger(__name__)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DedupRepository:
    """SQLite-backed persistent deduplication store and single-writer lock manager."""

    def __init__(self, db_path: Optional[Path] = None, state_root: Optional[Path] = None) -> None:
        self.state_root = state_root or (PATHS.data_preprocessed / "extraction_state")
        self._custom_db_path = db_path

    def _get_db_path(self, dataset_id: str, dataset_version: str) -> Path:
        if self._custom_db_path:
            return self._custom_db_path
        folder = self.state_root / dataset_id / dataset_version
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "dedup.db"

    def _get_connection(self, dataset_id: str, dataset_version: str) -> sqlite3.Connection:
        db_path = self._get_db_path(dataset_id, dataset_version)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        self._ensure_tables(conn)
        return conn

    def _get_idempotency_connection(self) -> sqlite3.Connection:
        db_path = self._custom_db_path or (self.state_root / "idempotency.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency_ledger (
                    idempotency_key TEXT PRIMARY KEY,
                    request_sha256 TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        return conn

    def _ensure_tables(self, conn: sqlite3.Connection) -> None:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dedup_ledger (
                    source_identity TEXT NOT NULL,
                    source_record_id TEXT NOT NULL,
                    processed_at TEXT NOT NULL,
                    PRIMARY KEY (source_identity, source_record_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS single_writer_locks (
                    dataset_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    heartbeat_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS extraction_batches (
                    batch_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    source_identity TEXT NOT NULL,
                    source_start_offset INTEGER NOT NULL,
                    source_end_offset INTEGER NOT NULL,
                    staging_sha256 TEXT,
                    record_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    # --- Single Writer Lock ---

    def acquire_lock(
        self,
        dataset_id: str,
        dataset_version: str,
        run_id: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        """Acquire exclusive single-writer lock for dataset_id + dataset_version.

        Raises ExtractionAlreadyRunningError (409) if active lock exists.
        Recovers gracefully if lock is stale (now > expires_at).
        """
        dataset_key = f"{dataset_id}:{dataset_version}"
        conn = self._get_connection(dataset_id, dataset_version)
        now_ts = time.time()
        expires_ts = now_ts + timeout_seconds

        with conn:
            cur = conn.execute(
                "SELECT run_id, expires_at FROM single_writer_locks WHERE dataset_key = ?",
                (dataset_key,),
            )
            row = cur.fetchone()

            if row is not None:
                existing_run_id = row["run_id"]
                existing_expires = row["expires_at"]

                if existing_run_id == run_id:
                    # Refresh our own lock
                    conn.execute(
                        "UPDATE single_writer_locks SET expires_at = ? WHERE dataset_key = ?",
                        (expires_ts, dataset_key),
                    )
                    return

                if now_ts < existing_expires:
                    # Active lock held by another run
                    raise ExtractionAlreadyRunningError(
                        f"동일한 데이터셋({dataset_id}/{dataset_version})에 대한 추출 작업(run_id='{existing_run_id}')이 현재 실행 중입니다.",
                        details=[{
                            "dataset_id": dataset_id,
                            "dataset_version": dataset_version,
                            "active_run_id": existing_run_id,
                            "expires_in_seconds": round(existing_expires - now_ts, 2),
                        }],
                    )
                else:
                    logger.warning(
                        f"[DedupRepository] Stale lock detected for {dataset_key} (held by {existing_run_id}, expired at {existing_expires}). Overriding."
                    )

            conn.execute(
                """
                INSERT INTO single_writer_locks (dataset_key, run_id, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(dataset_key) DO UPDATE SET
                    run_id = excluded.run_id,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                """,
                (dataset_key, run_id, now_utc_iso(), expires_ts),
            )

    def release_lock(
        self,
        dataset_id: str,
        dataset_version: str,
        run_id: str,
    ) -> None:
        """Release single-writer lock held by this run_id."""
        dataset_key = f"{dataset_id}:{dataset_version}"
        try:
            conn = self._get_connection(dataset_id, dataset_version)
            with conn:
                conn.execute(
                    "DELETE FROM single_writer_locks WHERE dataset_key = ? AND run_id = ?",
                    (dataset_key, run_id),
                )
        except Exception as exc:
            logger.warning(f"[DedupRepository] Failed to release lock for {dataset_key}: {exc}")

    # --- Dedup Ledger ---

    def is_record_processed(
        self,
        source_identity: str,
        source_record_id: str,
        dataset_id: str,
        dataset_version: str,
    ) -> bool:
        """Check if source record has already been committed to dedup ledger."""
        conn = self._get_connection(dataset_id, dataset_version)
        cur = conn.execute(
            "SELECT 1 FROM dedup_ledger WHERE source_identity = ? AND source_record_id = ?",
            (source_identity, source_record_id),
        )
        return cur.fetchone() is not None

    def record_processed_batch(
        self,
        source_identity: str,
        source_record_ids: list[str],
        dataset_id: str,
        dataset_version: str,
    ) -> None:
        """Commit a batch of processed source record IDs to persistent SQLite ledger."""
        if not source_record_ids:
            return
        conn = self._get_connection(dataset_id, dataset_version)
        ts = now_utc_iso()
        rows = [(source_identity, rid, ts) for rid in source_record_ids]
        with conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO dedup_ledger (source_identity, source_record_id, processed_at)
                VALUES (?, ?, ?)
                """,
                rows,
            )

    # --- Idempotency Ledger ---

    def get_idempotency_record(
        self,
        idempotency_key: str,
        dataset_id: Optional[str] = None,
        dataset_version: Optional[str] = None,
    ) -> Optional[tuple[str, dict[str, Any]]]:
        """Fetch existing idempotency record (request_sha256, response_dict) if exists."""
        conn = self._get_idempotency_connection()
        cur = conn.execute(
            "SELECT request_sha256, response_json FROM idempotency_ledger WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        try:
            resp_dict = json.loads(row["response_json"])
            return row["request_sha256"], resp_dict
        except Exception:
            return None

    def save_idempotency_record(
        self,
        idempotency_key: str,
        request_sha256: str,
        response_dict: dict[str, Any],
        dataset_id: Optional[str] = None,
        dataset_version: Optional[str] = None,
    ) -> None:
        """Save successful extraction response under idempotency key."""
        conn = self._get_idempotency_connection()
        with conn:
            conn.execute(
                """
                INSERT INTO idempotency_ledger (idempotency_key, request_sha256, response_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    request_sha256 = excluded.request_sha256,
                    response_json = excluded.response_json
                """,
                (idempotency_key, request_sha256, json.dumps(response_dict, ensure_ascii=False), now_utc_iso()),
            )

    # --- Batch State Management ---

    def create_batch(
        self,
        batch_id: str,
        run_id: str,
        source_identity: str,
        source_start_offset: int,
        source_end_offset: int,
        record_count: int,
        dataset_id: str,
        dataset_version: str,
    ) -> None:
        """Record a new extraction batch in 'pending' status."""
        conn = self._get_connection(dataset_id, dataset_version)
        ts = now_utc_iso()
        with conn:
            conn.execute(
                """
                INSERT INTO extraction_batches
                (batch_id, run_id, source_identity, source_start_offset, source_end_offset, record_count, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    run_id = excluded.run_id,
                    source_identity = excluded.source_identity,
                    source_start_offset = excluded.source_start_offset,
                    source_end_offset = excluded.source_end_offset,
                    record_count = excluded.record_count,
                    status = 'pending',
                    updated_at = excluded.updated_at
                """,
                (batch_id, run_id, source_identity, source_start_offset, source_end_offset, record_count, ts, ts),
            )

    def mark_batch_staged(
        self,
        batch_id: str,
        staging_sha256: str,
        dataset_id: str,
        dataset_version: str,
    ) -> None:
        """Transition batch status to 'staged' after staging files are flushed/fsynced."""
        conn = self._get_connection(dataset_id, dataset_version)
        ts = now_utc_iso()
        with conn:
            conn.execute(
                """
                UPDATE extraction_batches
                SET status = 'staged', staging_sha256 = ?, updated_at = ?
                WHERE batch_id = ?
                """,
                (staging_sha256, ts, batch_id),
            )

    def mark_batch_committed(
        self,
        batch_id: str,
        dataset_id: str,
        dataset_version: str,
    ) -> None:
        """Transition batch status to 'committed' after dedup and checkpoint updates."""
        conn = self._get_connection(dataset_id, dataset_version)
        ts = now_utc_iso()
        with conn:
            conn.execute(
                """
                UPDATE extraction_batches
                SET status = 'committed', updated_at = ?
                WHERE batch_id = ?
                """,
                (ts, batch_id),
            )

    def get_batch(
        self,
        batch_id: str,
        dataset_id: str,
        dataset_version: str,
    ) -> Optional[dict[str, Any]]:
        """Fetch batch record by ID."""
        conn = self._get_connection(dataset_id, dataset_version)
        cur = conn.execute(
            "SELECT * FROM extraction_batches WHERE batch_id = ?",
            (batch_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None

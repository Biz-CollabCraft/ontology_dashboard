"""Persistent FIFO Queue implementation for the Generator Runtime Pipeline."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineDuplicateInputError,
    PipelineQueueItemInvalidError,
    PipelineQueuePersistError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    PipelineQueueItem,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


class PipelineQueue:
    """Persistent FIFO queue backed by SQLite with deduplication and crash recovery."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            preprocessed_dir = getattr(PATHS, "data_preprocessed_dir", Path("data_preprocessed"))
            queue_dir = Path(preprocessed_dir) / "pipeline_queue"
            queue_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = queue_dir / "queue.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue_items (
                    job_id TEXT PRIMARY KEY,
                    source_uri TEXT NOT NULL,
                    source_checksum TEXT NOT NULL,
                    dedup_key TEXT UNIQUE NOT NULL,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status_seq ON queue_items (status, sequence)")
            conn.commit()

    def normalize_uri(self, uri: str) -> str:
        return str(Path(uri).as_posix()).strip()

    def enqueue(
        self,
        *,
        job_id: str,
        source_uri: str,
        source_checksum: str,
        dataset_id: str = "canonical-ai4i-v1",
        dataset_version: str = "canonical-ai4i-physics-v3.1",
    ) -> PipelineQueueItem:
        """Enqueue a new completed observation source file item."""
        clean_job_id = job_id.strip()
        clean_uri = self.normalize_uri(source_uri)
        clean_checksum = source_checksum.strip()

        if not clean_job_id or not clean_uri or not clean_checksum:
            raise PipelineQueueItemInvalidError(
                "job_id, source_uri, and source_checksum must not be empty",
                details=[{"job_id": job_id, "source_uri": source_uri}],
            )

        dedup_key = f"{clean_uri}:{clean_checksum}"
        now = now_utc_iso()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    # Check if active duplicate already exists
                    cur = conn.execute(
                        "SELECT job_id, status FROM queue_items WHERE dedup_key = ?",
                        (dedup_key,),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        ex_status = existing["status"]
                        if ex_status in ("queued", "running", "succeeded"):
                            raise PipelineDuplicateInputError(
                                f"동일한 입력 파일(SHA-256: {clean_checksum[:8]}...)이 이미 등록되어 있습니다 ({ex_status}).",
                                details=[{"job_id": existing["job_id"], "status": ex_status}],
                            )

                    # Get next sequence
                    cur = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM queue_items")
                    next_seq = cur.fetchone()["next_seq"]

                    item = PipelineQueueItem(
                        job_id=clean_job_id,
                        source_uri=clean_uri,
                        source_checksum=clean_checksum,
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                        detected_at=now,
                        sequence=next_seq,
                        attempt=1,
                        status="queued",
                    )

                    conn.execute(
                        """
                        INSERT INTO queue_items (
                            job_id, source_uri, source_checksum, dedup_key,
                            dataset_id, dataset_version, detected_at, sequence,
                            attempt, status, error_code, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.job_id,
                            item.source_uri,
                            item.source_checksum,
                            dedup_key,
                            item.dataset_id,
                            item.dataset_version,
                            item.detected_at,
                            item.sequence,
                            item.attempt,
                            item.status,
                            item.error_code,
                            now,
                            now,
                        ),
                    )
                    conn.commit()
                    logger.info(f"[PipelineQueue] Enqueued job '{item.job_id}' (seq={item.sequence}) for {clean_uri}")
                    return item
            except PipelineDuplicateInputError:
                raise
            except Exception as exc:
                logger.exception(f"[PipelineQueue] Failed to persist queue item: {exc}")
                raise PipelineQueuePersistError(f"작업 큐 저장 실패: {exc}") from exc

    def claim_next(self) -> Optional[PipelineQueueItem]:
        """Claim the next FIFO queued item and transition state to running."""
        now = now_utc_iso()
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    """
                    SELECT * FROM queue_items
                    WHERE status = 'queued'
                    ORDER BY sequence ASC
                    LIMIT 1
                    """
                )
                row = cur.fetchone()
                if row is None:
                    return None

                job_id = row["job_id"]
                conn.execute(
                    """
                    UPDATE queue_items
                    SET status = 'running', updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now, job_id),
                )
                conn.commit()

                return PipelineQueueItem(
                    job_id=row["job_id"],
                    source_uri=row["source_uri"],
                    source_checksum=row["source_checksum"],
                    dataset_id=row["dataset_id"],
                    dataset_version=row["dataset_version"],
                    detected_at=row["detected_at"],
                    sequence=row["sequence"],
                    attempt=row["attempt"],
                    status="running",
                    error_code=row["error_code"],
                )

    def mark_succeeded(self, job_id: str) -> None:
        now = now_utc_iso()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "UPDATE queue_items SET status = 'succeeded', updated_at = ? WHERE job_id = ?",
                (now, job_id),
            )
            conn.commit()

    def mark_failed(self, job_id: str, error_code: Optional[str] = None, dead_letter: bool = False) -> None:
        now = now_utc_iso()
        new_status = "dead_letter" if dead_letter else "failed"
        with self._lock, self._get_connection() as conn:
            conn.execute(
                "UPDATE queue_items SET status = ?, error_code = ?, updated_at = ? WHERE job_id = ?",
                (new_status, error_code, now, job_id),
            )
            conn.commit()

    def mark_retry_wait(self, job_id: str, error_code: Optional[str] = None) -> None:
        now = now_utc_iso()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                UPDATE queue_items
                SET status = 'queued', attempt = attempt + 1, error_code = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (error_code, now, job_id),
            )
            conn.commit()

    def list_items(self, status: Optional[str] = None) -> list[PipelineQueueItem]:
        with self._lock, self._get_connection() as conn:
            if status:
                cur = conn.execute(
                    "SELECT * FROM queue_items WHERE status = ? ORDER BY sequence ASC",
                    (status,),
                )
            else:
                cur = conn.execute("SELECT * FROM queue_items ORDER BY sequence ASC")
            rows = cur.fetchall()
            return [
                PipelineQueueItem(
                    job_id=r["job_id"],
                    source_uri=r["source_uri"],
                    source_checksum=r["source_checksum"],
                    dataset_id=r["dataset_id"],
                    dataset_version=r["dataset_version"],
                    detected_at=r["detected_at"],
                    sequence=r["sequence"],
                    attempt=r["attempt"],
                    status=r["status"],
                    error_code=r["error_code"],
                )
                for r in rows
            ]

    def recover_running_on_startup(self) -> int:
        """Reset any interrupted 'running' jobs back to 'queued' on startup."""
        now = now_utc_iso()
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE queue_items
                SET status = 'queued', attempt = attempt + 1, updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            )
            count = cur.rowcount
            conn.commit()
            if count > 0:
                logger.warning(f"[PipelineQueue] Recovered {count} interrupted 'running' queue items back to 'queued'")
            return count

"""Persistent FIFO Queue implementation for the Generator Runtime Pipeline."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional
from uuid import uuid4

from systems.generator.generator_config import PATHS
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineDuplicateInputError,
    PipelineInputNotFoundError,
    PipelineJobNotFailedError,
    PipelineQueueItemInvalidError,
    PipelineQueuePersistError,
    PipelineSourceAlreadyProcessedError,
    PipelineSourceAlreadyRegisteredError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    PipelineQueueItem,
    compute_source_identity,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


def is_temporary_file(file_path: Path | str) -> bool:
    """Check if file path corresponds to a temporary/partial/swap file."""
    p = Path(file_path)
    name = p.name
    suffix = p.suffix.lower()
    if name.startswith(".") or name.startswith("~"):
        return True
    if suffix in (".tmp", ".temp", ".part", ".swp", ".crdownload") or name.endswith("~"):
        return True
    return False


class PipelineQueue:
    """Persistent FIFO queue backed by SQLite with deduplication, crash recovery, and retry re-enqueue."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        if db_path is None:
            self.db_path = PATHS.pipeline_queue_db
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
                    source_identity TEXT,
                    size_bytes INTEGER,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    pipeline_contract_version TEXT NOT NULL DEFAULT 'generator-prediction-result-v1',
                    detected_at TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 1,
                    retry_of_job_id TEXT,
                    status TEXT NOT NULL,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # Check for missing columns in existing table and alter if needed
            cur = conn.execute("PRAGMA table_info(queue_items)")
            columns = [row["name"] for row in cur.fetchall()]
            if "retry_of_job_id" not in columns:
                conn.execute("ALTER TABLE queue_items ADD COLUMN retry_of_job_id TEXT")
            if "source_identity" not in columns:
                conn.execute("ALTER TABLE queue_items ADD COLUMN source_identity TEXT")
            if "size_bytes" not in columns:
                conn.execute("ALTER TABLE queue_items ADD COLUMN size_bytes INTEGER")
            if "pipeline_contract_version" not in columns:
                conn.execute("ALTER TABLE queue_items ADD COLUMN pipeline_contract_version TEXT DEFAULT 'generator-prediction-result-v1'")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_status_seq ON queue_items (status, sequence)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_queue_source_identity ON queue_items (source_identity, status)")
            conn.commit()

    def normalize_uri(self, uri: str) -> str:
        return str(Path(uri).as_posix()).strip()

    def enqueue(
        self,
        *,
        job_id: str,
        source_uri: str,
        source_checksum: str,
        size_bytes: Optional[int] = None,
        dataset_id: str = "canonical-ai4i-v1",
        dataset_version: str = "canonical-ai4i-physics-v3.1",
        pipeline_contract_version: str = "generator-prediction-result-v1",
        retry_of_job_id: Optional[str] = None,
    ) -> PipelineQueueItem:
        """Enqueue a new completed observation source file item with source identity deduplication."""
        clean_job_id = job_id.strip()
        clean_uri = self.normalize_uri(source_uri)
        clean_checksum = source_checksum.strip()

        if not clean_job_id or not clean_uri or not clean_checksum:
            raise PipelineQueueItemInvalidError(
                "job_id, source_uri, and source_checksum must not be empty",
                details=[{"job_id": job_id, "source_uri": source_uri}],
            )

        if is_temporary_file(clean_uri):
            raise PipelineQueueItemInvalidError(
                f"임시 파일('{clean_uri}')은 큐 등록 대상에서 제외됩니다.",
                details=[{"source_uri": clean_uri}],
            )

        # Infer size_bytes if not passed and file exists locally
        computed_size = size_bytes
        if computed_size is None:
            try:
                local_path = Path(clean_uri)
                if local_path.is_file():
                    computed_size = local_path.stat().st_size
            except Exception:
                pass

        source_identity = compute_source_identity(
            source_checksum=clean_checksum,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            pipeline_contract_version=pipeline_contract_version,
        )
        dedup_key = f"{clean_uri}:{clean_checksum}"
        now = now_utc_iso()

        with self._lock:
            try:
                with self._get_connection() as conn:
                    # Check if active duplicate already exists by source_identity
                    cur = conn.execute(
                        "SELECT job_id, status FROM queue_items WHERE source_identity = ?",
                        (source_identity,),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        ex_status = existing["status"]
                        if ex_status in ("queued", "running", "retry_wait"):
                            raise PipelineSourceAlreadyRegisteredError(
                                f"동일한 입력(source_identity: {source_identity[:8]}...)이 이미 등록되어 있습니다 ({ex_status}).",
                                details=[{"job_id": existing["job_id"], "status": ex_status, "source_identity": source_identity}],
                            )
                        elif ex_status == "succeeded":
                            raise PipelineSourceAlreadyProcessedError(
                                f"동일한 입력(source_identity: {source_identity[:8]}...)이 이미 처리 완료되었습니다.",
                                details=[{"job_id": existing["job_id"], "status": ex_status, "source_identity": source_identity}],
                            )
                        elif ex_status == "dead_letter":
                            raise PipelineDuplicateInputError(
                                f"동일한 입력(source_identity: {source_identity[:8]}...)이 dead_letter 상태입니다. 자동 재등록되지 않습니다.",
                                details=[{"job_id": existing["job_id"], "status": ex_status, "source_identity": source_identity}],
                            )

                    # Get next sequence
                    cur = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM queue_items")
                    next_seq = cur.fetchone()["next_seq"]

                    item = PipelineQueueItem(
                        job_id=clean_job_id,
                        source_uri=clean_uri,
                        source_checksum=clean_checksum,
                        source_identity=source_identity,
                        size_bytes=computed_size,
                        dataset_id=dataset_id,
                        dataset_version=dataset_version,
                        pipeline_contract_version=pipeline_contract_version,
                        detected_at=now,
                        sequence=next_seq,
                        attempt=1,
                        retry_of_job_id=retry_of_job_id,
                        status="queued",
                    )

                    conn.execute(
                        """
                        INSERT INTO queue_items (
                            job_id, source_uri, source_checksum, dedup_key, source_identity, size_bytes,
                            dataset_id, dataset_version, pipeline_contract_version, detected_at, sequence,
                            attempt, retry_of_job_id, status, error_code, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.job_id,
                            item.source_uri,
                            item.source_checksum,
                            dedup_key,
                            item.source_identity,
                            item.size_bytes,
                            item.dataset_id,
                            item.dataset_version,
                            item.pipeline_contract_version,
                            item.detected_at,
                            item.sequence,
                            item.attempt,
                            item.retry_of_job_id,
                            item.status,
                            item.error_code,
                            now,
                            now,
                        ),
                    )
                    conn.commit()
                    logger.info(f"[PipelineQueue] Enqueued job '{item.job_id}' (seq={item.sequence}, identity={source_identity[:8]}) for {clean_uri}")
                    return item
            except (PipelineDuplicateInputError, PipelineSourceAlreadyRegisteredError, PipelineSourceAlreadyProcessedError, PipelineQueueItemInvalidError):
                raise
            except Exception as exc:
                logger.exception(f"[PipelineQueue] Failed to persist queue item: {exc}")
                raise PipelineQueuePersistError(f"작업 큐 저장 실패: {exc}") from exc

    def retry_failed_job(self, job_id: str) -> PipelineQueueItem:
        """Atomically re-enqueue a failed or dead_letter job as a new queue item."""
        now = now_utc_iso()
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT * FROM queue_items WHERE job_id = ?",
                    (job_id,),
                )
                row = cur.fetchone()
                if row is None:
                    raise PipelineInputNotFoundError(
                        f"재등록 대상 작업을 찾을 수 없습니다: '{job_id}'",
                        details=[{"job_id": job_id}],
                    )

                status = row["status"]
                if status not in ("failed", "dead_letter"):
                    raise PipelineJobNotFailedError(
                        f"실패(failed/dead_letter) 상태의 작업만 재등록할 수 있습니다. 현재 상태: '{status}'",
                        details=[{"job_id": job_id, "status": status}],
                    )

                # Release unique constraints on old record while preserving the record
                old_dedup = row["dedup_key"]
                old_identity = row["source_identity"] if "source_identity" in row.keys() else None
                archived_dedup = f"archived:{job_id}:{old_dedup}"
                archived_identity = f"archived:{job_id}:{old_identity}" if old_identity else None
                conn.execute(
                    "UPDATE queue_items SET dedup_key = ?, source_identity = ?, updated_at = ? WHERE job_id = ?",
                    (archived_dedup, archived_identity, now, job_id),
                )

                # Get next sequence
                cur = conn.execute("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM queue_items")
                next_seq = cur.fetchone()["next_seq"]

                contract_ver = row["pipeline_contract_version"] if "pipeline_contract_version" in row.keys() and row["pipeline_contract_version"] else "generator-prediction-result-v1"
                size_b = row["size_bytes"] if "size_bytes" in row.keys() else None

                new_job_id = f"{job_id}-retry-{uuid4().hex[:6]}"
                new_item = PipelineQueueItem(
                    job_id=new_job_id,
                    source_uri=row["source_uri"],
                    source_checksum=row["source_checksum"],
                    source_identity=old_identity,
                    size_bytes=size_b,
                    dataset_id=row["dataset_id"],
                    dataset_version=row["dataset_version"],
                    pipeline_contract_version=contract_ver,
                    detected_at=now,
                    sequence=next_seq,
                    attempt=1,
                    retry_of_job_id=job_id,
                    status="queued",
                )

                conn.execute(
                    """
                    INSERT INTO queue_items (
                        job_id, source_uri, source_checksum, dedup_key, source_identity, size_bytes,
                        dataset_id, dataset_version, pipeline_contract_version, detected_at, sequence,
                        attempt, retry_of_job_id, status, error_code, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        new_item.job_id,
                        new_item.source_uri,
                        new_item.source_checksum,
                        old_dedup,
                        new_item.source_identity,
                        new_item.size_bytes,
                        new_item.dataset_id,
                        new_item.dataset_version,
                        new_item.pipeline_contract_version,
                        new_item.detected_at,
                        new_item.sequence,
                        new_item.attempt,
                        new_item.retry_of_job_id,
                        new_item.status,
                        None,
                        now,
                        now,
                    ),
                )
                conn.commit()
                logger.info(f"[PipelineQueue] Re-enqueued failed job '{job_id}' as new job '{new_job_id}' (seq={next_seq})")
                return new_item

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

                contract_ver = row["pipeline_contract_version"] if "pipeline_contract_version" in row.keys() and row["pipeline_contract_version"] else "generator-prediction-result-v1"
                return PipelineQueueItem(
                    job_id=row["job_id"],
                    source_uri=row["source_uri"],
                    source_checksum=row["source_checksum"],
                    source_identity=row["source_identity"] if "source_identity" in row.keys() else None,
                    size_bytes=row["size_bytes"] if "size_bytes" in row.keys() else None,
                    dataset_id=row["dataset_id"],
                    dataset_version=row["dataset_version"],
                    pipeline_contract_version=contract_ver,
                    detected_at=row["detected_at"],
                    sequence=row["sequence"],
                    attempt=row["attempt"],
                    retry_of_job_id=row["retry_of_job_id"] if "retry_of_job_id" in row.keys() else None,
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
                    source_identity=r["source_identity"] if "source_identity" in r.keys() else None,
                    size_bytes=r["size_bytes"] if "size_bytes" in r.keys() else None,
                    dataset_id=r["dataset_id"],
                    dataset_version=r["dataset_version"],
                    pipeline_contract_version=r["pipeline_contract_version"] if "pipeline_contract_version" in r.keys() and r["pipeline_contract_version"] else "generator-prediction-result-v1",
                    detected_at=r["detected_at"],
                    sequence=r["sequence"],
                    attempt=r["attempt"],
                    retry_of_job_id=r["retry_of_job_id"] if "retry_of_job_id" in r.keys() else None,
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

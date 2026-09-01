from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class PipelineJobRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("progress_json", "checkpoint_json", "result_json"):
            value = item.pop(key)
            item[key.removesuffix("_json")] = json.loads(value) if value else None
        item["activate_on_success"] = bool(item["activate_on_success"])
        item["cancel_requested"] = bool(item["cancel_requested"])
        item["error"] = ({"code": item.pop("error_code"), "message": item.pop("error_message")} if item.get("error_code") else None)
        return item

    def create_or_get(self, item: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._connect() as connection:
            try:
                connection.execute(
                    """INSERT INTO system_pipeline_jobs(
                    job_id,job_type,status,request_id,idempotency_key,run_id,mapping_id,mapping_version,
                    mapping_sha256,source_uri,source_identity,replay_scope,activate_on_success,progress_json,
                    checkpoint_json,result_json,error_code,error_message,retry_count,cancel_requested,
                    created_by,created_at,started_at,heartbeat_at,completed_at,lease_owner,lease_expires_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item["job_id"], item["job_type"], "queued", item["request_id"], item["idempotency_key"],
                        item["run_id"], item["mapping_id"], item["mapping_version"], item["mapping_sha256"],
                        item["source_uri"], None, "full_source", int(item["activate_on_success"]), "{}", None,
                        None, None, None, 0, 0, item["created_by"], item["created_at"], None, None, None, None, None,
                    ),
                )
                created = True
            except sqlite3.IntegrityError:
                created = False
        existing = self.get_by_idempotency_key(item["idempotency_key"])
        if existing is None:
            raise RuntimeError("failed to persist pipeline job")
        return existing, created

    def create_downstream(self, item: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO system_pipeline_jobs(
                job_id,job_type,status,request_id,idempotency_key,run_id,mapping_id,mapping_version,
                mapping_sha256,source_uri,source_identity,replay_scope,activate_on_success,progress_json,
                checkpoint_json,result_json,error_code,error_message,retry_count,cancel_requested,
                created_by,created_at,started_at,heartbeat_at,completed_at,lease_owner,lease_expires_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["job_id"], "downstream_rebuild", "queued", item["request_id"],
                    item["idempotency_key"], item["run_id"], item["mapping_id"],
                    item["mapping_version"], item["mapping_sha256"], item["source_uri"],
                    item["analysis_id"], "impact_snapshot", 0,
                    json.dumps({"analysis_id": item["analysis_id"]}), None, None, None, None,
                    0, 0, item["created_by"], item["created_at"], None, None, None, None, None,
                ),
            )
            for step in steps:
                connection.execute(
                    """INSERT INTO system_pipeline_job_steps(
                    step_id,job_id,action_id,stage,sequence,status,input_json,output_json,
                    error_code,error_message,started_at,completed_at)
                    VALUES(?,?,?,?,?,'pending',?,NULL,NULL,NULL,NULL,NULL)""",
                    (
                        step["step_id"], item["job_id"], step["action_id"], step["stage"],
                        step["sequence"], json.dumps(step["input"], ensure_ascii=False),
                    ),
                )
        return self.get(item["job_id"])

    def list_steps(self, job_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM system_pipeline_job_steps WHERE job_id=? ORDER BY sequence",
                (job_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["input"] = json.loads(item.pop("input_json"))
            raw_output = item.pop("output_json")
            item["output"] = json.loads(raw_output) if raw_output else None
            item["error"] = (
                {"code": item.pop("error_code"), "message": item.pop("error_message")}
                if item.get("error_code") else None
            )
            result.append(item)
        return result

    def start_step(self, step_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE system_pipeline_job_steps SET status='running',started_at=? WHERE step_id=?",
                (self._now(), step_id),
            )

    def finish_step(self, step_id: str, output: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE system_pipeline_job_steps SET status='succeeded',output_json=?,completed_at=? WHERE step_id=?",
                (json.dumps(output, ensure_ascii=False), self._now(), step_id),
            )

    def fail_step(self, step_id: str, code: str, message: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE system_pipeline_job_steps SET status='failed',error_code=?,error_message=?,completed_at=? WHERE step_id=?",
                (code, message, self._now(), step_id),
            )

    def block_remaining_steps(self, job_id: str, after_sequence: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE system_pipeline_job_steps SET status='blocked',
                error_code='SYSTEM_STEP_DEPENDENCY_FAILED',error_message='A prerequisite step failed',completed_at=?
                WHERE job_id=? AND sequence>? AND status='pending'""",
                (self._now(), job_id, after_sequence),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_pipeline_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._decode(row)

    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_pipeline_jobs WHERE idempotency_key=?", (key,)).fetchone()
        return self._decode(row)

    def list(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if status:
                rows = connection.execute("SELECT * FROM system_pipeline_jobs WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM system_pipeline_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows]

    def find_active(self, source_uri: str, mapping_sha256: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM system_pipeline_jobs WHERE source_uri=? AND mapping_sha256=? AND status IN ('queued','running','checkpointed','cancel_requested') ORDER BY created_at LIMIT 1",
                (source_uri, mapping_sha256),
            ).fetchone()
        return self._decode(row)

    def next_runnable(self) -> dict[str, Any] | None:
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM system_pipeline_jobs
                WHERE status IN ('queued','checkpointed')
                   OR (status='running' AND lease_expires_at IS NOT NULL AND lease_expires_at<?)
                ORDER BY created_at LIMIT 1""",
                (now,),
            ).fetchone()
        return self._decode(row)

    def claim(self, job_id: str, owner: str, lease_seconds: int = 60) -> dict[str, Any] | None:
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE system_pipeline_jobs SET status='running',started_at=COALESCE(started_at,?),heartbeat_at=?,lease_owner=?,lease_expires_at=?
                WHERE job_id=? AND status IN ('queued','checkpointed','running') AND (lease_expires_at IS NULL OR lease_expires_at<?)""",
                (now.isoformat(), now.isoformat(), owner, expires, job_id, now.isoformat()),
            )
            if cursor.rowcount != 1:
                return None
        return self.get(job_id)

    def finish(self, job_id: str, result: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE system_pipeline_jobs SET status='succeeded',result_json=?,heartbeat_at=?,completed_at=?,lease_owner=NULL,lease_expires_at=NULL WHERE job_id=?",
                (json.dumps(result, ensure_ascii=False), now, now, job_id),
            )
        return self.get(job_id)

    def fail(self, job_id: str, code: str, message: str) -> dict[str, Any]:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE system_pipeline_jobs SET status='failed',error_code=?,error_message=?,heartbeat_at=?,completed_at=?,lease_owner=NULL,lease_expires_at=NULL WHERE job_id=?",
                (code, message, now, now, job_id),
            )
        return self.get(job_id)

    def request_cancel(self, job_id: str) -> dict[str, Any] | None:
        now = self._now()
        with self._connect() as connection:
            row = connection.execute("SELECT status FROM system_pipeline_jobs WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                return None
            if row["status"] == "queued":
                connection.execute("UPDATE system_pipeline_jobs SET status='cancelled',cancel_requested=1,completed_at=? WHERE job_id=?", (now, job_id))
            elif row["status"] in ("running", "checkpointed"):
                connection.execute("UPDATE system_pipeline_jobs SET status='cancel_requested',cancel_requested=1 WHERE job_id=?", (job_id,))
            else:
                return self.get(job_id)
        return self.get(job_id)

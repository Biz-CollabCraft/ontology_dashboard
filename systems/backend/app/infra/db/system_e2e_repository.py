from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SystemE2ERepository:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _decode(row):
        item = dict(row)
        for key in ("asset_ids_json", "input_ref_json", "output_ref_json", "metadata_json"):
            if key in item:
                item[key.removesuffix("_json")] = json.loads(item.pop(key) or "null")
        if "retryable" in item:
            item["retryable"] = bool(item["retryable"])
        return item

    def record_run(self, item: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO system_e2e_runs VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
                   completed_at=excluded.completed_at,error_code=excluded.error_code,
                   retryable=excluded.retryable,asset_ids_json=excluded.asset_ids_json""",
                (item["run_id"], item["status"], item.get("source_uri"), item.get("source_sha256"),
                 item.get("batch_id"), json.dumps(item.get("asset_ids", [])), item["started_at"],
                 item.get("completed_at"), item.get("error_code"), int(item.get("retryable", False))),
            )

    def append_event(self, item: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO system_e2e_timeline_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["timeline_event_id"], item["occurred_at"], item["stage"], item["status"],
                 item["service"], item["domain"], item.get("request_id"), item["run_id"],
                 item.get("job_id"), item.get("event_id"), item.get("asset_id"), item.get("model_id"),
                 json.dumps(item.get("input_ref")), json.dumps(item.get("output_ref")),
                 item.get("error_code"), int(item.get("retryable", False)), json.dumps(item.get("metadata", {}))),
            )

    def create_alert(self, item: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO dashboard_anomaly_alerts VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (item["alert_id"], item["event_id"], item["asset_id"], item["observed_at"],
                 item["severity"], item["status"], item["headline"], item["product_result_id"],
                 item.get("evidence_id"), item.get("report_id"), item["created_at"]),
            )

    def list_runs(self, limit: int = 100):
        with self._connect() as connection:
            return [self._decode(r) for r in connection.execute(
                "SELECT * FROM system_e2e_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()]

    def get_run(self, run_id: str):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_e2e_runs WHERE run_id=?", (run_id,)).fetchone()
        return self._decode(row) if row else None

    def timeline(self, run_id: str):
        with self._connect() as connection:
            return [self._decode(r) for r in connection.execute(
                "SELECT * FROM system_e2e_timeline_events WHERE run_id=? ORDER BY occurred_at,timeline_event_id", (run_id,)).fetchall()]

    def get_event(self, event_id: str):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_e2e_timeline_events WHERE timeline_event_id=?", (event_id,)).fetchone()
        return self._decode(row) if row else None

    def list_alerts(self, limit: int = 100):
        with self._connect() as connection:
            return [dict(r) for r in connection.execute(
                "SELECT * FROM dashboard_anomaly_alerts ORDER BY observed_at DESC LIMIT ?", (limit,)).fetchall()]

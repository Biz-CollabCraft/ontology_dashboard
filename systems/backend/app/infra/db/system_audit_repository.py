from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SystemAuditRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _decode(row):
        item = dict(row)
        for key in ("before_ref_json", "after_ref_json", "metadata_json", "filters_json"):
            if key in item:
                item[key.removesuffix("_json")] = json.loads(item.pop(key) or "null")
        if "truncated" in item:
            item["truncated"] = bool(item["truncated"])
        return item

    def append_audit(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO system_audit_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["audit_id"], item["occurred_at"], item["actor_id"], item["actor_type"],
                 item["action"], item["resource_type"], item["resource_id"], item.get("resource_version"),
                 item["outcome"], item["request_id"], item.get("run_id"), item.get("job_id"),
                 item.get("event_id"), item.get("reason"), item.get("error_code"),
                 json.dumps(item.get("before_ref")), json.dumps(item.get("after_ref")),
                 json.dumps(item.get("metadata", {})),)
            )
        return item

    def list_audit(self, filters: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
        clauses, values = [], []
        allowed = {"actor_id", "action", "resource_type", "resource_id", "outcome", "request_id", "run_id", "job_id", "event_id"}
        for key, value in filters.items():
            if key in allowed and value:
                clauses.append(f"{key}=?"); values.append(value)
        if filters.get("occurred_from"):
            clauses.append("occurred_at>=?"); values.append(filters["occurred_from"])
        if filters.get("occurred_to"):
            clauses.append("occurred_at<=?"); values.append(filters["occurred_to"])
        sql = "SELECT * FROM system_audit_events" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY occurred_at DESC LIMIT ?"
        values.append(min(max(limit, 1), 10000))
        with self._connect() as connection:
            return [self._decode(row) for row in connection.execute(sql, values).fetchall()]

    def get_audit(self, audit_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_audit_events WHERE audit_id=?", (audit_id,)).fetchone()
        return self._decode(row) if row else None

    def append_log(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("""INSERT INTO system_operational_logs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["log_id"], item["occurred_at"], item["service"], item["domain"], item["severity"],
                 item["message"], item.get("error_code"), item.get("request_id"), item.get("run_id"),
                 item.get("job_id"), item.get("event_id"), item.get("asset_id"), item.get("model_id"),
                 json.dumps(item.get("metadata", {}))))
        return item

    def list_logs(self, filters: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
        clauses, values = [], []
        allowed = {"service", "domain", "severity", "error_code", "request_id", "run_id", "job_id", "event_id", "asset_id", "model_id"}
        for key, value in filters.items():
            if key in allowed and value:
                clauses.append(f"{key}=?"); values.append(value)
        if filters.get("occurred_from"):
            clauses.append("occurred_at>=?"); values.append(filters["occurred_from"])
        if filters.get("occurred_to"):
            clauses.append("occurred_at<=?"); values.append(filters["occurred_to"])
        sql = "SELECT * FROM system_operational_logs" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY occurred_at DESC LIMIT ?"
        values.append(min(max(limit, 1), 10000))
        with self._connect() as connection:
            return [self._decode(row) for row in connection.execute(sql, values).fetchall()]

    def create_export(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute("""INSERT INTO system_log_exports VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item["export_id"], item["requested_by"], item["status"], item["format"],
                 json.dumps(item["filters"]), item.get("record_count", 0), int(item.get("truncated", False)),
                 item.get("logical_uri"), item.get("sha256"), item.get("error_code"), item["created_at"], item.get("completed_at")))
        return item

    def get_export(self, export_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_log_exports WHERE export_id=?", (export_id,)).fetchone()
        return self._decode(row) if row else None

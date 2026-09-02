from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.infra.db.postgresql_compat import postgres_repository_connection


class SystemE2ERepository:
    def __init__(self, database_path: str | Path) -> None:
        self.database = str(database_path)
        self.is_postgresql = self.database.startswith(("postgresql://", "postgresql+psycopg://"))
        self.path = self.database if self.is_postgresql else Path(database_path)

    def _connect(self):
        if self.is_postgresql:
            return postgres_repository_connection(
                self.database.replace("postgresql+psycopg://", "postgresql://", 1),
                identity_access=True,
            )
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
            asset_ids_value = json.dumps(item.get("asset_ids", []))
            asset_ids_sql = "CAST(? AS jsonb)" if self.is_postgresql else "?"
            connection.execute(
                f"""INSERT INTO system_e2e_runs(
                   run_id,status,source_uri,source_sha256,batch_id,asset_ids_json,
                       started_at,completed_at,error_code,retryable,organization_id,project_id,workspace_id
                   ) VALUES(?,?,?,?,?,{asset_ids_sql},?,?,?,?,?,?,?)
                   ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
                   completed_at=excluded.completed_at,error_code=excluded.error_code,
                   retryable=excluded.retryable,asset_ids_json=excluded.asset_ids_json""",
                (item["run_id"], item["status"], item.get("source_uri"), item.get("source_sha256"),
                 item.get("batch_id"), asset_ids_value, item["started_at"],
                 item.get("completed_at"), item.get("error_code"), bool(item.get("retryable", False)),
                 item["organization_id"], item["project_id"], item["workspace_id"]),
            )

    def append_event(self, item: dict[str, Any]) -> None:
        with self._connect() as connection:
            json_value = "CAST(? AS jsonb)" if self.is_postgresql else "?"
            connection.execute(
                f"""INSERT INTO system_e2e_timeline_events(
                       timeline_event_id,occurred_at,stage,status,service,domain,request_id,
                       run_id,job_id,event_id,asset_id,model_id,input_ref_json,output_ref_json,
                       error_code,retryable,metadata_json
                       ,organization_id,project_id,workspace_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,{json_value},{json_value},?,?,{json_value},?,?,?)
                    ON CONFLICT(timeline_event_id) DO NOTHING""",
                (item["timeline_event_id"], item["occurred_at"], item["stage"], item["status"],
                 item["service"], item["domain"], item.get("request_id"), item["run_id"],
                 item.get("job_id"), item.get("event_id"), item.get("asset_id"), item.get("model_id"),
                 json.dumps(item.get("input_ref")), json.dumps(item.get("output_ref")),
                 item.get("error_code"), bool(item.get("retryable", False)), json.dumps(item.get("metadata", {})),
                 item["organization_id"], item["project_id"], item["workspace_id"]),
            )

    def create_alert(self, item: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO dashboard_anomaly_alerts(
                       alert_id,event_id,asset_id,observed_at,severity,status,headline,
                       product_result_id,evidence_id,report_id,created_at
                       ,organization_id,project_id,workspace_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(alert_id) DO NOTHING""",
                (item["alert_id"], item["event_id"], item["asset_id"], item["observed_at"],
                 item["severity"], item["status"], item["headline"], item["product_result_id"],
                 item.get("evidence_id"), item.get("report_id"), item["created_at"],
                 item["organization_id"], item["project_id"], item["workspace_id"]),
            )

    def list_runs(self, limit: int = 100, *, organization_id: str):
        with self._connect() as connection:
            return [self._decode(r) for r in connection.execute(
                "SELECT * FROM system_e2e_runs WHERE organization_id=? ORDER BY started_at DESC LIMIT ?",
                (organization_id, limit)).fetchall()]

    def get_run(self, run_id: str, *, organization_id: str):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_e2e_runs WHERE organization_id=? AND run_id=?", (organization_id, run_id)).fetchone()
        return self._decode(row) if row else None

    def timeline(self, run_id: str, *, organization_id: str):
        with self._connect() as connection:
            return [self._decode(r) for r in connection.execute(
                "SELECT * FROM system_e2e_timeline_events WHERE organization_id=? AND run_id=? ORDER BY occurred_at,timeline_event_id", (organization_id, run_id)).fetchall()]

    def get_event(self, event_id: str, *, organization_id: str):
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_e2e_timeline_events WHERE organization_id=? AND timeline_event_id=?", (organization_id, event_id)).fetchone()
        return self._decode(row) if row else None

    def list_alerts(self, limit: int = 100, *, organization_id: str, project_id: str | None = None, workspace_id: str | None = None):
        clauses, values = ["organization_id=?"], [organization_id]
        if project_id is not None:
            clauses.append("project_id=?"); values.append(project_id)
        if workspace_id is not None:
            clauses.append("workspace_id=?"); values.append(workspace_id)
        values.append(limit)
        with self._connect() as connection:
            return [dict(r) for r in connection.execute(
                f"SELECT * FROM dashboard_anomaly_alerts WHERE {' AND '.join(clauses)} ORDER BY observed_at DESC LIMIT ?", values).fetchall()]

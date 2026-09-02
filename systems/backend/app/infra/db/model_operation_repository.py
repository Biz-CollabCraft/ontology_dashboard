from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class ModelOperationRepository:
    def __init__(self, database_path: str | Path) -> None: self.path = Path(database_path)
    def _connect(self):
        connection = sqlite3.connect(self.path); connection.row_factory = sqlite3.Row; return connection
    def record_selection(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as c:
            c.execute("""INSERT INTO system_model_selection_history(selection_id,model_id,from_model_version,to_model_version,from_manifest_sha256,to_manifest_sha256,action,reason,actor,request_id,status,error_code,error_message,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                item["selection_id"],item["model_id"],item.get("from_model_version"),item.get("to_model_version"),item.get("from_manifest_sha256"),item.get("to_manifest_sha256"),item["action"],item["reason"],item["actor"],item.get("request_id"),item["status"],item.get("error_code"),item.get("error_message"),item["created_at"]))
        return item
    def selection_history(self, model_id: str) -> list[dict[str, Any]]:
        with self._connect() as c: rows=c.execute("SELECT * FROM system_model_selection_history WHERE model_id=? ORDER BY created_at DESC",(model_id,)).fetchall()
        return [dict(row) for row in rows]
    def record_revision(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as c:
            c.execute("""INSERT INTO system_active_model_set_revisions(revision_id,model_set_id,model_set_version,payload_sha256,previous_revision_id,status,requested_by,reason,created_at,activated_at,error_code,error_message,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                item["revision_id"],item["model_set_id"],item["model_set_version"],item["payload_sha256"],item.get("previous_revision_id"),item["status"],item["requested_by"],item["reason"],item["created_at"],item.get("activated_at"),item.get("error_code"),item.get("error_message"),json.dumps(item["payload"],ensure_ascii=False)))
        return item
    def revisions(self) -> list[dict[str, Any]]:
        with self._connect() as c: rows=c.execute("SELECT * FROM system_active_model_set_revisions ORDER BY created_at DESC LIMIT 100").fetchall()
        result=[]
        for row in rows:
            item=dict(row); item["payload"]=json.loads(item.pop("payload_json")); result.append(item)
        return result
    def get_revision(self, revision_id: str) -> dict[str, Any] | None:
        with self._connect() as c: row=c.execute("SELECT * FROM system_active_model_set_revisions WHERE revision_id=?",(revision_id,)).fetchone()
        if not row: return None
        item=dict(row); item["payload"]=json.loads(item.pop("payload_json")); return item

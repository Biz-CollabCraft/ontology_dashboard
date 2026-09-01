from __future__ import annotations
import json, sqlite3
from pathlib import Path


class ImpactAnalysisRepository:
    def __init__(self, database_path: str | Path) -> None: self.path = Path(database_path)
    def _connect(self):
        connection = sqlite3.connect(self.path); connection.row_factory = sqlite3.Row; return connection
    @staticmethod
    def _decode(row):
        if row is None: return None
        item = dict(row)
        for key in ("include_stages_json","source_json","nodes_json","edges_json","actions_json"):
            item[key.removesuffix("_json")] = json.loads(item.pop(key))
        actions = item.pop("actions")
        item["recommended_actions"] = [a for a in actions if a["status"] == "recommended"]
        item["blocked_actions"] = [a for a in actions if a["status"] == "blocked"]
        return item
    def create(self, item):
        with self._connect() as c:
            c.execute("""INSERT INTO system_impact_analyses(analysis_id,status,mapping_id,mapping_version,mapping_sha256,rebuild_job_id,include_stages_json,source_json,nodes_json,edges_json,actions_json,snapshot_sha256,created_by,created_at,completed_at,error_code,error_message) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
                item["analysis_id"],item["status"],item["mapping_id"],item["mapping_version"],item["mapping_sha256"],item["rebuild_job_id"],json.dumps(item["include_stages"]),json.dumps(item["source"]),json.dumps(item["nodes"]),json.dumps(item["edges"]),json.dumps(item["actions"]),item["snapshot_sha256"],item["created_by"],item["created_at"],item["created_at"],None,None))
        return self.get(item["analysis_id"])
    def get(self, analysis_id):
        with self._connect() as c: row=c.execute("SELECT * FROM system_impact_analyses WHERE analysis_id=?",(analysis_id,)).fetchone()
        return self._decode(row)
    def list(self, limit=100):
        with self._connect() as c: rows=c.execute("SELECT * FROM system_impact_analyses ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        return [self._decode(row) for row in rows]

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ManagedAssetDraftRepository:
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
        for field in ("payload", "validation_errors", "validation_warnings"):
            item[field] = json.loads(item.pop(f"{field}_json"))
        error_code = item.pop("publish_error_code")
        error_message = item.pop("publish_error_message")
        item["publish_error"] = (
            {"code": error_code, "message": error_message} if error_code else None
        )
        return item

    def create(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO system_managed_asset_drafts(
                draft_id,asset_type,asset_id,target_version,base_version,revision,status,payload_json,
                payload_sha256,validation_status,validation_errors_json,validation_warnings_json,
                validated_revision,created_by,updated_by,created_at,updated_at,published_at,
                published_sha256,publish_error_code,publish_error_message)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["draft_id"], item["asset_type"], item["asset_id"], item["target_version"],
                    item.get("base_version"), 1, "draft", json.dumps(item["payload"], ensure_ascii=False),
                    item["payload_sha256"], "not_validated", "[]", "[]", None,
                    item["created_by"], item["updated_by"], item["created_at"], item["updated_at"],
                    None, None, None, None,
                ),
            )
        return self.get(item["draft_id"])

    def get(self, draft_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM system_managed_asset_drafts WHERE draft_id=?", (draft_id,)
            ).fetchone()
        return self._decode(row)

    def list(self, asset_type: str | None = None, status: str | None = None, asset_id: str | None = None) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[str] = []
        for column, value in (("asset_type", asset_type), ("status", status), ("asset_id", asset_id)):
            if value:
                conditions.append(f"{column}=?")
                params.append(value)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM system_managed_asset_drafts{where} ORDER BY updated_at DESC LIMIT 100",
                params,
            ).fetchall()
        return [self._decode(row) for row in rows]

    def update_payload(self, draft_id: str, revision: int, payload: dict[str, Any], checksum: str, actor: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE system_managed_asset_drafts SET revision=revision+1,status='draft',
                payload_json=?,payload_sha256=?,validation_status='not_validated',
                validation_errors_json='[]',validation_warnings_json='[]',validated_revision=NULL,
                updated_by=?,updated_at=?,publish_error_code=NULL,publish_error_message=NULL
                WHERE draft_id=? AND revision=? AND status NOT IN ('publishing','published')""",
                (json.dumps(payload, ensure_ascii=False), checksum, actor, self._now(), draft_id, revision),
            )
            if cursor.rowcount != 1:
                return None
        return self.get(draft_id)

    def record_validation(self, draft_id: str, revision: int, checksum: str, errors: list, warnings: list, actor: str) -> dict[str, Any] | None:
        valid = not errors
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE system_managed_asset_drafts SET status=?,validation_status=?,
                validation_errors_json=?,validation_warnings_json=?,validated_revision=?,payload_sha256=?,
                updated_by=?,updated_at=? WHERE draft_id=? AND revision=? AND status NOT IN ('publishing','published')""",
                (
                    "validated" if valid else "validation_failed", "valid" if valid else "invalid",
                    json.dumps(errors), json.dumps(warnings), revision if valid else None, checksum,
                    actor, self._now(), draft_id, revision,
                ),
            )
            if cursor.rowcount != 1:
                return None
        return self.get(draft_id)

    def mark_publishing(self, draft_id: str, revision: int, checksum: str, actor: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE system_managed_asset_drafts SET status='publishing',updated_by=?,updated_at=?
                WHERE draft_id=? AND revision=? AND payload_sha256=? AND status='validated'
                AND validated_revision=revision""",
                (actor, self._now(), draft_id, revision, checksum),
            )
            if cursor.rowcount != 1:
                return None
        return self.get(draft_id)

    def mark_published(self, draft_id: str, checksum: str, actor: str) -> dict[str, Any]:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE system_managed_asset_drafts SET status='published',published_at=?,
                published_sha256=?,updated_by=?,updated_at=?,publish_error_code=NULL,
                publish_error_message=NULL WHERE draft_id=?""",
                (now, checksum, actor, now, draft_id),
            )
        return self.get(draft_id)

    def mark_publish_failed(self, draft_id: str, code: str, message: str, actor: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE system_managed_asset_drafts SET status='publish_failed',
                publish_error_code=?,publish_error_message=?,updated_by=?,updated_at=? WHERE draft_id=?""",
                (code, message, actor, self._now(), draft_id),
            )

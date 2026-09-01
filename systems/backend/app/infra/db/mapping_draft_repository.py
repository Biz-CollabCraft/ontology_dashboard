from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MappingDraftRepository:
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
        item["payload"] = json.loads(item.pop("payload_json"))
        item["validation_errors"] = json.loads(item.pop("validation_errors_json"))
        item["draft_id"] = item.pop("id")
        return item

    def create(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO system_mapping_drafts(
                   id,mapping_id,target_version,base_version,revision,status,payload_json,payload_sha256,
                   validation_status,validation_errors_json,validated_revision,created_by,updated_by,
                   created_at,updated_at,published_at,published_sha256,publish_error_code,publish_error_message)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["draft_id"], item["mapping_id"], item["target_version"], item.get("base_version"),
                    item["revision"], item["status"], json.dumps(item["payload"], ensure_ascii=False),
                    item["payload_sha256"], item["validation_status"], json.dumps(item["validation_errors"]),
                    item.get("validated_revision"), item["created_by"], item["updated_by"], item["created_at"],
                    item["updated_at"], None, None, None, None,
                ),
            )
        return self.get(item["draft_id"])

    def get(self, draft_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM system_mapping_drafts WHERE id=?", (draft_id,)).fetchone()
        return self._decode(row)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM system_mapping_drafts ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows]

    def update_payload(self, draft_id: str, expected_revision: int, payload: dict[str, Any], payload_sha256: str, actor: str) -> dict[str, Any] | None:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE system_mapping_drafts SET revision=revision+1,status='draft',payload_json=?,payload_sha256=?,
                   validation_status='not_validated',validation_errors_json='[]',validated_revision=NULL,
                   updated_by=?,updated_at=?,publish_error_code=NULL,publish_error_message=NULL
                   WHERE id=? AND revision=? AND status NOT IN ('published','publishing','discarded')""",
                (json.dumps(payload, ensure_ascii=False), payload_sha256, actor, now, draft_id, expected_revision),
            )
            if cursor.rowcount != 1:
                return None
        return self.get(draft_id)

    def record_validation(self, draft_id: str, revision: int, *, valid: bool, checksum: str, errors: list[dict[str, Any]], actor: str) -> dict[str, Any] | None:
        now = self._now()
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE system_mapping_drafts SET status=?,validation_status=?,validation_errors_json=?,
                   validated_revision=?,payload_sha256=?,updated_by=?,updated_at=? WHERE id=? AND revision=?""",
                ("validated" if valid else "validation_failed", "valid" if valid else "invalid", json.dumps(errors),
                 revision if valid else None, checksum, actor, now, draft_id, revision),
            )
            if cursor.rowcount != 1:
                return None
        return self.get(draft_id)

    def mark_publishing(self, draft_id: str, revision: int, actor: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE system_mapping_drafts SET status='publishing',updated_by=?,updated_at=?
                   WHERE id=? AND revision=? AND status='validated' AND validated_revision=revision""",
                (actor, self._now(), draft_id, revision),
            )
            if cursor.rowcount != 1:
                return None
        return self.get(draft_id)

    def mark_published(self, draft_id: str, checksum: str, actor: str) -> dict[str, Any]:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """UPDATE system_mapping_drafts SET status='published',published_at=?,published_sha256=?,
                   updated_by=?,updated_at=?,publish_error_code=NULL,publish_error_message=NULL WHERE id=?""",
                (now, checksum, actor, now, draft_id),
            )
        return self.get(draft_id)

    def mark_publish_failed(self, draft_id: str, code: str, message: str, actor: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """UPDATE system_mapping_drafts SET status='publish_failed',publish_error_code=?,publish_error_message=?,
                   updated_by=?,updated_at=? WHERE id=?""",
                (code, message, actor, self._now(), draft_id),
            )
        return self.get(draft_id)

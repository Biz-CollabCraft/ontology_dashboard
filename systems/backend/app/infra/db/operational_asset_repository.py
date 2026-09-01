from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_NAMESPACE = uuid.UUID("cfe7a00c-4bd5-45c0-80a6-0c18ea42bf89")


class OperationalAssetRepository:
    def __init__(self, database_path: str | Path) -> None:
        self.path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _id(*parts: str) -> str:
        return str(uuid.uuid5(_NAMESPACE, ":".join(parts)))

    def reconcile(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        snapshot_sha = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        reconciliation_id = self._id("reconciliation", snapshot_sha)
        now = self._now()
        assets = list(snapshot.get("assets") or [])
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM operational_asset_reconciliations WHERE snapshot_sha256=?",
                (snapshot_sha,),
            ).fetchone()
            if existing is not None:
                return dict(existing)

            seen_versions: set[str] = set()
            for item in assets:
                asset_id = self._id(snapshot["source_system"], item["asset_type"], item["asset_key"])
                version_id = self._id(asset_id, item["version"])
                seen_versions.add(version_id)
                connection.execute(
                    """
                    INSERT INTO operational_assets(id,source_system,asset_type,asset_key,created_at,updated_at)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(source_system,asset_type,asset_key) DO UPDATE SET updated_at=excluded.updated_at
                    """,
                    (asset_id, snapshot["source_system"], item["asset_type"], item["asset_key"], now, now),
                )
                current = connection.execute(
                    "SELECT sha256,registry_status FROM operational_asset_versions WHERE id=?", (version_id,)
                ).fetchone()
                status = item["registry_status"]
                if current is not None and current["sha256"] != item["sha256"]:
                    status = "drifted"
                connection.execute(
                    """
                    INSERT INTO operational_asset_versions(
                      id,asset_id,version,registry_status,lifecycle_status,logical_uri,sha256,
                      schema_id,schema_version,content_type,size_bytes,is_active,pointer_ref,
                      validation_status,validation_errors_json,dependencies_json,first_seen_at,last_seen_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(asset_id,version) DO UPDATE SET
                      registry_status=excluded.registry_status,lifecycle_status=excluded.lifecycle_status,
                      logical_uri=excluded.logical_uri,sha256=excluded.sha256,schema_id=excluded.schema_id,
                      schema_version=excluded.schema_version,content_type=excluded.content_type,
                      size_bytes=excluded.size_bytes,is_active=excluded.is_active,pointer_ref=excluded.pointer_ref,
                      validation_status=excluded.validation_status,
                      validation_errors_json=excluded.validation_errors_json,
                      dependencies_json=excluded.dependencies_json,last_seen_at=excluded.last_seen_at
                    """,
                    (
                        version_id, asset_id, item["version"], status, item.get("lifecycle_status"),
                        item["logical_uri"], item["sha256"], item.get("schema_id"), item.get("schema_version"),
                        item["content_type"], item["size_bytes"], int(item["active"]), item.get("pointer_ref"),
                        item["validation"]["status"], json.dumps(item["validation"]["errors"]),
                        json.dumps(item.get("dependencies") or []), now, now,
                    ),
                )
            rows = connection.execute(
                """SELECT v.id FROM operational_asset_versions v
                   JOIN operational_assets a ON a.id=v.asset_id WHERE a.source_system=?""",
                (snapshot["source_system"],),
            ).fetchall()
            missing = [row["id"] for row in rows if row["id"] not in seen_versions]
            if missing:
                connection.executemany(
                    "UPDATE operational_asset_versions SET registry_status='unavailable',is_active=0,last_seen_at=? WHERE id=?",
                    [(now, item_id) for item_id in missing],
                )
            verified = sum(item["registry_status"] == "verified" for item in assets)
            invalid = sum(item["registry_status"] == "invalid" for item in assets)
            conflicted = sum(item["registry_status"] == "conflicted" for item in assets)
            connection.execute(
                """INSERT INTO operational_asset_reconciliations(
                   id,source_system,snapshot_sha256,status,asset_count,verified_count,
                   invalid_count,conflicted_count,started_at,completed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (reconciliation_id, snapshot["source_system"], snapshot_sha, "succeeded", len(assets), verified, invalid, conflicted, now, now),
            )
        return {
            "id": reconciliation_id, "source_system": snapshot["source_system"],
            "snapshot_sha256": snapshot_sha, "status": "succeeded", "asset_count": len(assets),
            "verified_count": verified, "invalid_count": invalid, "conflicted_count": conflicted,
            "started_at": now, "completed_at": now,
        }

    def list_assets(
        self, *, asset_type: str | None, registry_status: str | None,
        validation_status: str | None, active: bool | None, search: str | None,
        limit: int, offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        if asset_type:
            clauses.append("a.asset_type=?")
            params.append(asset_type)
        if registry_status:
            clauses.append("EXISTS (SELECT 1 FROM operational_asset_versions v WHERE v.asset_id=a.id AND v.registry_status=?)")
            params.append(registry_status)
        if validation_status:
            clauses.append("EXISTS (SELECT 1 FROM operational_asset_versions v WHERE v.asset_id=a.id AND v.validation_status=?)")
            params.append(validation_status)
        if active is not None:
            clauses.append(
                "EXISTS (SELECT 1 FROM operational_asset_versions v WHERE v.asset_id=a.id AND v.is_active=1)"
                if active else
                "NOT EXISTS (SELECT 1 FROM operational_asset_versions v WHERE v.asset_id=a.id AND v.is_active=1)"
            )
        if search:
            clauses.append("(LOWER(a.asset_key) LIKE ? OR EXISTS (SELECT 1 FROM operational_asset_versions v WHERE v.asset_id=a.id AND (LOWER(v.version) LIKE ? OR LOWER(COALESCE(v.schema_id,'')) LIKE ?)))")
            needle = f"%{search.lower()}%"
            params.extend((needle, needle, needle))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as connection:
            total = int(connection.execute("SELECT COUNT(*) FROM operational_assets a" + where, params).fetchone()[0])
            rows = connection.execute(
                "SELECT a.* FROM operational_assets a" + where + " ORDER BY a.asset_type,a.asset_key LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                asset = dict(row)
                versions = connection.execute(
                    "SELECT * FROM operational_asset_versions WHERE asset_id=? ORDER BY is_active DESC,last_seen_at DESC,version DESC,id DESC",
                    (asset["id"],),
                ).fetchall()
                selected = dict(versions[0]) if versions else None
                active_count = sum(bool(version["is_active"]) for version in versions)
                if selected:
                    asset.update({
                        "current_version": selected["version"],
                        "registry_status": "conflicted" if active_count > 1 else selected["registry_status"],
                        "lifecycle_status": selected["lifecycle_status"],
                        "validation_status": selected["validation_status"],
                        "active": bool(selected["is_active"]),
                        "logical_uri": selected["logical_uri"],
                        "sha256": selected["sha256"],
                        "schema_id": selected["schema_id"],
                        "schema_version": selected["schema_version"],
                        "last_seen_at": selected["last_seen_at"],
                    })
                result.append(asset)
        return result, total

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM operational_assets WHERE id=?", (asset_id,)).fetchone()
        return None if row is None else dict(row)

    def list_versions(self, asset_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operational_asset_versions WHERE asset_id=? ORDER BY first_seen_at DESC", (asset_id,)
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["is_active"] = bool(item["is_active"])
            item["validation_errors"] = json.loads(item.pop("validation_errors_json"))
            item["dependencies"] = json.loads(item.pop("dependencies_json"))
            result.append(item)
        return result

    def latest_reconciliation(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operational_asset_reconciliations ORDER BY completed_at DESC,id DESC LIMIT 1"
            ).fetchone()
        return None if row is None else dict(row)

    def resolve_dependency(self, asset_type: str, asset_key: str, version: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT a.id AS asset_id,v.id AS version_id,v.registry_status
                   FROM operational_assets a LEFT JOIN operational_asset_versions v
                     ON v.asset_id=a.id AND v.version=?
                   WHERE a.asset_type=? AND a.asset_key=? LIMIT 1""",
                (version, asset_type, asset_key),
            ).fetchone()
        return None if row is None else dict(row)

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .system_operation_exception import SystemOperationError

_SECRET_KEY = re.compile(r"(authorization|token|password|secret|cookie|api[_-]?key)", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class SystemAuditService:
    def __init__(self, repository, export_root: Path) -> None:
        self.repository = repository
        self.export_root = export_root

    def record(self, **fields: Any) -> dict[str, Any]:
        item = {
            "audit_id": fields.pop("audit_id", str(uuid.uuid4())),
            "occurred_at": fields.pop("occurred_at", _now()),
            "actor_type": fields.pop("actor_type", "system_operator"),
            **fields,
        }
        item["metadata"] = redact(item.get("metadata", {}))
        item["before_ref"] = redact(item.get("before_ref"))
        item["after_ref"] = redact(item.get("after_ref"))
        return self.repository.append_audit(item)

    def safe_record(self, **fields: Any) -> None:
        try:
            self.record(**fields)
        except Exception as exc:
            try:
                self.repository.append_log({
                    "log_id": str(uuid.uuid4()), "occurred_at": _now(), "service": "backend",
                    "domain": "control_plane", "severity": "ERROR",
                    "message": "System audit event could not be persisted.",
                    "error_code": "SYSTEM_AUDIT_WRITE_FAILED", "request_id": fields.get("request_id"),
                    "metadata": {"exception_type": type(exc).__name__},
                })
            except Exception:
                pass

    def record_log(self, *, service: str, domain: str, severity: str, message: str,
                   error_code: str | None = None, request_id: str | None = None,
                   run_id: str | None = None, job_id: str | None = None,
                   event_id: str | None = None, asset_id: str | None = None,
                   model_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.repository.append_log({
            "log_id": str(uuid.uuid4()), "occurred_at": _now(), "service": service,
            "domain": domain, "severity": severity, "message": message,
            "error_code": error_code, "request_id": request_id, "run_id": run_id,
            "job_id": job_id, "event_id": event_id, "asset_id": asset_id,
            "model_id": model_id, "metadata": redact(metadata or {}),
        })

    def list_audit(self, filters: dict[str, Any], limit: int) -> dict[str, Any]:
        items = self.repository.list_audit(filters, limit)
        return {"items": items, "count": len(items)}

    def get_audit(self, audit_id: str) -> dict[str, Any]:
        item = self.repository.get_audit(audit_id)
        if not item:
            raise SystemOperationError(404, "SYSTEM_AUDIT_NOT_FOUND", "감사 기록을 찾을 수 없습니다.")
        return item

    def list_logs(self, filters: dict[str, Any], limit: int) -> dict[str, Any]:
        items = self.repository.list_logs(filters, limit)
        return {"items": items, "count": len(items)}

    def export(self, body, actor: str, request_id: str) -> dict[str, Any]:
        export_id, created_at = str(uuid.uuid4()), _now()
        rows = (self.repository.list_audit(body.filters, body.limit + 1)
                if body.source == "audit" else self.repository.list_logs(body.filters, body.limit + 1))
        truncated, rows = len(rows) > body.limit, rows[:body.limit]
        self.export_root.mkdir(parents=True, exist_ok=True)
        final = self.export_root / f"{export_id}.jsonl"
        fd, temporary_name = tempfile.mkstemp(prefix=f".{export_id}.", suffix=".tmp", dir=self.export_root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                for row in rows:
                    stream.write(json.dumps(redact(row), ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary_name, final)
            digest = hashlib.sha256(final.read_bytes()).hexdigest()
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        item = {"export_id": export_id, "requested_by": actor, "status": "succeeded", "format": "jsonl",
                "filters": redact(body.filters), "record_count": len(rows), "truncated": truncated,
                "logical_uri": f"system-operations/exports/{final.name}", "sha256": digest,
                "error_code": None, "created_at": created_at, "completed_at": _now()}
        self.repository.create_export(item)
        self.safe_record(actor_id=actor, action="logs.export", resource_type="log_export", resource_id=export_id,
                         resource_version=None, outcome="succeeded", request_id=request_id,
                         after_ref={"logical_uri": item["logical_uri"], "sha256": digest}, metadata={"record_count": len(rows)})
        return item

    def get_export(self, export_id: str) -> dict[str, Any]:
        item = self.repository.get_export(export_id)
        if not item:
            raise SystemOperationError(404, "SYSTEM_LOG_EXPORT_NOT_FOUND", "로그 Export를 찾을 수 없습니다.")
        return item

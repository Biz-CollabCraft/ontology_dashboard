from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()[:24]
    return f"{prefix}-{digest}"


class SystemE2EService:
    def __init__(self, repository) -> None:
        self.repository = repository

    def record_prediction_receipt(self, *, payload: dict[str, Any], receipt: Any,
                                  product_results: list[dict[str, Any]], request_id: str) -> None:
        now = _now()
        batch_id = str(receipt.batch_id)
        run_id = str(payload.get("run_id") or batch_id)
        source = payload.get("source_context") or {}
        source_ref = source.get("source_ref") or source
        asset_ids = sorted({str(item.get("asset_id")) for item in payload.get("results", []) if item.get("asset_id")})
        failed = receipt.validation_status in {"conflict", "rejected"}
        self.repository.record_run({"run_id": run_id, "status": "failed" if failed else "succeeded",
            "source_uri": source_ref.get("uri"), "source_sha256": source_ref.get("sha256"),
            "batch_id": batch_id, "asset_ids": asset_ids, "started_at": str(payload.get("emitted_at") or now),
            "completed_at": now, "error_code": receipt.rejection_reason if failed else None, "retryable": False})
        self.repository.append_event({"timeline_event_id": _id("evt", run_id, "prediction_inbox", batch_id),
            "occurred_at": now, "stage": "prediction_inbox", "status": "failed" if failed else "succeeded",
            "service": "backend", "domain": "diagnosis", "request_id": request_id, "run_id": run_id,
            "event_id": batch_id, "input_ref": {"batch_id": batch_id, "sha256": receipt.payload_sha256},
            "output_ref": {"promotion_status": receipt.promotion_status}, "retryable": False})
        for result in product_results:
            artifact_id = str(result["artifact_id"])
            event_id = str(result.get("prediction_result_id") or artifact_id)
            self.repository.append_event({"timeline_event_id": _id("evt", run_id, "product_result", artifact_id),
                "occurred_at": now, "stage": "product_result", "status": "succeeded", "service": "backend",
                "domain": "diagnosis", "request_id": request_id, "run_id": run_id, "event_id": event_id,
                "asset_id": result.get("asset_id"), "output_ref": {"artifact_id": artifact_id}, "retryable": False,
                "metadata": {"status_grade": result.get("status_grade")}})
            grade = str(result.get("status_grade") or "normal")
            if grade != "normal":
                self.repository.create_alert({"alert_id": _id("alert", event_id), "event_id": event_id,
                    "asset_id": str(result["asset_id"]), "observed_at": str(result.get("observed_at") or now),
                    "severity": grade, "status": "open", "headline": f"{result['asset_id']} 이상 징후 감지",
                    "product_result_id": event_id, "evidence_id": result.get("evidence_id"), "created_at": now})

    def list_runs(self, limit=100): return {"items": self.repository.list_runs(limit)}
    def get_run(self, run_id):
        item = self.repository.get_run(run_id)
        if not item: raise KeyError(run_id)
        return item
    def timeline(self, run_id): return {"run": self.get_run(run_id), "events": self.repository.timeline(run_id)}
    def get_event(self, event_id):
        item = self.repository.get_event(event_id)
        if not item: raise KeyError(event_id)
        return item
    def list_alerts(self, limit=100): return {"items": self.repository.list_alerts(limit)}

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

    @staticmethod
    def _public(item: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in item.items() if key not in {"organization_id", "project_id", "workspace_id"}}

    def record_prediction_receipt(self, *, organization_id: str, project_id: str, workspace_id: str,
                                  payload: dict[str, Any], receipt: Any,
                                  product_results: list[dict[str, Any]], request_id: str) -> None:
        supported_grades = {"normal", "attention", "warning", "critical"}
        unsupported_grades = sorted({
            str(result.get("status_grade") or "normal")
            for result in product_results
        } - supported_grades)
        if unsupported_grades:
            raise ValueError(
                "unsupported Product Result status_grade: "
                + ", ".join(unsupported_grades)
            )

        now = _now()
        batch_id = str(receipt.batch_id)
        producer_run_id = str(payload.get("run_id") or batch_id)
        run_id = _id("run", organization_id, project_id, workspace_id, producer_run_id)
        source = payload.get("source_context") or {}
        source_uri = source.get("source_uri")
        source_sha256 = source.get("source_checksum")
        asset_ids = sorted({str(item.get("asset_id")) for item in payload.get("results", []) if item.get("asset_id")})
        failed = receipt.validation_status in {"conflict", "rejected"}
        scope = {"organization_id": organization_id, "project_id": project_id, "workspace_id": workspace_id}
        self.repository.record_run({**scope, "run_id": run_id, "status": "failed" if failed else "succeeded",
            "source_uri": source_uri, "source_sha256": source_sha256,
            "batch_id": batch_id, "asset_ids": asset_ids, "started_at": str(payload.get("emitted_at") or now),
            "completed_at": now, "error_code": receipt.rejection_reason if failed else None, "retryable": False})
        self.repository.append_event({"timeline_event_id": _id("evt", run_id, "prediction_inbox", batch_id),
            "occurred_at": now, "stage": "prediction_inbox", "status": "failed" if failed else "succeeded",
            "service": "backend", "domain": "diagnosis", "request_id": request_id, "run_id": run_id,
            "event_id": batch_id, "input_ref": {"batch_id": batch_id, "sha256": receipt.payload_sha256},
            "output_ref": {"promotion_status": receipt.promotion_status}, "retryable": False,
            "metadata": {"producer_run_id": producer_run_id}, **scope})
        for result in product_results:
            artifact_id = str(result["artifact_id"])
            event_id = str(result.get("prediction_result_id") or artifact_id)
            self.repository.append_event({"timeline_event_id": _id("evt", run_id, "product_result", artifact_id),
                "occurred_at": now, "stage": "product_result", "status": "succeeded", "service": "backend",
                "domain": "diagnosis", "request_id": request_id, "run_id": run_id, "event_id": event_id,
                "asset_id": result.get("asset_id"), "output_ref": {"artifact_id": artifact_id}, "retryable": False,
                "metadata": {"status_grade": result.get("status_grade")}, **scope})
            grade = str(result.get("status_grade") or "normal")
            if grade != "normal":
                self.repository.create_alert({"alert_id": _id("alert", organization_id, project_id, workspace_id, event_id), "event_id": event_id,
                    "asset_id": str(result["asset_id"]), "observed_at": str(result.get("observed_at") or now),
                    "severity": grade, "status": "open", "headline": f"{result['asset_id']} 이상 징후 감지",
                    "product_result_id": event_id, "evidence_id": result.get("evidence_id"), "created_at": now, **scope})

    def list_runs(self, *, organization_id: str, limit=100):
        items = self.repository.list_runs(limit, organization_id=organization_id)
        return {"items": [self._public(item) for item in items], "count": len(items)}
    def get_run(self, run_id, *, organization_id: str):
        item = self.repository.get_run(run_id, organization_id=organization_id)
        if not item: raise KeyError(run_id)
        return self._public(item)
    def timeline(self, run_id, *, organization_id: str): return {"run": self.get_run(run_id, organization_id=organization_id), "events": [self._public(item) for item in self.repository.timeline(run_id, organization_id=organization_id)]}
    def get_event(self, event_id, *, organization_id: str):
        item = self.repository.get_event(event_id, organization_id=organization_id)
        if not item: raise KeyError(event_id)
        return self._public(item)
    def list_alerts(self, *, organization_id: str, project_id: str | None = None, workspace_id: str | None = None, limit=100):
        items = self.repository.list_alerts(limit, organization_id=organization_id, project_id=project_id, workspace_id=workspace_id)
        return {"items": [self._public(item) for item in items], "count": len(items)}

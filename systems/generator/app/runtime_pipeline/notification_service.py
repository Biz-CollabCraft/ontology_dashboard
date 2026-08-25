"""Service for managing Anomaly Signal Outbox and single-dispatch HTTP client."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from systems.generator.generator_config import PATHS
from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineNotificationFailedError,
    PipelineNotificationServerError,
    PipelineNotificationTimeoutError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    AnomalySignalPayload,
    NotificationOutboxItem,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


class NotificationService:
    """HTTP client for dispatching anomaly notifications with Outbox persistence and single-dispatch execution."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        timeout_seconds: float = 5.0,
        outbox_dir: Optional[Path] = None,
    ) -> None:
        self.endpoint_url = endpoint_url or os.environ.get(
            "GENERATOR_ANOMALY_SIGNAL_URL",
            "http://localhost:8000/api/v1/anomaly-events",
        )
        self.timeout = timeout_seconds
        if outbox_dir is None:
            self.outbox_dir = PATHS.notification_outbox_root
        else:
            self.outbox_dir = Path(outbox_dir)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)

    def save_outbox_item(self, item: NotificationOutboxItem) -> Path:
        """Atomically persist or update NotificationOutboxItem file."""
        dest_path = self.outbox_dir / f"{item.event_id}.json"
        temp_path = self.outbox_dir / f".tmp_{item.event_id}.json"
        item.updated_at = now_utc_iso()
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(item.model_dump_json(indent=2))
            f.flush()
            os.fsync(f.fileno())
        temp_path.replace(dest_path)
        return dest_path

    def get_outbox_item(self, event_id: str) -> Optional[NotificationOutboxItem]:
        """Load single outbox item by event_id."""
        path = self.outbox_dir / f"{event_id}.json"
        if not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return NotificationOutboxItem.model_validate(data)
        except Exception as exc:
            logger.error(f"[NotificationService] Failed to load outbox item '{event_id}': {exc}")
            return None

    def list_outbox_items(self, status: Optional[str] = None) -> list[NotificationOutboxItem]:
        """List all outbox items, optionally filtered by status."""
        items: list[NotificationOutboxItem] = []
        for file in sorted(self.outbox_dir.glob("*.json")):
            if file.name.startswith(".tmp_"):
                continue
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                item = NotificationOutboxItem.model_validate(data)
                if status is None or item.status == status:
                    items.append(item)
            except Exception as exc:
                quarantine_dir = self.outbox_dir / "quarantine"
                quarantine_dir.mkdir(parents=True, exist_ok=True)
                dest = quarantine_dir / file.name
                try:
                    file.replace(dest)
                    logger.error(
                        f"[NotificationService] Corrupt outbox file '{file.name}' quarantined to '{dest}': {exc} "
                        f"(error_code=PIPELINE_NOTIFICATION_OUTBOX_CORRUPT, retryable=False)"
                    )
                except Exception:
                    logger.error(f"[NotificationService] Failed to quarantine corrupt file '{file.name}': {exc}")
        return items


    def create_outbox_record(self, payload: AnomalySignalPayload) -> NotificationOutboxItem:
        """Create new pending outbox record for payload."""
        item = NotificationOutboxItem(
            event_id=payload.event_id,
            run_id=payload.run_id,
            job_id=payload.job_id,
            asset_id=payload.asset_id,
            status="pending",
            attempt=0,
            max_attempts=5,
            payload=payload,
        )
        self.save_outbox_item(item)
        return item

    def send_once(self, payload: AnomalySignalPayload) -> dict[str, Any]:
        """Perform a single HTTP POST dispatch attempt to the receiver."""
        body = payload.model_dump_json().encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": payload.event_id,
            "X-Request-ID": payload.run_id,
        }
        req = urllib.request.Request(
            self.endpoint_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status_code = resp.getcode()
                resp_body = resp.read().decode("utf-8")
                logger.info(
                    f"[NotificationService] Successfully sent signal '{payload.event_id}' "
                    f"(HTTP {status_code}) to {self.endpoint_url}"
                )
                return {"delivered": True, "status_code": status_code, "response": resp_body}
        except urllib.error.HTTPError as h_err:
            if 400 <= h_err.code < 500:
                logger.error(
                    f"[NotificationService] Receiver rejected signal '{payload.event_id}' with HTTP {h_err.code}"
                )
                raise PipelineNotificationFailedError(
                    f"신호 수신 시스템이 이상 신호를 거부했습니다 (HTTP {h_err.code})",
                    details=[{"status_code": h_err.code, "event_id": payload.event_id}],
                    retryable=False,
                ) from h_err
            # 5xx server error
            logger.warning(
                f"[NotificationService] Server error from receiver (HTTP {h_err.code}): {h_err}"
            )
            raise PipelineNotificationServerError(
                f"이상 신호 수신 서버 5xx 오류 (HTTP {h_err.code}): {h_err}",
                details=[{"status_code": h_err.code, "event_id": payload.event_id}],
                retryable=True,
            ) from h_err
        except TimeoutError as t_err:
            logger.warning(f"[NotificationService] Timeout sending signal '{payload.event_id}': {t_err}")
            raise PipelineNotificationTimeoutError(
                f"이상 신호 전송 타임아웃 ({self.endpoint_url}): {t_err}",
                details=[{"event_id": payload.event_id, "endpoint": self.endpoint_url}],
                retryable=True,
            ) from t_err
        except Exception as exc:
            logger.warning(f"[NotificationService] Network error sending signal '{payload.event_id}': {exc}")
            raise PipelineNotificationFailedError(
                f"이상 신호 전송 네트워크 오류: {exc}",
                details=[{"event_id": payload.event_id, "error": str(exc)}],
                retryable=True,
            ) from exc

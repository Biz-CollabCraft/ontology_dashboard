"""Service for dispatching Anomaly Signals to external receiving systems."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineNotificationFailedError,
    PipelineNotificationRetryExhaustedError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    AnomalySignalPayload,
)

logger = logging.getLogger(__name__)


class NotificationService:
    """HTTP client for dispatching anomaly notifications with retry and idempotency."""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        timeout_seconds: float = 5.0,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> None:
        self.endpoint_url = endpoint_url or os.environ.get(
            "GENERATOR_ANOMALY_SIGNAL_URL",
            "http://localhost:8000/api/v1/anomaly-events",
        )
        self.timeout = timeout_seconds
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor

    def send_notification(self, payload: AnomalySignalPayload) -> dict[str, Any]:
        """Send anomaly signal payload to configured receiving endpoint."""
        body = payload.model_dump_json().encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": payload.event_id,
            "X-Request-ID": payload.run_id,
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
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
                        f"[NotificationService] Dispatched anomaly signal '{payload.event_id}' "
                        f"(HTTP {status_code}) to {self.endpoint_url}"
                    )
                    return {"delivered": True, "status_code": status_code, "response": resp_body}
            except urllib.error.HTTPError as h_err:
                last_error = h_err
                if 400 <= h_err.code < 500:
                    # Client contract error (4xx) - Fail Fast
                    logger.error(
                        f"[NotificationService] Receiving endpoint rejected signal with HTTP {h_err.code}: {h_err.read().decode('utf-8', errors='ignore')}"
                    )
                    raise PipelineNotificationFailedError(
                        f"신호 수신 시스템이 이상 신호를 거절했습니다 (HTTP {h_err.code})",
                        details=[{"status_code": h_err.code, "event_id": payload.event_id}],
                        retryable=False,
                    ) from h_err
                # 5xx error - retry
                logger.warning(
                    f"[NotificationService] Attempt {attempt}/{self.max_retries} failed (HTTP {h_err.code}): {h_err}"
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    f"[NotificationService] Attempt {attempt}/{self.max_retries} network error: {exc}"
                )

            if attempt < self.max_retries:
                sleep_sec = self.backoff_factor * (2 ** (attempt - 1))
                time.sleep(sleep_sec)

        raise PipelineNotificationRetryExhaustedError(
            f"이상 신호 전송 실패 (최대 {self.max_retries}회 재시도 초과): {last_error}",
            details=[{"event_id": payload.event_id, "endpoint": self.endpoint_url, "error": str(last_error)}],
            retryable=True,
        ) from last_error

"""Background worker dedicated solely to delivering Anomaly Signals from Notification Outbox."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

from systems.generator.app.runtime_pipeline.notification_service import NotificationService
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    NotificationOutboxItem,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


class NotificationWorker:
    """Dedicated background worker polling Outbox and executing retries without re-running pipeline."""

    def __init__(
        self,
        service: NotificationService,
        poll_interval: float = 0.5,
        max_attempts: int = 5,
    ) -> None:
        self.service = service
        self.poll_interval = poll_interval
        self.max_attempts = max_attempts
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background notification worker thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="NotificationWorkerThread",
                daemon=True,
            )
            self._thread.start()
            logger.info("[NotificationWorker] Background notification worker started")

    def stop(self, timeout: float = 10.0) -> None:
        """Signal stop and wait for thread to terminate."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("[NotificationWorker] Background notification worker stopped")

    def process_item(self, item: NotificationOutboxItem) -> bool:
        """Process a single outbox item through send_once and update outbox status."""
        logger.info(f"[NotificationWorker] Delivering signal '{item.event_id}' (attempt={item.attempt + 1}/{item.max_attempts})")
        item.status = "sending"
        self.service.save_outbox_item(item)

        try:
            self.service.send_once(item.payload)
            item.status = "sent"
            item.attempt += 1
            item.last_error_code = None
            item.last_error_message = None
            self.service.save_outbox_item(item)
            logger.info(f"[NotificationWorker] Successfully delivered signal '{item.event_id}'")
            return True
        except Exception as exc:
            err_code = getattr(exc, "code", "PIPELINE_NOTIFICATION_FAILED")
            retryable = getattr(exc, "retryable", False)
            item.attempt += 1
            item.last_error_code = err_code
            item.last_error_message = str(exc)

            if retryable and item.attempt < item.max_attempts:
                backoff_seconds = float(2 ** (item.attempt - 1))  # 1s, 2s, 4s, 8s
                next_time = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
                item.status = "retry_wait"
                item.next_retry_at = next_time.isoformat()
                logger.warning(
                    f"[NotificationWorker] Signal '{item.event_id}' delivery failed (retryable): {exc}. "
                    f"Scheduling retry in {backoff_seconds:.1f}s"
                )
            else:
                item.status = "failed"
                logger.error(
                    f"[NotificationWorker] Signal '{item.event_id}' delivery failed permanently (retryable={retryable}, attempt={item.attempt}): {exc}"
                )

            self.service.save_outbox_item(item)
            return False

    def process_pending(self) -> int:
        """Scan and process all ready pending/retry_wait items. Returns count of processed items."""
        items = self.service.list_outbox_items()
        processed_count = 0
        now_dt = datetime.now(timezone.utc)

        for item in items:
            if item.status == "pending":
                self.process_item(item)
                processed_count += 1
            elif item.status == "retry_wait":
                if item.next_retry_at:
                    try:
                        due_dt = datetime.fromisoformat(item.next_retry_at)
                        if now_dt >= due_dt:
                            self.process_item(item)
                            processed_count += 1
                    except Exception:
                        self.process_item(item)
                        processed_count += 1
                else:
                    self.process_item(item)
                    processed_count += 1

        return processed_count

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = self.process_pending()
                if processed == 0:
                    time.sleep(self.poll_interval)
            except Exception as exc:
                logger.error(f"[NotificationWorker] Error in worker loop: {exc}")
                time.sleep(self.poll_interval)

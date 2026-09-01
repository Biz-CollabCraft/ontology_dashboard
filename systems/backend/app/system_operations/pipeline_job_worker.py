from __future__ import annotations

import logging
import os
import threading

logger = logging.getLogger(__name__)


class PipelineJobWorker:
    def __init__(self, service, *, poll_seconds: float = 1.0) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self.owner = f"backend-{os.getpid()}"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="system-pipeline-job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                job = self.service.repository.next_runnable()
                if job:
                    self.service.execute(job["job_id"], self.owner)
            except Exception:
                logger.exception("System Pipeline Job worker iteration failed")

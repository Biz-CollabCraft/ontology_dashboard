"""Server-owned worker lifecycle for durable DecisionSession execution.

The supervisor owns worker start/stop/drain. Durable state remains in PostgreSQL;
the in-process queue is only a dispatch mechanism and may be rebuilt by a resumer.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock, Thread
from typing import Callable, Generic, TypeVar
from uuid import uuid4

T = TypeVar("T")


@dataclass(frozen=True)
class WorkerHandle:
    job_id: str
    future: Future


class DecisionResumer:
    """Periodic callback runner owned by the application lifecycle."""

    def __init__(self, callback: Callable[[], object], *, interval_seconds: float = 5.0) -> None:
        if interval_seconds < 0.1:
            raise ValueError("resumer interval must be at least 0.1 seconds")
        self.callback = callback
        self.interval_seconds = interval_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name="decision-resumer", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.callback()
            except Exception:
                # A single scope/database failure must not kill the lifecycle loop.
                pass
            self._stop.wait(self.interval_seconds)

    def stop(self, *, wait: bool = True) -> None:
        self._stop.set()
        with self._lock:
            thread, self._thread = self._thread, None
        if wait and thread is not None:
            thread.join(timeout=max(1.0, self.interval_seconds + 1.0))


class DecisionWorkerSupervisor(Generic[T]):
    def __init__(self, *, max_workers: int = 2) -> None:
        if not 1 <= max_workers <= 8:
            raise ValueError("worker parallelism must be between 1 and 8")
        self.max_workers = max_workers
        self.worker_id = f"decision-worker-{uuid4().hex[:12]}"
        self._executor: ThreadPoolExecutor | None = None
        self._stopping = Event()
        self._lock = Lock()
        self._active: dict[str, Future] = {}

    @property
    def running(self) -> bool:
        with self._lock:
            return self._executor is not None and not self._stopping.is_set()

    def start(self) -> None:
        with self._lock:
            if self._stopping.is_set():
                raise RuntimeError("decision_worker_supervisor_stopped")
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix="decision-worker",
                )

    def submit(self, job: Callable[[], T]) -> WorkerHandle:
        self.start()
        with self._lock:
            executor = self._executor
            if executor is None or self._stopping.is_set():
                raise RuntimeError("decision_worker_supervisor_not_running")
            job_id = uuid4().hex
            future = executor.submit(job)
            self._active[job_id] = future

        def forget(done: Future) -> None:
            with self._lock:
                self._active.pop(job_id, None)

        future.add_done_callback(forget)
        return WorkerHandle(job_id=job_id, future=future)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            active = tuple(self._active.values())
            return {
                "worker_id": self.worker_id,
                "running": self._executor is not None and not self._stopping.is_set(),
                "active": len(active),
                "completed": sum(f.done() for f in active),
            }

    def stop(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._lock:
            self._stopping.set()
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=cancel_pending)

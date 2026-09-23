"""Server-owned worker lifecycle for durable DecisionSession execution.

The supervisor owns worker start/stop/drain. Durable state remains in PostgreSQL;
the in-process queue is only a dispatch mechanism and may be rebuilt by a resumer.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock
from typing import Callable, Generic, TypeVar
from uuid import uuid4

T = TypeVar("T")


@dataclass(frozen=True)
class WorkerHandle:
    job_id: str
    future: Future


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

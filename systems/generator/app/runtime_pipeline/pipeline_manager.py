"""Application-level manager coordinating queue, worker, and pipeline execution."""

from __future__ import annotations

import logging
from typing import Any, Optional

from systems.generator.app.runtime_pipeline.prediction_delivery_service import (
    PredictionDeliveryService,
)
from systems.generator.app.runtime_pipeline.prediction_delivery_worker import (
    PredictionDeliveryWorker,
)
from systems.generator.app.runtime_pipeline.pipeline_queue import PipelineQueue
from systems.generator.app.runtime_pipeline.pipeline_repository import PipelineRepository
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    PredictionResultBatchPayload,
    PipelineQueueItem,
    PipelineRunState,
)
from systems.generator.app.runtime_pipeline.pipeline_service import PipelineService
from systems.generator.app.runtime_pipeline.pipeline_worker import PipelineWorker

logger = logging.getLogger(__name__)


class PipelineManager:
    """Application singleton managing queue, workers lifecycle, and status reporting."""

    _instance: Optional[PipelineManager] = None

    def __init__(
        self,
        queue: Optional[PipelineQueue] = None,
        repository: Optional[PipelineRepository] = None,
        service: Optional[PipelineService] = None,
        prediction_delivery_service: Optional[PredictionDeliveryService] = None,
    ) -> None:
        self.repository = repository or PipelineRepository()
        self.queue = queue or PipelineQueue()
        self.prediction_delivery_service = prediction_delivery_service or PredictionDeliveryService()
        self.service = service or PipelineService(
            repository=self.repository,
            prediction_delivery_service=self.prediction_delivery_service,
        )
        self.worker = PipelineWorker(queue=self.queue, service=self.service)
        self.prediction_delivery_worker = PredictionDeliveryWorker(
            service=self.prediction_delivery_service,
            repository=self.repository,
        )
        self._is_running = False

    @property
    def notification_worker(self) -> PredictionDeliveryWorker:
        return self.prediction_delivery_worker

    @classmethod
    def get_instance(cls) -> PipelineManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def set_instance(cls, instance: Optional[PipelineManager]) -> None:
        cls._instance = instance

    def start(self) -> None:
        """Startup lifecycle hook: recover interrupted jobs and start background workers."""
        from systems.generator.generator_config import PATHS
        if not PATHS.runtime_prediction_enabled:
            self._is_running = False
            logger.info("[PipelineManager] Generator Runtime Prediction is disabled (GENERATOR_RUNTIME_PREDICTION_ENABLED=false). Background workers will not start.")
            return

        if self._is_running:
            return
        recovered = self.queue.recover_running_on_startup()
        logger.info(f"[PipelineManager] Startup recovery completed: {recovered} running jobs reset")
        self.worker.start()
        self.prediction_delivery_worker.start()
        self._is_running = True

    def stop(self, timeout: float = 10.0) -> None:
        """Shutdown lifecycle hook: drain workers and release resources."""
        if not self._is_running:
            return
        self.worker.stop(timeout=timeout)
        self.prediction_delivery_worker.stop(timeout=timeout)
        self._is_running = False
        logger.info("[PipelineManager] Shutdown completed")

    def enqueue(
        self,
        *,
        job_id: str,
        source_uri: str,
        source_checksum: str,
        size_bytes: Optional[int] = None,
        dataset_id: str = "canonical-ai4i-v1",
        dataset_version: str = "canonical-ai4i-physics-v3.1",
        pipeline_contract_version: str = "generator-prediction-result-v1",
    ) -> PipelineQueueItem:
        """Enqueue new observation source file for processing."""
        from systems.generator.generator_config import PATHS
        from systems.generator.app.runtime_pipeline.pipeline_exception import (
            PipelineRuntimePredictionDisabledError,
        )
        if not PATHS.runtime_prediction_enabled:
            raise PipelineRuntimePredictionDisabledError(
                "Runtime Prediction Pipeline이 비활성화되어 있어 enqueue 요청을 수락할 수 없습니다. (GENERATOR_RUNTIME_PREDICTION_ENABLED=false)",
                retryable=False,
            )
        return self.queue.enqueue(
            job_id=job_id,
            source_uri=source_uri,
            source_checksum=source_checksum,
            size_bytes=size_bytes,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            pipeline_contract_version=pipeline_contract_version,
        )

    def retry_failed_job(self, job_id: str) -> PipelineQueueItem:
        """Explicitly re-enqueue a failed or dead_letter job."""
        from systems.generator.generator_config import PATHS
        from systems.generator.app.runtime_pipeline.pipeline_exception import (
            PipelineRuntimePredictionDisabledError,
        )
        if not PATHS.runtime_prediction_enabled:
            raise PipelineRuntimePredictionDisabledError(
                "Runtime Prediction Pipeline이 비활성화되어 있어 작업 재시도를 수락할 수 없습니다. (GENERATOR_RUNTIME_PREDICTION_ENABLED=false)",
                retryable=False,
            )
        return self.queue.retry_failed_job(job_id=job_id)

    def get_status(self) -> dict[str, Any]:
        """Inspection summary of queue and worker state."""
        from systems.generator.generator_config import PATHS
        queued_items = self.queue.list_items(status="queued")
        running_items = self.queue.list_items(status="running")
        recent_runs = self.repository.list_run_states(limit=10)

        if not PATHS.runtime_prediction_enabled:
            return {
                "enabled": False,
                "worker_active": False,
                "delivery_worker_active": False,
                "mode": "disabled",
                "reason": "backend_receiver_not_ready",
                "queued_count": len(queued_items),
                "running_count": len(running_items),
                "current_job": self.worker._current_job.model_dump() if self.worker._current_job else None,
                "recent_runs": [r.model_dump() for r in recent_runs],
            }

        return {
            "enabled": True,
            "worker_active": self._is_running,
            "delivery_worker_active": getattr(self.prediction_delivery_worker, "_is_running", False),
            "mode": "active",
            "queued_count": len(queued_items),
            "running_count": len(running_items),
            "current_job": self.worker._current_job.model_dump() if self.worker._current_job else None,
            "recent_runs": [r.model_dump() for r in recent_runs],
        }

    def get_run_state(self, run_id: str) -> Optional[PipelineRunState]:
        return self.repository.get_run_state(run_id)

    def get_event(self, event_id: str) -> Optional[PredictionResultBatchPayload]:
        return self.repository.get_event(event_id)

    def list_queue_items(self, status: Optional[str] = None) -> list[PipelineQueueItem]:
        return self.queue.list_items(status=status)

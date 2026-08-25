"""State transition manager for individual Pipeline runs."""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineStateTransitionInvalidError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
    ModelPredictionResult,
    PipelineError,
    PipelineRunState,
    StageState,
    now_utc_iso,
)

logger = logging.getLogger(__name__)


class PipelineStateManager:
    """Manages state transitions and output file references for an individual run."""

    def __init__(self, run_state: PipelineRunState) -> None:
        self.state = run_state

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        job_id: str,
        source_ref: ArtifactReference,
    ) -> PipelineStateManager:
        """Create a fresh PipelineRunState instance."""
        state = PipelineRunState(
            run_id=run_id,
            job_id=job_id,
            status="pending",
            current_stage=None,
            source_ref=source_ref,
            stages={},
            prediction_results=[],
            anomaly_detected=None,
            notification_status=None,
            started_at=None,
            finished_at=None,
            errors=[],
        )
        return cls(state)

    def start_run(self) -> None:
        if self.state.status != "pending":
            raise PipelineStateTransitionInvalidError(
                f"Cannot start pipeline run from status '{self.state.status}'",
                details=[{"run_id": self.state.run_id, "status": self.state.status}],
            )
        self.state.status = "running"
        self.state.started_at = now_utc_iso()

    def start_stage(
        self,
        stage_name: str,
        input_refs: Optional[list[ArtifactReference]] = None,
    ) -> StageState:
        """Transition a stage to running."""
        now = now_utc_iso()
        stage = self.state.stages.get(stage_name)
        if stage is None:
            stage = StageState(
                stage_name=stage_name,
                status="running",
                attempt=1,
                started_at=now,
                input_refs=input_refs or [],
                output_refs=[],
            )
            self.state.stages[stage_name] = stage
        else:
            if stage.status == "running":
                raise PipelineStateTransitionInvalidError(
                    f"Stage '{stage_name}' is already running",
                    details=[{"run_id": self.state.run_id, "stage": stage_name}],
                )
            stage.status = "running"
            stage.attempt += 1
            stage.started_at = now
            if input_refs:
                stage.input_refs = input_refs

        self.state.current_stage = stage_name
        return stage

    def succeed_stage(
        self,
        stage_name: str,
        output_refs: list[ArtifactReference],
    ) -> StageState:
        """Mark a stage succeeded ONLY after output files are validated and published."""
        stage = self.state.stages.get(stage_name)
        if stage is None or stage.status != "running":
            raise PipelineStateTransitionInvalidError(
                f"Cannot succeed stage '{stage_name}' because it is not running",
                details=[{"run_id": self.state.run_id, "stage": stage_name}],
            )
        stage.status = "succeeded"
        stage.finished_at = now_utc_iso()
        stage.output_refs = output_refs
        return stage

    def fail_stage(
        self,
        stage_name: str,
        error_code: str,
        error_message: str,
        *,
        retryable: bool = False,
        details: Optional[list[dict[str, Any]]] = None,
    ) -> StageState:
        """Mark a stage failed and append to run error list."""
        now = now_utc_iso()
        stage = self.state.stages.get(stage_name)
        if stage is None:
            stage = StageState(
                stage_name=stage_name,
                status="failed",
                attempt=1,
                started_at=now,
            )
            self.state.stages[stage_name] = stage

        stage.status = "failed"
        stage.finished_at = now
        stage.error_code = error_code
        stage.error_message = error_message
        stage.retryable = retryable

        err = PipelineError(
            code=error_code,
            message=error_message,
            stage=stage_name,
            details=details or [],
            retryable=retryable,
            attempt=stage.attempt,
            occurred_at=now,
        )
        self.state.errors.append(err)
        return stage

    def record_predictions(
        self,
        results: list[ModelPredictionResult],
        anomaly_detected: Optional[bool],
    ) -> None:
        self.state.prediction_results = results
        self.state.anomaly_detected = anomaly_detected

    def record_notification(self, status: Literal["not_required", "pending", "sent", "failed"]) -> None:
        self.state.notification_status = status

    def finish_run(
        self,
        final_status: Literal["succeeded", "partially_succeeded", "failed"],
    ) -> None:
        self.state.status = final_status
        self.state.current_stage = None
        self.state.finished_at = now_utc_iso()

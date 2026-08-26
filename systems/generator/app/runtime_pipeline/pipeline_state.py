"""State transition manager for individual Pipeline runs."""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from systems.generator.app.runtime_pipeline.pipeline_exception import (
    PipelineStateTransitionInvalidError,
)
from systems.generator.app.runtime_pipeline.pipeline_schema import (
    ArtifactReference,
    InternalModelPredictionResult,
    PipelineCheckpoint,
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
            prediction_delivery_status=None,
            prediction_event_ids=[],
            prediction_events=[],
            started_at=None,
            finished_at=None,
            errors=[],
            last_completed_stage=None,
            next_stage="preprocessing",
            resume_count=0,
            resumed_from_stage=None,
            checkpoint_status="resumable",
            cleanup_status="not_started",
            intermediate_outputs=[],
            checkpoint=None,
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

    def record_checkpoint(
        self,
        *,
        stage_name: str,
        next_stage: Optional[str] = None,
        stage_outputs: Optional[list[ArtifactReference]] = None,
        model_snapshot: Optional[dict[str, Any]] = None,
        source_identity: str = "",
        dataset_id: str = "canonical-ai4i-v1",
        dataset_version: str = "canonical-ai4i-physics-v3.1",
        pipeline_contract_version: str = "generator-prediction-result-v1",
        status: Literal["resumable", "debug_only", "cleanup_pending", "completed", "invalidated"] = "resumable",
    ) -> PipelineCheckpoint:
        """Atomically construct and bind a verified stage checkpoint."""
        now = now_utc_iso()
        existing_outputs = dict(self.state.checkpoint.stage_outputs) if self.state.checkpoint else {}
        if stage_outputs is not None:
            existing_outputs[stage_name] = stage_outputs

        existing_snapshot = dict(self.state.checkpoint.model_snapshot) if self.state.checkpoint else {}
        if model_snapshot is not None:
            existing_snapshot.update(model_snapshot)

        chk = PipelineCheckpoint(
            checkpoint_version="generator-runtime-checkpoint-v1",
            run_id=self.state.run_id,
            job_id=self.state.job_id,
            source_identity=source_identity or (self.state.checkpoint.source_identity if self.state.checkpoint else ""),
            source_uri=self.state.source_ref.uri,
            source_checksum=self.state.source_ref.sha256,
            source_size_bytes=self.state.source_ref.size_bytes,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            pipeline_contract_version=pipeline_contract_version,
            last_completed_stage=stage_name,  # type: ignore
            next_stage=next_stage,  # type: ignore
            status=status,
            created_at=self.state.checkpoint.created_at if self.state.checkpoint else now,
            updated_at=now,
            stage_outputs=existing_outputs,
            model_snapshot=existing_snapshot,
            errors=list(self.state.errors),
        )
        self.state.checkpoint = chk
        self.state.last_completed_stage = stage_name
        self.state.next_stage = next_stage
        self.state.checkpoint_status = status
        return chk

    def mark_resumed(self, from_stage: str) -> None:
        """Record resumption state."""
        self.state.resume_count += 1
        self.state.resumed_from_stage = from_stage
        self.state.status = "running"
        logger.info(f"[PipelineStateManager] Run '{self.state.run_id}' resumed from stage '{from_stage}' (resume_count={self.state.resume_count})")

    def register_intermediate_outputs(self, refs: list[ArtifactReference]) -> None:
        """Register run-dedicated intermediate artifacts for lifecycle tracking & cleanup."""
        existing_uris = {r.uri for r in self.state.intermediate_outputs}
        for ref in refs:
            if ref.uri not in existing_uris:
                self.state.intermediate_outputs.append(ref)
                existing_uris.add(ref.uri)

    def mark_cleanup_pending(self) -> None:
        self.state.cleanup_status = "cleanup_pending"

    def mark_cleaned(self) -> None:
        self.state.cleanup_status = "cleaned"

    def mark_cleanup_failed(self, error_code: str, error_message: str) -> None:
        self.state.cleanup_status = "cleanup_failed"
        err = PipelineError(
            code=error_code,
            message=error_message,
            stage="intermediate_cleanup",
            details=[],
            retryable=False,
            attempt=1,
            occurred_at=now_utc_iso(),
        )
        self.state.errors.append(err)

    def record_predictions(
        self,
        results: list[InternalModelPredictionResult],
    ) -> None:
        self.state.prediction_results = results

    def record_prediction_delivery(self, status: Literal["not_required", "pending", "sent", "failed"]) -> None:
        self.state.prediction_delivery_status = status

    def finish_run(
        self,
        final_status: Literal["succeeded", "succeeded_with_cleanup_warning", "partially_succeeded", "failed"],
    ) -> None:
        self.state.status = final_status
        self.state.current_stage = None
        self.state.finished_at = now_utc_iso()

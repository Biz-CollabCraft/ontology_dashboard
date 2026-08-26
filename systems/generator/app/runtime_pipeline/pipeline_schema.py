"""Pydantic schemas and dataclasses for the Generator Runtime Prediction Pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactReference(BaseModel):
    """Reference to an atomically published file asset."""
    model_config = ConfigDict(extra="forbid")

    uri: str = Field(..., description="Logical relative or absolute URI to the artifact")
    sha256: str = Field(..., description="SHA-256 checksum of the artifact payload")
    role: str = Field("generic_artifact", description="Role or purpose of this artifact reference")
    size_bytes: Optional[int] = Field(None, description="Size in bytes")


class PipelineError(BaseModel):
    """Structured error information with stage context and retryability."""
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    stage: str = Field(..., description="Pipeline stage where error occurred")
    details: list[dict[str, Any]] = Field(default_factory=list, description="Diagnostic error details")
    retryable: bool = Field(False, description="Whether this error is retryable")
    attempt: int = Field(1, description="Attempt number when error occurred")
    occurred_at: str = Field(default_factory=now_utc_iso, description="ISO timestamp")


class StageState(BaseModel):
    """Execution state of an individual pipeline stage."""
    model_config = ConfigDict(extra="forbid")

    stage_name: str = Field(..., description="Name of the stage")
    status: Literal["pending", "running", "succeeded", "failed", "skipped"] = Field(
        "pending", description="Stage execution status"
    )
    attempt: int = Field(1, ge=1, description="Attempt count")
    started_at: Optional[str] = Field(None, description="ISO start timestamp")
    finished_at: Optional[str] = Field(None, description="ISO finish timestamp")
    input_refs: list[ArtifactReference] = Field(default_factory=list, description="Input artifact references")
    output_refs: list[ArtifactReference] = Field(default_factory=list, description="Output artifact references")
    error_code: Optional[str] = Field(None, description="Error code if failed")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    retryable: Optional[bool] = Field(None, description="Whether failed stage is retryable")


class RuntimeFeatureRowMetadata(BaseModel):
    """Row metadata mapping each feature matrix row to equipment and timestamp."""
    model_config = ConfigDict(extra="forbid")

    row_index: int = Field(..., ge=0, description="Row index in feature matrix")
    asset_id: str = Field(..., description="Target asset/equipment identifier")
    observed_at: str = Field(..., description="Observation timestamp in UTC ISO format")


class ModelPredictionResult(BaseModel):
    """Inference result payload for a single model in equipment batch."""
    model_config = ConfigDict(extra="forbid")

    model_version: str = Field(..., description="Published model artifact version")
    status: Literal["succeeded", "failed", "unknown"] = Field("succeeded", description="Model evaluation status")
    observed_at: str = Field(..., description="Observation timestamp in UTC ISO format")
    score_type: Optional[str] = Field("positive_class_probability", description="Type of score, e.g. positive_class_probability")
    score_source: Optional[Literal["predict_proba", "decision_function_compat", "predict_compat"]] = Field(
        "predict_proba", description="Inference method source"
    )
    score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Predicted numeric score/probability")
    artifact_ref: Optional[ArtifactReference] = Field(None, description="Reference to Model Artifact")
    feature_ref: Optional[ArtifactReference] = Field(None, description="Reference to Runtime Feature bundle")
    error_code: Optional[str] = Field(None, description="Error code if model inference failed")
    error_message: Optional[str] = Field(None, description="Error message if model inference failed")


class InternalModelPredictionResult(BaseModel):
    """Internal model inference result containing asset_id and model_id for orchestration."""
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(..., description="Target equipment identifier")
    model_id: str = Field(..., description="Unique model identifier, e.g. pdm-lightgbm")
    model_version: str = Field(..., description="Published model artifact version")
    status: Literal["succeeded", "failed", "unknown"] = Field("succeeded", description="Model evaluation status")
    observed_at: str = Field(..., description="Observation timestamp in UTC ISO format")
    score_type: Optional[str] = Field("positive_class_probability", description="Type of score, e.g. positive_class_probability")
    score_source: Optional[Literal["predict_proba", "decision_function_compat", "predict_compat"]] = Field(
        "predict_proba", description="Inference method source"
    )
    score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Predicted numeric score/probability")
    artifact_ref: Optional[ArtifactReference] = Field(None, description="Reference to Model Artifact")
    feature_ref: Optional[ArtifactReference] = Field(None, description="Reference to Runtime Feature bundle")
    error_code: Optional[str] = Field(None, description="Error code if model inference failed")
    error_message: Optional[str] = Field(None, description="Error message if model inference failed")

    def to_payload_result(self) -> ModelPredictionResult:
        """Convert internal result to contract payload result (without redundant asset_id/model_id)."""
        return ModelPredictionResult(
            model_version=self.model_version,
            status=self.status,
            observed_at=self.observed_at,
            score_type=self.score_type,
            score_source=self.score_source,
            score=self.score,
            artifact_ref=self.artifact_ref,
            feature_ref=self.feature_ref,
            error_code=self.error_code,
            error_message=self.error_message,
        )


class PredictionDeliveryEventState(BaseModel):
    """Delivery state tracking for an individual Prediction Result Batch delivery event."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., description="Unique event identifier")
    asset_id: str = Field(..., description="Target equipment identifier")
    status: Literal["pending", "sending", "retry_wait", "sent", "failed"] = Field(
        "pending", description="Event delivery status"
    )
    attempt: int = Field(0, ge=0, description="Attempt count")
    max_attempts: int = Field(5, ge=1, description="Max delivery attempts")
    next_retry_at: Optional[str] = Field(None, description="ISO timestamp for next retry")
    last_error_code: Optional[str] = Field(None, description="Last error code")
    last_error_message: Optional[str] = Field(None, description="Last error message")
    updated_at: str = Field(default_factory=now_utc_iso, description="ISO update timestamp")


class PipelineCheckpoint(BaseModel):
    """State checkpoint recorded at end of each stage for resumption."""
    model_config = ConfigDict(extra="forbid")

    checkpoint_version: str = Field("generator-runtime-checkpoint-v1", description="Checkpoint schema version")
    run_id: str = Field(..., description="Run identifier")
    job_id: str = Field(..., description="Job identifier")
    source_identity: str = Field(..., description="Source identity SHA-256")
    source_uri: str = Field(..., description="Source file relative or logical URI")
    source_checksum: str = Field(..., description="Source file SHA-256")
    source_size_bytes: Optional[int] = Field(None, description="Source file size in bytes")
    dataset_id: str = Field(..., description="Dataset ID")
    dataset_version: str = Field(..., description="Dataset version")
    pipeline_contract_version: str = Field("generator-prediction-result-v1", description="Pipeline contract version")
    last_completed_stage: Optional[Literal[
        "source_validated",
        "preprocessing",
        "runtime_feature",
        "runtime_prediction",
        "batch_building",
        "prediction_delivery"
    ]] = Field(None, description="Last completed stage name")
    next_stage: Optional[Literal[
        "preprocessing",
        "runtime_feature",
        "runtime_prediction",
        "batch_building",
        "prediction_delivery",
        "completed"
    ]] = Field(None, description="Next stage to execute")
    status: Literal["resumable", "debug_only", "cleanup_pending", "completed", "invalidated"] = Field(
        "resumable", description="Checkpoint lifecycle status"
    )
    created_at: str = Field(default_factory=now_utc_iso, description="Created timestamp")
    updated_at: str = Field(default_factory=now_utc_iso, description="Updated timestamp")
    stage_outputs: dict[str, list[ArtifactReference]] = Field(default_factory=dict, description="Validated output artifact references by stage")
    model_snapshot: dict[str, dict[str, Any]] = Field(default_factory=dict, description="Active model versions, manifest checksums and schemas")
    errors: list[PipelineError] = Field(default_factory=list, description="Historical error list")


class PipelineRunState(BaseModel):
    """Complete execution record for a single pipeline run."""
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(..., description="Unique run identifier (UUID/timestamp based)")
    job_id: str = Field(..., description="Queue job identifier")
    status: Literal[
        "pending",
        "queued",
        "running",
        "succeeded",
        "succeeded_with_cleanup_warning",
        "partially_succeeded",
        "failed",
    ] = Field("pending", description="Overall pipeline run status")
    current_stage: Optional[str] = Field(None, description="Currently active stage")
    source_ref: ArtifactReference = Field(..., description="Source observation protocol file reference")
    stages: dict[str, StageState] = Field(default_factory=dict, description="Stage execution map")
    prediction_results: list[InternalModelPredictionResult] = Field(
        default_factory=list, description="Array of prediction results for all registered models across equipments"
    )
    prediction_delivery_status: Optional[Literal["not_required", "pending", "sent", "failed"]] = Field(
        None, description="Prediction delivery dispatch status"
    )
    prediction_event_ids: list[str] = Field(
        default_factory=list, description="List of generated prediction batch event IDs"
    )
    prediction_events: list[PredictionDeliveryEventState] = Field(
        default_factory=list, description="List of per-event delivery states"
    )
    started_at: Optional[str] = Field(None, description="ISO start timestamp")
    finished_at: Optional[str] = Field(None, description="ISO finish timestamp")
    errors: list[PipelineError] = Field(default_factory=list, description="List of errors occurred")

    # Resumption, checkpoint, and intermediate cleanup lifecycle fields
    last_completed_stage: Optional[str] = Field(None, description="Last completed stage name")
    next_stage: Optional[str] = Field(None, description="Next stage to execute")
    resume_count: int = Field(0, ge=0, description="Number of times this run was resumed")
    resumed_from_stage: Optional[str] = Field(None, description="Stage from which this execution resumed")
    checkpoint_status: Optional[Literal["resumable", "debug_only", "cleanup_pending", "completed", "invalidated"]] = Field(
        None, description="Checkpoint lifecycle status"
    )
    cleanup_status: Optional[Literal["not_started", "cleanup_pending", "cleaned", "cleanup_failed", "cleanup_skipped"]] = Field(
        "not_started", description="Intermediate output cleanup status"
    )
    intermediate_outputs: list[ArtifactReference] = Field(
        default_factory=list, description="List of run-dedicated intermediate artifacts subject to cleanup"
    )
    checkpoint: Optional[PipelineCheckpoint] = Field(None, description="Current persistent stage checkpoint")


def compute_source_identity(
    source_checksum: str,
    dataset_id: str = "canonical-ai4i-v1",
    dataset_version: str = "canonical-ai4i-physics-v3.1",
    pipeline_contract_version: str = "generator-prediction-result-v1",
) -> str:
    """Compute stable, version-aware deduplication identity for source input."""
    import hashlib
    clean_checksum = source_checksum.strip().lower()
    clean_ds = dataset_id.strip()
    clean_ver = dataset_version.strip()
    clean_contract = pipeline_contract_version.strip()
    key = f"{clean_checksum}:{clean_ds}:{clean_ver}:{clean_contract}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class PipelineQueueItem(BaseModel):
    """Item managed in persistent FIFO queue."""
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., description="Unique job identifier")
    source_uri: str = Field(..., description="Source file relative or absolute URI")
    source_checksum: str = Field(..., description="Source file SHA-256 checksum")
    source_identity: Optional[str] = Field(None, description="SHA-256 deduplication identity of input and contract versions")
    size_bytes: Optional[int] = Field(None, description="File size in bytes at detection time")
    dataset_id: str = Field("canonical-ai4i-v1", description="Dataset identifier")
    dataset_version: str = Field("canonical-ai4i-physics-v3.1", description="Dataset version")
    pipeline_contract_version: str = Field("generator-prediction-result-v1", description="Pipeline contract version")
    detected_at: str = Field(default_factory=now_utc_iso, description="ISO detection timestamp")
    sequence: int = Field(1, ge=1, description="FIFO sequence number")
    attempt: int = Field(1, ge=1, description="Execution attempt number")
    retry_of_job_id: Optional[str] = Field(None, description="Previous failed job ID if re-enqueued")
    status: Literal[
        "detected",
        "queued",
        "running",
        "succeeded",
        "retry_wait",
        "failed",
        "dead_letter",
    ] = Field("queued", description="Queue item state")
    error_code: Optional[str] = Field(None, description="Error code if item failed")


class SourceLineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_uri: str
    source_checksum: str
    pipeline_contract_version: str = "generator-prediction-result-v1"


class PredictionResultBatchPayload(BaseModel):
    """Prediction Result Batch payload sent per equipment across models."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., description="Unique event identifier (Idempotency Key)")
    run_id: str = Field(..., description="Associated pipeline run ID")
    job_id: str = Field(..., description="Associated queue job ID")
    asset_id: str = Field(..., description="Target equipment identifier")
    observed_at: str = Field(..., description="Observation timestamp in UTC ISO format")
    generated_at: str = Field(default_factory=now_utc_iso, description="Generation timestamp")
    dataset_id: str = Field(..., description="Dataset identifier")
    dataset_version: str = Field(..., description="Dataset version")
    model_results: dict[str, ModelPredictionResult] = Field(
        ..., description="Map of model_id to model prediction results for this equipment"
    )
    source_lineage: SourceLineage = Field(..., description="Input lineage traceability")
    sensor_data_ref: Optional[dict[str, Any]] = Field(None, description="Sensor data reference")


class PredictionOutboxItem(BaseModel):
    """Item managed in prediction delivery outbox."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., description="Unique event identifier")
    run_id: str = Field(..., description="Associated pipeline run ID")
    job_id: str = Field(..., description="Associated queue job ID")
    asset_id: str = Field(..., description="Target equipment identifier")
    status: Literal["pending", "sending", "sent", "retry_wait", "failed"] = Field(
        "pending", description="Outbox delivery status"
    )
    attempt: int = Field(0, ge=0, description="Attempt count")
    max_attempts: int = Field(5, ge=1, description="Max delivery attempts")
    next_retry_at: Optional[str] = Field(None, description="ISO timestamp for next retry")
    last_error_code: Optional[str] = Field(None, description="Last error code if failed")
    last_error_message: Optional[str] = Field(None, description="Last error message if failed")
    created_at: str = Field(default_factory=now_utc_iso, description="Created timestamp")
    updated_at: str = Field(default_factory=now_utc_iso, description="Updated timestamp")
    payload: PredictionResultBatchPayload = Field(..., description="Batch payload to deliver")

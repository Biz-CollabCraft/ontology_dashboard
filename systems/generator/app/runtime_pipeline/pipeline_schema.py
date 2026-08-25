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
    """Inference result for a single registered model for a specific equipment."""
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(..., description="Target equipment identifier")
    model_id: str = Field(..., description="Unique model identifier, e.g. pdm-lightgbm")
    model_version: str = Field(..., description="Published model artifact version")
    status: Literal["succeeded", "failed", "unknown"] = Field("succeeded", description="Model evaluation status")
    prediction: Literal["normal", "anomaly", "unknown", "failed"] = Field("normal", description="Prediction class")
    probability: Optional[float] = Field(None, ge=0.0, le=1.0, description="Predicted anomaly probability score")
    threshold: float = Field(0.5, ge=0.0, le=1.0, description="Decision threshold")
    is_anomaly: Optional[bool] = Field(None, description="Whether prediction is classified as anomaly")
    predicted_at: str = Field(default_factory=now_utc_iso, description="ISO timestamp of prediction")
    artifact_ref: Optional[ArtifactReference] = Field(None, description="Reference to Model Artifact")
    feature_ref: Optional[ArtifactReference] = Field(None, description="Reference to Runtime Feature bundle")
    error_code: Optional[str] = Field(None, description="Error code if model inference failed")
    error_message: Optional[str] = Field(None, description="Error message if model inference failed")


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
        "partially_succeeded",
        "failed",
    ] = Field("pending", description="Overall pipeline run status")
    current_stage: Optional[str] = Field(None, description="Currently active stage")
    source_ref: ArtifactReference = Field(..., description="Source observation protocol file reference")
    stages: dict[str, StageState] = Field(default_factory=dict, description="Stage execution map")
    prediction_results: list[ModelPredictionResult] = Field(
        default_factory=list, description="Array of predictions for all registered models across equipments"
    )
    anomaly_detected: Optional[bool] = Field(None, description="Whether any model detected an anomaly")
    notification_status: Optional[Literal["not_required", "pending", "sent", "failed"]] = Field(
        None, description="Notification dispatch status"
    )
    notification_event_ids: list[str] = Field(
        default_factory=list, description="List of generated anomaly signal event IDs"
    )
    started_at: Optional[str] = Field(None, description="ISO start timestamp")
    finished_at: Optional[str] = Field(None, description="ISO finish timestamp")
    errors: list[PipelineError] = Field(default_factory=list, description="List of errors occurred")


class PipelineQueueItem(BaseModel):
    """Item managed in persistent FIFO queue."""
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(..., description="Unique job identifier")
    source_uri: str = Field(..., description="Source file relative or absolute URI")
    source_checksum: str = Field(..., description="Source file SHA-256 checksum")
    dataset_id: str = Field("canonical-ai4i-v1", description="Dataset identifier")
    dataset_version: str = Field("canonical-ai4i-physics-v3.1", description="Dataset version")
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
    pipeline_contract_version: str = "1.0"


class AnomalySignalPayload(BaseModel):
    """External anomaly signal payload sent to receiving system per anomalous equipment."""
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., description="Unique event identifier (Idempotency Key)")
    run_id: str = Field(..., description="Associated pipeline run ID")
    job_id: str = Field(..., description="Associated queue job ID")
    asset_id: str = Field(..., description="Target equipment identifier")
    detected_at: str = Field(default_factory=now_utc_iso, description="Detection timestamp")
    dataset_id: str = Field(..., description="Dataset identifier")
    dataset_version: str = Field(..., description="Dataset version")
    anomaly_detected: bool = Field(True, description="Always true when signal is dispatched")
    anomaly_models: list[str] = Field(default_factory=list, description="List of model IDs flagging anomaly")
    model_results: list[ModelPredictionResult] = Field(
        ..., min_length=1, description="Array of model prediction results for this equipment"
    )
    source_lineage: SourceLineage = Field(..., description="Input lineage traceability")
    sensor_data_ref: Optional[dict[str, Any]] = Field(None, description="Sensor data reference")
    feature_ref: Optional[dict[str, Any]] = Field(None, description="Runtime feature reference")


class NotificationOutboxItem(BaseModel):
    """Item managed in notification outbox."""
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
    payload: AnomalySignalPayload = Field(..., description="Signal payload to deliver")

"""Domain exception classes for the Generator Runtime Pipeline."""

from __future__ import annotations

from typing import Any, Optional


class PipelineBaseError(Exception):
    """Base exception for all pipeline domain errors."""

    status_code: int = 500
    code: str = "PIPELINE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[list[dict[str, Any]]] = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or []
        self.retryable = retryable


class PipelineAlreadyRunningError(PipelineBaseError):
    status_code = 409
    code = "PIPELINE_ALREADY_RUNNING"


class PipelineQueuePersistError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_QUEUE_PERSIST_FAILED"


class PipelineQueueItemInvalidError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_QUEUE_ITEM_INVALID"


class PipelineDuplicateInputError(PipelineBaseError):
    status_code = 409
    code = "PIPELINE_DUPLICATE_INPUT"


class PipelineStateTransitionInvalidError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_STATE_TRANSITION_INVALID"


class PipelineRecoveryError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_RECOVERY_FAILED"


class PipelineInputNotFoundError(PipelineBaseError):
    status_code = 404
    code = "PIPELINE_INPUT_NOT_FOUND"


class PipelineInputNotReadyError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_INPUT_NOT_READY"


class PipelineInputChecksumMismatchError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_INPUT_CHECKSUM_MISMATCH"


class PipelinePreprocessingFailedError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_PREPROCESSING_FAILED"


class PipelineRuntimeFeatureFailedError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_RUNTIME_FEATURE_FAILED"


class PipelineHistoryInsufficientError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_HISTORY_INSUFFICIENT"


class PipelineFeatureSchemaMismatchError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_FEATURE_SCHEMA_MISMATCH"


class PipelineNoActiveModelError(PipelineBaseError):
    status_code = 503
    code = "PIPELINE_NO_ACTIVE_MODEL"


class PipelineModelArtifactInvalidError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_MODEL_ARTIFACT_INVALID"


class PipelineModelPredictionFailedError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_MODEL_PREDICTION_FAILED"


class PipelinePartialPredictionError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_PARTIAL_PREDICTION"


class PipelineAggregationFailedError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_AGGREGATION_FAILED"


class PipelineNotificationFailedError(PipelineBaseError):
    status_code = 502
    code = "PIPELINE_NOTIFICATION_FAILED"


class PipelineNotificationRetryExhaustedError(PipelineBaseError):
    status_code = 502
    code = "PIPELINE_NOTIFICATION_RETRY_EXHAUSTED"

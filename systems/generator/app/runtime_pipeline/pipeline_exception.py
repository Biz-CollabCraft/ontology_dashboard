"""Domain exception classes for the Generator Runtime Pipeline."""

from __future__ import annotations

from typing import Any, Optional


class PipelineBaseError(Exception):
    """Base exception for all pipeline domain errors."""

    status_code: int = 500
    code: str = "PIPELINE_ERROR"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[list[dict[str, Any]]] = None,
        retryable: Optional[bool] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or []
        if retryable is not None:
            self.retryable = retryable


# =====================================================================
# 1. Non-Retryable Errors (Fail Immediately)
# =====================================================================

class PipelinePathNotAllowedError(PipelineBaseError):
    status_code = 403
    code = "PIPELINE_PATH_NOT_ALLOWED"
    retryable = False


class PipelineQueueItemInvalidError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_QUEUE_ITEM_INVALID"
    retryable = False


class PipelineDuplicateInputError(PipelineBaseError):
    status_code = 409
    code = "PIPELINE_DUPLICATE_INPUT"
    retryable = False


class PipelineAlreadyRunningError(PipelineBaseError):
    status_code = 409
    code = "PIPELINE_ALREADY_RUNNING"
    retryable = False


class PipelineStateTransitionInvalidError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_STATE_TRANSITION_INVALID"
    retryable = False


class PipelineInputNotFoundError(PipelineBaseError):
    status_code = 404
    code = "PIPELINE_INPUT_NOT_FOUND"
    retryable = False


class PipelineInputNotReadyError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_INPUT_NOT_READY"
    retryable = False


class PipelineInputChecksumMismatchError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_INPUT_CHECKSUM_MISMATCH"
    retryable = False


class PipelineUnsupportedInputFormatError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_UNSUPPORTED_INPUT_FORMAT"
    retryable = False


class PipelineMappingNotImplementedError(PipelineBaseError):
    status_code = 501
    code = "PIPELINE_MAPPING_NOT_IMPLEMENTED"
    retryable = False


class PipelineAssetIdMissingError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_ASSET_ID_MISSING"
    retryable = False


class PipelinePreprocessingFailedError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_PREPROCESSING_FAILED"
    retryable = False


class PipelineRuntimeFeatureFailedError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_RUNTIME_FEATURE_FAILED"
    retryable = False


class PipelineHistoryInsufficientError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_HISTORY_INSUFFICIENT"
    retryable = False


class PipelineFeatureSchemaMismatchError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_FEATURE_SCHEMA_MISMATCH"
    retryable = False


class PipelineNoActiveModelError(PipelineBaseError):
    status_code = 503
    code = "PIPELINE_NO_ACTIVE_MODEL"
    retryable = False


class PipelineModelArtifactInvalidError(PipelineBaseError):
    status_code = 422
    code = "PIPELINE_MODEL_ARTIFACT_INVALID"
    retryable = False


class PipelineModelPredictionFailedError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_MODEL_PREDICTION_FAILED"
    retryable = False


class PipelinePartialPredictionError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_PARTIAL_PREDICTION"
    retryable = False


class PipelineAggregationFailedError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_AGGREGATION_FAILED"
    retryable = False


class PipelineJobNotFailedError(PipelineBaseError):
    status_code = 400
    code = "PIPELINE_JOB_NOT_FAILED"
    retryable = False


class PipelineNotImplementedError(PipelineBaseError):
    status_code = 501
    code = "PIPELINE_NOT_IMPLEMENTED"
    retryable = False


# =====================================================================
# 2. Retryable Errors (Max 5 Attempts with Exponential Backoff)
# =====================================================================

class PipelineQueuePersistError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_QUEUE_PERSIST_FAILED"
    retryable = True


class PipelineTemporaryFileIoError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_TEMPORARY_FILE_IO_FAILED"
    retryable = True


class PipelineModelArtifactBusyError(PipelineBaseError):
    status_code = 503
    code = "PIPELINE_MODEL_ARTIFACT_BUSY"
    retryable = True


class PipelineRecoveryError(PipelineBaseError):
    status_code = 500
    code = "PIPELINE_RECOVERY_FAILED"
    retryable = True


class PipelineNotificationFailedError(PipelineBaseError):
    status_code = 502
    code = "PIPELINE_NOTIFICATION_FAILED"
    retryable = True


class PipelineNotificationTimeoutError(PipelineBaseError):
    status_code = 504
    code = "PIPELINE_NOTIFICATION_TIMEOUT"
    retryable = True


class PipelineNotificationServerError(PipelineBaseError):
    status_code = 502
    code = "PIPELINE_NOTIFICATION_SERVER_ERROR"
    retryable = True


class PipelineNotificationRetryExhaustedError(PipelineBaseError):
    status_code = 502
    code = "PIPELINE_NOTIFICATION_RETRY_EXHAUSTED"
    retryable = False

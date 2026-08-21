"""Domain exceptions for feature and label generation domain."""

from __future__ import annotations
from typing import Any


class FeatureError(ValueError):
    """Base exception for all feature domain errors."""

    def __init__(
        self,
        message: str,
        code: str = "FEATURE_ERROR",
        status_code: int = 500,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or []


class FeatureInputNotFoundError(FeatureError):
    """Raised when an input artifact (Observation, Failure, Plan, Mapping, Schemas) is missing."""

    def __init__(
        self,
        message: str = "요청한 입력 아티팩트를 찾을 수 없습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code="FEATURE_INPUT_NOT_FOUND", status_code=404, details=details)


class FeatureContractError(FeatureError):
    """Raised when input parameters, paths, or data contracts are violated."""

    def __init__(
        self,
        message: str = "Feature 계약 검증에 실패했습니다.",
        code: str = "FEATURE_CONTRACT_ERROR",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class FeatureSchemaMismatchError(FeatureError):
    """Raised when DataFrame columns do not match Feature Schema or Label Schema definitions."""

    def __init__(
        self,
        message: str = "Feature 또는 Label 스키마 정의와 일치하지 않습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code="FEATURE_SCHEMA_MISMATCH_ERROR", status_code=422, details=details)


class FeatureLabelAlignmentError(FeatureError):
    """Raised when failure labels, timestamps, or equipment IDs cannot be aligned with telemetry observations."""

    def __init__(
        self,
        message: str = "Telemetry 관측치와 Failure 라벨 간의 식별자 또는 시간 정렬에 실패했습니다.",
        code: str = "FEATURE_LABEL_ALIGNMENT_ERROR",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class FeatureDatasetIntegrityError(FeatureError):
    """Raised when existing or saved feature dataset files fail checksum, shape, or format integrity checks."""

    def __init__(
        self,
        message: str = "Feature Dataset Bundle 무결성 검증에 실패했습니다.",
        code: str = "FEATURE_DATASET_INTEGRITY_ERROR",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class FeaturePublishConflictError(FeatureError):
    """Raised when attempting to publish a feature bundle with a conflicting contract or mismatched version."""

    def __init__(
        self,
        message: str = "동일한 Feature Dataset 버전의 기존 아티팩트와 충돌이 발생했습니다.",
        code: str = "FEATURE_PUBLISH_CONFLICT",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=409, details=details)


class FeaturePublishError(FeatureError):
    """Raised when atomic publishing or disk writing fails."""

    def __init__(
        self,
        message: str = "Feature Dataset Bundle 원자적 발행에 실패했습니다.",
        code: str = "FEATURE_PUBLISH_ERROR",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=500, details=details)


class InsufficientTrainingDataError(FeatureError):
    """Raised when the resulting feature matrix has 0 valid rows for training."""

    def __init__(
        self,
        message: str = "학습에 유효한 데이터 행이 0건입니다.",
        code: str = "INSUFFICIENT_TRAINING_DATA",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


# Compatibility aliases
NpyValidationError = FeatureContractError
NpyPublishError = FeaturePublishError
FailureDataNotReadyError = FeatureInputNotFoundError
LabelContractInvalidError = FeatureLabelAlignmentError
LabelAnchorNotFoundError = FeatureLabelAlignmentError
FeatureConflictError = FeaturePublishConflictError

"""Training domain exceptions for Generator API conforming to canonical error contract."""

from __future__ import annotations
from typing import Any


class TrainingError(ValueError):
    """Base exception for all Training domain errors."""

    def __init__(
        self,
        message: str = "모델 학습 도메인 처리 중 오류가 발생했습니다.",
        code: str = "TRAINING_ERROR",
        status_code: int = 400,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or []


class FeatureDatasetNotFoundError(TrainingError):
    def __init__(
        self,
        message: str = "지정한 Feature Dataset Bundle을 찾을 수 없습니다.",
        code: str = "FEATURE_DATASET_NOT_FOUND",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=404, details=details)


class ModelNotRegisteredError(TrainingError):
    def __init__(
        self,
        message: str = "지원하지 않는 모델 알고리즘입니다.",
        code: str = "MODEL_NOT_REGISTERED",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=404, details=details)


class TrainingAlreadyRunningError(TrainingError):
    def __init__(
        self,
        message: str = "모델 학습이 이미 진행 중입니다.",
        code: str = "TRAINING_ALREADY_RUNNING",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=409, details=details)


class ModelArtifactConflictError(TrainingError):
    def __init__(
        self,
        message: str = "동일한 Model Artifact 버전이 이미 존재합니다.",
        code: str = "MODEL_ARTIFACT_CONFLICT",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=409, details=details)


class FeatureDatasetIntegrityError(TrainingError):
    def __init__(
        self,
        message: str = "Feature Dataset Bundle 파일 또는 무결성 검증에 실패했습니다.",
        code: str = "FEATURE_DATASET_INTEGRITY_ERROR",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class FeatureSchemaMismatchError(TrainingError):
    def __init__(
        self,
        message: str = "Feature Schema 버전 또는 allowlist 검증에 실패했습니다.",
        code: str = "FEATURE_SCHEMA_MISMATCH",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class LabelSchemaMismatchError(TrainingError):
    def __init__(
        self,
        message: str = "Label Schema 버전 또는 계약 검증에 실패했습니다.",
        code: str = "LABEL_SCHEMA_MISMATCH",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class TrainingSplitMetadataMissingError(TrainingError):
    def __init__(
        self,
        message: str = "시간순 데이터 분할(asset_time_split)을 위한 메타데이터가 누락되었습니다.",
        code: str = "TRAINING_SPLIT_METADATA_MISSING",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class InsufficientTrainingDataError(TrainingError):
    def __init__(
        self,
        message: str = "학습에 필요한 유효 피처 또는 클래스(Positive/Negative) 표본이 부족합니다.",
        code: str = "INSUFFICIENT_TRAINING_DATA",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class ModelTrainingFailedError(TrainingError):
    def __init__(
        self,
        message: str = "모델 학습 실행에 실패했습니다.",
        code: str = "MODEL_TRAINING_FAILED",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=500, details=details)


class ModelArtifactPublishFailedError(TrainingError):
    def __init__(
        self,
        message: str = "Model Artifact 불변 패키지 발행 및 검증에 실패했습니다.",
        code: str = "MODEL_ARTIFACT_PUBLISH_FAILED",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=500, details=details)

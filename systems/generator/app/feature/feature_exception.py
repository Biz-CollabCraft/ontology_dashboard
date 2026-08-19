"""Domain exceptions for feature, label, and NPY generation processing."""

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


class ExtractionPlanNotReadyError(FeatureError):
    """Raised when the required Extraction Plan does not exist in repository."""

    def __init__(
        self,
        message: str = "요청한 Extraction Plan이 없습니다. 먼저 POST /extraction을 실행해 주세요.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_PLAN_NOT_READY",
            status_code=404,
            details=details,
        )


class ExtractionPlanVersionMismatchError(FeatureError):
    """Raised when the requested plan version does not match the stored plan."""

    def __init__(
        self,
        message: str = "요청한 Extraction Plan 버전과 실제 저장된 Plan 버전이 일치하지 않습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_PLAN_VERSION_MISMATCH",
            status_code=422,
            details=details,
        )


class OntologyMappingNotReadyError(FeatureError):
    """Raised when the required Ontology Mapping does not exist in repository."""

    def __init__(
        self,
        message: str = "요청한 Ontology Mapping이 없습니다. 먼저 POST /extraction을 실행해 주세요.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="ONTOLOGY_MAPPING_NOT_READY",
            status_code=404,
            details=details,
        )


class OntologyMappingVersionMismatchError(FeatureError):
    """Raised when the requested mapping version does not match the stored mapping."""

    def __init__(
        self,
        message: str = "요청한 Ontology Mapping 버전과 실제 저장된 Mapping 버전이 일치하지 않습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="ONTOLOGY_MAPPING_VERSION_MISMATCH",
            status_code=422,
            details=details,
        )


class FailureDataNotReadyError(FeatureError):
    """Raised when failure events dataset or label history cannot be found."""

    def __init__(
        self,
        message: str = "학습에 필요한 고장 이력(Failure Data)을 찾을 수 없습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="FAILURE_DATA_NOT_READY",
            status_code=404,
            details=details,
        )


class LabelContractInvalidError(FeatureError):
    """Raised when label column values or format violate contract."""

    def __init__(
        self,
        message: str = "라벨 계약이 올바르지 않습니다 (label 컬럼 누락 또는 {0,1} 외 값).",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="LABEL_CONTRACT_INVALID",
            status_code=422,
            details=details,
        )


class LabelAnchorNotFoundError(FeatureError):
    """Raised when ID, timestamp, or failure anchor cannot be determined."""

    def __init__(
        self,
        message: str = "라벨 생성을 위한 ID, timestamp 또는 anchor(failure_point)를 결정할 수 없습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="LABEL_ANCHOR_NOT_FOUND",
            status_code=422,
            details=details,
        )


class FeatureBuildError(FeatureError):
    """Raised when time-series feature calculation fails."""

    def __init__(
        self,
        message: str = "시계열 피처 생성 중 오류가 발생했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="FEATURE_BUILD_ERROR",
            status_code=422,
            details=details,
        )


class LabelBuildError(FeatureError):
    """Raised when failure horizon labeling fails."""

    def __init__(
        self,
        message: str = "라벨링 생성 중 오류가 발생했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="LABEL_BUILD_ERROR",
            status_code=422,
            details=details,
        )


class FeatureSchemaMismatchError(FeatureError):
    """Raised when feature allowlist or schema version contract is violated."""

    def __init__(
        self,
        message: str = "Feature Schema 버전 또는 allowlist 검증에 실패했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="FEATURE_SCHEMA_MISMATCH",
            status_code=422,
            details=details,
        )


class InsufficientTrainingDataError(FeatureError):
    """Raised when rows, positive samples, or feature columns are insufficient."""

    def __init__(
        self,
        message: str = "학습에 필요한 유효 피처, 데이터 행 또는 positive 샘플이 부족합니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="INSUFFICIENT_TRAINING_DATA",
            status_code=422,
            details=details,
        )


class NpyBuildError(FeatureError):
    """Raised when NPY array conversion fails."""

    def __init__(
        self,
        message: str = "NPY 행렬 직렬화 중 오류가 발생했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="NPY_BUILD_ERROR",
            status_code=500,
            details=details,
        )


class NpyValidationError(FeatureError):
    """Raised when generated NPY arrays fail consistency checks."""

    def __init__(
        self,
        message: str = "생성된 NPY 행렬 및 메타데이터 유효성 검증에 실패했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="NPY_VALIDATION_ERROR",
            status_code=422,
            details=details,
        )


class NpyPublishError(FeatureError):
    """Raised when atomic publishing of NPY artifacts fails."""

    def __init__(
        self,
        message: str = "NPY 산출물 저장 및 발행에 실패했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="NPY_PUBLISH_ERROR",
            status_code=500,
            details=details,
        )


class FeatureConflictError(FeatureError):
    """Raised when duplicate feature dataset version conflict occurs."""

    def __init__(
        self,
        message: str = "동일한 Feature 버전이 이미 존재하거나 충돌이 발생했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="FEATURE_CONFLICT",
            status_code=409,
            details=details,
        )

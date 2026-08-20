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
    def __init__(self, message: str = "요청한 Extraction Plan이 없습니다. 먼저 POST /extraction을 실행해 주세요.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_NOT_READY", status_code=404, details=details)


class ExtractionPlanIntegrityError(FeatureError):
    def __init__(self, message: str = "Extraction Plan의 내용 해시와 요청된 버전이 일치하지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_INTEGRITY_ERROR", status_code=422, details=details)


class ExtractionPlanContractInvalidError(FeatureError):
    def __init__(self, message: str = "Extraction Plan 파일이 손상되었거나 계약 형식이 올바르지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_CONTRACT_INVALID", status_code=422, details=details)


class ExtractionPlanVersionMismatchError(FeatureError):
    def __init__(self, message: str = "요청한 Extraction Plan 버전과 실제 저장된 Plan 버전이 일치하지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_VERSION_MISMATCH", status_code=422, details=details)


class OntologyMappingNotReadyError(FeatureError):
    def __init__(self, message: str = "요청한 Ontology Mapping이 없습니다. 먼저 POST /extraction을 실행해 주세요.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="ONTOLOGY_MAPPING_NOT_READY", status_code=404, details=details)


class OntologyMappingIntegrityError(FeatureError):
    def __init__(self, message: str = "Ontology Mapping의 내용 해시와 요청된 버전이 일치하지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="ONTOLOGY_MAPPING_INTEGRITY_ERROR", status_code=422, details=details)


class OntologyMappingContractInvalidError(FeatureError):
    def __init__(self, message: str = "Ontology Mapping 파일이 손상되었거나 계약 형식이 올바르지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="ONTOLOGY_MAPPING_CONTRACT_INVALID", status_code=422, details=details)


class OntologyMappingVersionMismatchError(FeatureError):
    def __init__(self, message: str = "요청한 Ontology Mapping 버전과 실제 저장된 Mapping 버전이 일치하지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="ONTOLOGY_MAPPING_VERSION_MISMATCH", status_code=422, details=details)


class FailureDataNotReadyError(FeatureError):
    def __init__(self, message: str = "학습에 필요한 고장 이력(Failure Data)을 찾을 수 없습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="FAILURE_DATA_NOT_READY", status_code=404, details=details)


class LabelContractInvalidError(FeatureError):
    def __init__(self, message: str = "라벨 계약이 올바르지 않습니다 (label 컬럼 누락 또는 {0,1} 외 값).", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="LABEL_CONTRACT_INVALID", status_code=422, details=details)


class LabelAnchorNotFoundError(FeatureError):
    def __init__(self, message: str = "라벨 생성을 위한 ID, timestamp 또는 anchor(failure_point)를 결정할 수 없습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="LABEL_ANCHOR_NOT_FOUND", status_code=422, details=details)


class FeatureBuildError(FeatureError):
    def __init__(self, message: str = "시계열 피처 생성 중 오류가 발생했습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="FEATURE_BUILD_ERROR", status_code=422, details=details)


class LabelBuildError(FeatureError):
    def __init__(self, message: str = "라벨링 생성 중 오류가 발생했습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="LABEL_BUILD_ERROR", status_code=422, details=details)


class FeatureSchemaMismatchError(FeatureError):
    def __init__(self, message: str = "Feature Schema 버전 또는 allowlist 검증에 실패했습니다.", code: str = "FEATURE_SCHEMA_MISMATCH", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class LabelSchemaMismatchError(FeatureError):
    def __init__(self, message: str = "Label Schema 버전 또는 계약 검증에 실패했습니다.", code: str = "LABEL_SCHEMA_MISMATCH", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class InsufficientTrainingDataError(FeatureError):
    def __init__(
        self,
        message: str = "학습에 필요한 유효 피처, 데이터 행 또는 positive 샘플이 부족합니다.",
        code: str = "INSUFFICIENT_POSITIVE_SAMPLES",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class NpyBuildError(FeatureError):
    def __init__(self, message: str = "NPY 행렬 직렬화 중 오류가 발생했습니다.", code: str = "NPY_BUILD_ERROR", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=500, details=details)


class NpyValidationError(FeatureError):
    def __init__(self, message: str = "생성된 NPY 행렬 및 메타데이터 유효성 검증에 실패했습니다.", code: str = "NPY_VALIDATION_ERROR", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class FeatureDatasetIntegrityError(FeatureError):
    def __init__(self, message: str = "기존 Feature Dataset 번들의 무결성 검증에 실패했습니다.", code: str = "FEATURE_DATASET_INTEGRITY_ERROR", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=422, details=details)


class NpyPublishError(FeatureError):
    def __init__(self, message: str = "NPY 산출물 저장 및 발행에 실패했습니다.", code: str = "NPY_PUBLISH_ERROR", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=500, details=details)


class FeatureConflictError(FeatureError):
    def __init__(self, message: str = "동일한 Feature 버전이 이미 존재하거나 충돌이 발생했습니다.", code: str = "FEATURE_DATASET_CONFLICT", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code=code, status_code=409, details=details)

"""Domain exceptions for dataset extraction, planning, and mapping processes."""

from __future__ import annotations
from typing import Any


class ExtractionError(ValueError):
    """Base exception for all extraction domain errors."""

    def __init__(
        self,
        message: str,
        code: str = "EXTRACTION_ERROR",
        status_code: int = 500,
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or []


class DatasetNotFoundError(ExtractionError):
    def __init__(self, message: str = "요청한 데이터셋을 찾을 수 없습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="DATASET_NOT_FOUND", status_code=404, details=details)


class DatasetContractError(ExtractionError):
    def __init__(self, message: str = "데이터셋 계약 형식이 올바르지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="DATASET_CONTRACT_ERROR", status_code=422, details=details)


class ExtractionRoleError(ExtractionError):
    def __init__(self, message: str = "Long-format 추출에 필요한 필수 역할 컬럼이 누락되었습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_ROLE_COLUMNS_MISSING", status_code=422, details=details)


class ExtractionPlanningError(ExtractionError):
    def __init__(self, message: str = "추출 계획 수립에 실패했습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLANNING_ERROR", status_code=500, details=details)


class ExtractionPlanValidationError(ExtractionError):
    def __init__(self, message: str = "생성된 추출 계획의 정합성 검증에 실패했습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_VALIDATION_ERROR", status_code=422, details=details)


class ExtractionPlanPublishError(ExtractionError):
    def __init__(self, message: str = "추출 계획 또는 온톨로지 매핑 저장에 실패했습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_PUBLISH_ERROR", status_code=500, details=details)


class ExtractionConflictError(ExtractionError):
    def __init__(self, message: str = "추출 계획 충돌이 발생했습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_CONFLICT", status_code=409, details=details)


class ExtractionPlanNotReadyError(ExtractionError):
    def __init__(self, message: str = "요청한 Extraction Plan이 없습니다. 먼저 POST /extraction을 실행해 주세요.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_NOT_READY", status_code=404, details=details)


class ExtractionPlanIntegrityError(ExtractionError):
    def __init__(self, message: str = "Extraction Plan의 내용 해시와 요청된 버전이 일치하지 않습니다 (무결성 위반).", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_INTEGRITY_ERROR", status_code=422, details=details)


class ExtractionPlanContractInvalidError(ExtractionError):
    def __init__(self, message: str = "Extraction Plan JSON 파일이 손상되었거나 계약 형식이 올바르지 않습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="EXTRACTION_PLAN_CONTRACT_INVALID", status_code=422, details=details)


class OntologyMappingNotReadyError(ExtractionError):
    def __init__(self, message: str = "요청한 Ontology Mapping이 없습니다. 먼저 POST /extraction을 실행해 주세요.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="ONTOLOGY_MAPPING_NOT_READY", status_code=404, details=details)


class OntologyMappingIntegrityError(ExtractionError):
    def __init__(self, message: str = "Ontology Mapping의 내용 해시와 요청된 버전이 일치하지 않습니다 (무결성 위반).", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="ONTOLOGY_MAPPING_INTEGRITY_ERROR", status_code=422, details=details)


class OntologyMappingContractInvalidError(ExtractionError):
    def __init__(self, message: str = "Ontology Mapping JSON 파일이 손상되었거나 스키마 규칙을 위반했습니다.", details: list[Any] | None = None) -> None:
        super().__init__(message=message, code="ONTOLOGY_MAPPING_CONTRACT_INVALID", status_code=422, details=details)

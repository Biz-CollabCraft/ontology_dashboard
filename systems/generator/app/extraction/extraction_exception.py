"""Domain exceptions for extraction processing."""

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
    """Raised when the specified dataset cannot be found."""

    def __init__(
        self,
        message: str = "지정한 데이터셋을 찾을 수 없습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code="DATASET_NOT_FOUND", status_code=404, details=details)


class DatasetContractError(ExtractionError):
    """Raised when the dataset structure violates minimum format/contract rules."""

    def __init__(
        self,
        message: str = "데이터셋 계약 검증에 실패했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(message=message, code="DATASET_CONTRACT_ERROR", status_code=422, details=details)


class ExtractionRoleError(ExtractionError):
    """Raised when long-format required role columns cannot be determined or are missing."""

    def __init__(
        self,
        message: str = "Long-format 추출에 필요한 컬럼 역할을 결정할 수 없습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_ROLE_COLUMNS_MISSING",
            status_code=422,
            details=details,
        )


class ExtractionPlanningError(ExtractionError):
    """Raised when extraction plan generation fails."""

    def __init__(
        self,
        message: str = "추출 계획 수립에 실패했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_PLANNING_ERROR",
            status_code=422,
            details=details,
        )


class ExtractionPlanValidationError(ExtractionError):
    """Raised when extraction plan validation fails against actual dataset columns."""

    def __init__(
        self,
        message: str = "추출 계획 검증에 실패했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_PLAN_VALIDATION_ERROR",
            status_code=422,
            details=details,
        )


class ExtractionPlanPublishError(ExtractionError):
    """Raised when atomic publishing of an extraction plan fails."""

    def __init__(
        self,
        message: str = "추출 계획 저장 및 발행에 실패했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_PLAN_PUBLISH_ERROR",
            status_code=500,
            details=details,
        )


class ExtractionConflictError(ExtractionError):
    """Raised when a concurrent conflicting extraction is in progress or duplicate version conflict."""

    def __init__(
        self,
        message: str = "동일한 추출 작업이 이미 진행 중이거나 충돌이 발생했습니다.",
        details: list[Any] | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="EXTRACTION_CONFLICT",
            status_code=409,
            details=details,
        )

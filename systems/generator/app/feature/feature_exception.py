"""Feature domain exceptions and error definitions."""

from __future__ import annotations

from typing import Any


class FeatureError(Exception):
    """Base exception for all Feature domain errors."""

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
    """Raised when an input dataset, plan, or schema is not found (404)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="FEATURE_INPUT_NOT_FOUND",
            status_code=404,
            details=details,
        )


class FeatureContractError(FeatureError):
    """Raised when request payload or path contracts are violated (422)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="FEATURE_CONTRACT_ERROR",
            status_code=422,
            details=details,
        )


class FeatureSchemaMismatchError(FeatureError):
    """Raised when Feature or Label Schema does not match data or requested horizons (422)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="FEATURE_SCHEMA_MISMATCH_ERROR",
            status_code=422,
            details=details,
        )


class FeatureLabelAlignmentError(FeatureError):
    """Raised when alignment between features, labels, and row metadata fails (422)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="FEATURE_LABEL_ALIGNMENT_ERROR",
            status_code=422,
            details=details,
        )


class FeatureDatasetIntegrityError(FeatureError):
    """Raised when an existing bundle is corrupted, incomplete, or fails integrity checks (422)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="FEATURE_DATASET_INTEGRITY_ERROR",
            status_code=422,
            details=details,
        )


class FeaturePublishConflictError(FeatureError):
    """Raised when target feature dataset version exists with a conflicting fingerprint (409)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="FEATURE_PUBLISH_CONFLICT",
            status_code=409,
            details=details,
        )


class FeaturePublishError(FeatureError):
    """Raised when atomic publishing or filesystem operations fail (500)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="FEATURE_PUBLISH_ERROR",
            status_code=500,
            details=details,
        )


class InsufficientTrainingDataError(FeatureError):
    """Raised when dataset has 0 rows or insufficient data for labeling/training (422)."""

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(
            message=message,
            code="INSUFFICIENT_TRAINING_DATA",
            status_code=422,
            details=details,
        )

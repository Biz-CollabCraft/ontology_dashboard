"""Training domain specific exceptions mapped to HTTP status codes."""

from __future__ import annotations

from typing import Any


class TrainingError(Exception):
    """Base exception for Generator Training domain."""

    status_code: int = 500
    code: str = "TRAINING_ERROR"

    def __init__(self, message: str, details: list[Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []


class TrainingInputNotFoundError(TrainingError):
    """Raised when requested Feature Dataset Bundle or configuration is not found."""

    status_code = 404
    code = "TRAINING_INPUT_NOT_FOUND"


class TrainingConfigNotFoundError(TrainingError):
    """Raised when requested training configuration version file is not found."""

    status_code = 404
    code = "TRAINING_CONFIG_NOT_FOUND"


class TrainingConfigValidationError(TrainingError):
    """Raised when training configuration file fails JSON Schema or identity validation."""

    status_code = 422
    code = "TRAINING_CONFIG_VALIDATION_ERROR"


class TrainingModelNotFoundError(TrainingError):
    """Raised when an unsupported base model is requested."""

    status_code = 404
    code = "TRAINING_MODEL_NOT_FOUND"


class TrainingContractError(TrainingError):
    """Raised when request payload or parameters violate contract rules."""

    status_code = 422
    code = "TRAINING_CONTRACT_ERROR"


class FeatureDatasetIntegrityError(TrainingError):
    """Raised when Feature Dataset Bundle is corrupted, checksum fails, or files missing."""

    status_code = 422
    code = "FEATURE_DATASET_INTEGRITY_ERROR"


class TrainingDatasetError(TrainingError):
    """Raised when dataset cannot be split, contains single class, or lacks sufficient rows."""

    status_code = 422
    code = "TRAINING_DATASET_ERROR"


class TrainingDependencyError(TrainingError):
    """Raised when required model library or optional dependency is missing."""

    status_code = 500
    code = "TRAINING_DEPENDENCY_ERROR"


class ModelArtifactConflictError(TrainingError):
    """Raised when attempting to overwrite an existing immutable model version."""

    status_code = 409
    code = "MODEL_ARTIFACT_CONFLICT"


class ModelArtifactValidationError(TrainingError):
    """Raised when generated Model Artifact package fails manifest or checksum validation."""

    status_code = 422
    code = "MODEL_ARTIFACT_VALIDATION_ERROR"


class ModelArtifactPublishError(TrainingError):
    """Raised when atomic publishing of Model Artifact package fails."""

    status_code = 500
    code = "MODEL_ARTIFACT_PUBLISH_ERROR"


class TrainingExecutionError(TrainingError):
    """Raised when model training algorithm fails during fit or evaluation."""

    status_code = 500
    code = "TRAINING_EXECUTION_ERROR"

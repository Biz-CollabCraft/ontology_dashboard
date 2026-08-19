"""Generator feature domain package."""

from systems.generator.app.feature.feature_schema import (
    FeatureRequest,
    FeatureResponse,
    FeatureOutputsPayload,
)
from systems.generator.app.feature.feature_exception import (
    FeatureError,
    ExtractionPlanNotReadyError,
    ExtractionPlanVersionMismatchError,
    ExtractionPlanIntegrityError,
    ExtractionPlanContractInvalidError,
    OntologyMappingNotReadyError,
    OntologyMappingVersionMismatchError,
    OntologyMappingIntegrityError,
    OntologyMappingContractInvalidError,
    FailureDataNotReadyError,
    LabelContractInvalidError,
    LabelAnchorNotFoundError,
    FeatureBuildError,
    LabelBuildError,
    FeatureSchemaMismatchError,
    InsufficientTrainingDataError,
    NpyBuildError,
    NpyValidationError,
    NpyPublishError,
    FeatureConflictError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.app.feature.feature_schema_provider import (
    FeatureSchemaProvider,
    FeatureSchemaDefinition,
)
from systems.generator.app.feature.feature_service import FeatureService
from systems.generator.app.feature.feature_router import router as feature_router

__all__ = [
    "FeatureRequest",
    "FeatureResponse",
    "FeatureOutputsPayload",
    "FeatureError",
    "ExtractionPlanNotReadyError",
    "ExtractionPlanVersionMismatchError",
    "ExtractionPlanIntegrityError",
    "ExtractionPlanContractInvalidError",
    "OntologyMappingNotReadyError",
    "OntologyMappingVersionMismatchError",
    "OntologyMappingIntegrityError",
    "OntologyMappingContractInvalidError",
    "FailureDataNotReadyError",
    "LabelContractInvalidError",
    "LabelAnchorNotFoundError",
    "FeatureBuildError",
    "LabelBuildError",
    "FeatureSchemaMismatchError",
    "InsufficientTrainingDataError",
    "NpyBuildError",
    "NpyValidationError",
    "NpyPublishError",
    "FeatureConflictError",
    "FeatureRepository",
    "FeatureSchemaProvider",
    "FeatureSchemaDefinition",
    "FeatureService",
    "feature_router",
]

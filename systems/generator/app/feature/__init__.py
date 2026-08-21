"""Feature domain public package for feature generation and immutable bundle publishing."""

from __future__ import annotations

from systems.generator.app.feature.feature_schema import (
    FeatureRequest,
    FeatureResponse,
    FeatureOutputsPayload,
)
from systems.generator.app.feature.feature_exception import (
    FeatureError,
    FeatureInputNotFoundError,
    FeatureContractError,
    FeatureSchemaMismatchError,
    FeatureLabelAlignmentError,
    FeatureDatasetIntegrityError,
    FeaturePublishConflictError,
    FeaturePublishError,
    InsufficientTrainingDataError,
)
from systems.generator.app.feature.feature_repository import FeatureRepository
from systems.generator.app.feature.feature_schema_provider import FeatureSchemaProvider, FeatureSchemaDefinition
from systems.generator.app.feature.label_schema_provider import LabelSchemaProvider, LabelSchemaDefinition
from systems.generator.app.feature.feature_service import FeatureService
from systems.generator.app.feature.feature_router import router as feature_router

__all__ = [
    "FeatureRequest",
    "FeatureResponse",
    "FeatureOutputsPayload",
    "FeatureError",
    "FeatureInputNotFoundError",
    "FeatureContractError",
    "FeatureSchemaMismatchError",
    "FeatureLabelAlignmentError",
    "FeatureDatasetIntegrityError",
    "FeaturePublishConflictError",
    "FeaturePublishError",
    "InsufficientTrainingDataError",
    "FeatureRepository",
    "FeatureSchemaProvider",
    "FeatureSchemaDefinition",
    "LabelSchemaProvider",
    "LabelSchemaDefinition",
    "FeatureService",
    "feature_router",
]

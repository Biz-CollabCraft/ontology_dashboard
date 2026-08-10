"""Runtime inference and Product Result Artifact/Evidence producer."""

from .contracts import audit_fixture, derive_features, load_fixture
from .evidence import (
    FixtureContextProvider,
    build_evidence_package,
    build_product_result_artifact,
    validate_product_result_artifact,
)
from .predictor import ArtifactPredictor, HeuristicPredictor, Prediction, configured_predictor

__all__ = [
    "FixtureContextProvider",
    "ArtifactPredictor",
    "HeuristicPredictor",
    "Prediction",
    "audit_fixture",
    "build_evidence_package",
    "build_product_result_artifact",
    "configured_predictor",
    "validate_product_result_artifact",
    "derive_features",
    "load_fixture",
]


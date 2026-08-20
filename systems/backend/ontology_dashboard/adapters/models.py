"""Compatibility exports for Diagnosis-owned prediction contracts."""

from app.diagnosis.diagnosis_schema import (
    DataQuality,
    EvidenceSource,
    PredictionEvidence,
    PredictionModel,
    PredictionResult,
    PredictionSubject,
    PredictionValue,
    RecommendedAction,
)

__all__ = [
    "DataQuality",
    "EvidenceSource",
    "PredictionEvidence",
    "PredictionModel",
    "PredictionResult",
    "PredictionSubject",
    "PredictionValue",
    "RecommendedAction",
]

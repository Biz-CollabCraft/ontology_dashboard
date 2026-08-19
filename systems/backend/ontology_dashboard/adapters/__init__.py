"""Legacy Prediction persistence exports retained until Diagnosis phase #58."""

from .models import PredictionResult
from .prediction_repository import PredictionResultRepository

__all__ = ["PredictionResult", "PredictionResultRepository"]

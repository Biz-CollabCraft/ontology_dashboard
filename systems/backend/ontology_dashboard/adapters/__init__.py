"""Legacy Prediction persistence exports retained until Diagnosis phase #58."""

from .models import PredictionResult
from app.infra.db.prediction_result_repository import PredictionResultRepository

__all__ = ["PredictionResult", "PredictionResultRepository"]

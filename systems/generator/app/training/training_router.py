"""FastAPI Router for Generator canonical training API (/train) and Model Management API (/models)."""

from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Request, status

from systems.generator.app.training.training_schema import (
    TrainingRequest,
    TrainingResponse,
    ModelActivationResponse,
    ActiveModelResponse,
)
from systems.generator.app.training.training_service import TrainingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/train", tags=["Training"])
models_router = APIRouter(prefix="/models", tags=["Models"])
_service = TrainingService()


@router.post("", response_model=TrainingResponse, status_code=status.HTTP_200_OK)
def train_all_models(request: TrainingRequest, req: Request) -> TrainingResponse:
    """Train all registered base models and publish Model Artifacts."""
    req_id = getattr(req.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    return _service.run_training(request, base_model=None, request_id=req_id)


@router.post("/{base_model}", response_model=TrainingResponse, status_code=status.HTTP_200_OK)
def train_single_model(base_model: str, request: TrainingRequest, req: Request) -> TrainingResponse:
    """Train a single specified base model and publish its Model Artifact."""
    req_id = getattr(req.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    return _service.run_training(request, base_model=base_model, request_id=req_id)


@models_router.post("/{base_model}/activate/{model_version}", response_model=ModelActivationResponse, status_code=status.HTTP_200_OK)
def activate_model_version(base_model: str, model_version: str) -> ModelActivationResponse:
    """Manually activate an existing immutable model version pointer."""
    return _service.activate_model(base_model, model_version)


@models_router.get("/{base_model}/active", response_model=ActiveModelResponse, status_code=status.HTTP_200_OK)
def get_active_model(base_model: str) -> ActiveModelResponse:
    """Get active model version pointer information."""
    return _service.get_active_model(base_model)

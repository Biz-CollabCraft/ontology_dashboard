"""FastAPI Router for Generator Feature domain."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from systems.generator.app.feature.feature_schema import (
    FeatureRequest,
    FeatureResponse,
)
from systems.generator.app.feature.feature_service import FeatureService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feature"])
_service = FeatureService()


@router.post("/feature", response_model=FeatureResponse)
async def post_feature(req: FeatureRequest, request: Request) -> FeatureResponse:
    """Execute time-series feature generation, labeling, and versioned NPY publication."""
    req_id = getattr(request.state, "request_id", None)
    return _service.run_feature(req, request_id=req_id)

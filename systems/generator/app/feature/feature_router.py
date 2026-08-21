"""FastAPI router for feature and label generation domain."""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, Response

from systems.generator.app.feature.feature_schema import FeatureRequest, FeatureResponse
from systems.generator.app.feature.feature_service import FeatureService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feature"])


def get_feature_service() -> FeatureService:
    return FeatureService()


@router.post(
    "/feature",
    response_model=FeatureResponse,
    status_code=200,
    summary="Generate numerical features and labels and atomically publish Feature Dataset Bundle",
)
def create_feature_dataset(
    request: FeatureRequest,
    response: Response,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    service: FeatureService = Depends(get_feature_service),
) -> FeatureResponse:
    """Consumes Observation Dataset, Failure Dataset, Preprocessing Plan, and Ontology Mapping

    to construct aligned numerical feature matrix and labels, then atomically publishes
    an immutable Feature Dataset Bundle (5 essential files).
    """
    logger.info(
        f"[POST /feature] Received request: dataset={request.dataset_id}:{request.dataset_version}, "
        f"failure={request.failure_dataset_id}:{request.failure_dataset_version}, request_id={x_request_id}"
    )

    result = service.run_feature_pipeline(request, request_id=x_request_id)
    response.headers["X-Request-ID"] = result.request_id
    return result

"""FastAPI router for Generator Protocol Extraction domain."""

from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, Header, Request, status

from systems.generator.app.extraction.extraction_schema import (
    ExtractionRequest,
    ExtractionResponse,
)
from systems.generator.app.extraction.extraction_service import ExtractionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extraction"])
_extraction_service: Optional[ExtractionService] = None


def get_extraction_service() -> ExtractionService:
    global _extraction_service
    if _extraction_service is None:
        _extraction_service = ExtractionService()
    return _extraction_service


def set_extraction_service(service: Optional[ExtractionService]) -> None:
    global _extraction_service
    _extraction_service = service


@router.post(
    "/extraction",
    response_model=ExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute gen_data protocol extraction into Canonical Observation Dataset",
    description=(
        "Parses SensorRecord v2 protocol provenance files with approved static mapping tables, "
        "enforces deduplication and single-writer locks, and publishes versioned Canonical Observation Artifacts."
    ),
)
def extract_protocol_records(
    request_body: ExtractionRequest,
    request: Request,
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    service: ExtractionService = Depends(get_extraction_service),
) -> ExtractionResponse:
    """Synchronous endpoint executing end-to-end protocol extraction."""
    logger.info(
        f"[ExtractionAPI] Received extraction request: request_id={request_body.request_id}, "
        f"dataset={request_body.dataset_id}/{request_body.dataset_version}, "
        f"mapping={request_body.mapping_id}/{request_body.mapping_version}"
    )
    return service.execute_extraction(request_body)

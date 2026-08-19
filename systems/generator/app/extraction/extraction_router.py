"""FastAPI Router for Generator Extraction domain."""

from __future__ import annotations

import logging
from fastapi import APIRouter, Request
from systems.generator.app.extraction.extraction_schema import (
    ExtractionRequest,
    ExtractionResponse,
)
from systems.generator.app.extraction.extraction_service import ExtractionService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extraction"])
_service = ExtractionService()


@router.post("/extraction", response_model=ExtractionResponse)
async def post_extraction(req: ExtractionRequest, request: Request) -> ExtractionResponse:
    """Execute dataset extraction planning, validation, and versioned publishing."""
    req_id = getattr(request.state, "request_id", None)
    return _service.run_extraction(req, request_id=req_id)

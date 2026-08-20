"""Generator domain canonical FastAPI application."""

from __future__ import annotations

import logging
import uuid
from typing import Any
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from systems.generator.app.extraction.extraction_router import router as extraction_router
from systems.generator.app.extraction.extraction_exception import ExtractionError
from systems.generator.app.feature.feature_router import router as feature_router
from systems.generator.app.feature.feature_exception import FeatureError
from systems.generator.app.training.training_router import (
    router as training_router,
    models_router,
)
from systems.generator.app.training.training_exception import TrainingError
from systems.generator.app.extraction.extraction_schema import ErrorEnvelope, ErrorEnvelopeBody

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Generator Domain API",
    description="Generator control-plane, extraction, feature generation, and training API",
    version="1.0.0",
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Ensure every request has a request_id in state and response header."""
    req_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


# --- Standard Error Handlers ---

def _build_error_response(
    status_code: int,
    code: str,
    message: str,
    path: str,
    request_id: str,
    details: list[Any] | None = None,
) -> JSONResponse:
    error_id = f"err-{uuid.uuid4().hex[:8]}"
    envelope = ErrorEnvelope(
        error=ErrorEnvelopeBody(
            code=code,
            message=message,
            path=path,
            request_id=request_id,
            error_id=error_id,
            details=details or [],
        )
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump())


@app.exception_handler(ExtractionError)
async def extraction_error_handler(request: Request, exc: ExtractionError) -> JSONResponse:
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    logger.warning(f"[GeneratorAPI] ExtractionError: {exc.code} - {exc.message}")
    return _build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        path=request.url.path,
        request_id=req_id,
        details=exc.details,
    )


@app.exception_handler(FeatureError)
async def feature_error_handler(request: Request, exc: FeatureError) -> JSONResponse:
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    logger.warning(f"[GeneratorAPI] FeatureError: {exc.code} - {exc.message}")
    return _build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        path=request.url.path,
        request_id=req_id,
        details=exc.details,
    )


@app.exception_handler(TrainingError)
async def training_error_handler(request: Request, exc: TrainingError) -> JSONResponse:
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    logger.warning(f"[GeneratorAPI] TrainingError: {exc.code} - {exc.message}")
    return _build_error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        path=request.url.path,
        request_id=req_id,
        details=exc.details,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    details = []
    for err in exc.errors():
        details.append({
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        })
    logger.warning(f"[GeneratorAPI] Request validation error: {details}")
    return _build_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="REQUEST_VALIDATION_ERROR",
        message="요청 형식이 올바르지 않습니다.",
        path=request.url.path,
        request_id=req_id,
        details=details,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    code_map = {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        422: "UNPROCESSABLE_ENTITY",
        500: "INTERNAL_SERVER_ERROR",
    }
    code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
    message = str(exc.detail) if exc.detail else "HTTP 요청 처리 중 오류가 발생했습니다."
    return _build_error_response(
        status_code=exc.status_code,
        code=code,
        message=message,
        path=request.url.path,
        request_id=req_id,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")
    logger.exception(f"[GeneratorAPI] Unhandled server error: {exc}")
    return _build_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="INTERNAL_SERVER_ERROR",
        message="서버 내부 오류가 발생했습니다.",
        path=request.url.path,
        request_id=req_id,
    )


# --- Health Endpoint ---

@app.get("/health")
def health() -> dict[str, str]:
    """Server health check and system identifier."""
    return {"status": "ok", "system": "generator"}


# --- Include Routers ---

app.include_router(extraction_router)
app.include_router(feature_router)
app.include_router(training_router)
app.include_router(models_router)

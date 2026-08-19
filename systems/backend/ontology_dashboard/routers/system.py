"""System and contract endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.infra.observability.runtime import METRICS, metrics_authorized
from ..deployment import process_probe, readiness_probe, startup_probe
from ..polyglot import PolyglotHealthService, PolyglotSettings
from app.common.runtime_settings import project_root

router = APIRouter(tags=["system"])
ROOT = project_root()


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "ontology-dashboard",
        "mode": "liveness-compatibility",
        "domain_pack": "manufacturing-predictive-maintenance",
    }


@router.get("/health/live")
def health_live():
    return process_probe().model_dump(mode="json")


@router.get("/health/startup")
def health_startup():
    payload = startup_probe(ROOT)
    return JSONResponse(
        payload.model_dump(mode="json"),
        status_code=200 if payload.state == "ready" else 503,
    )


@router.get("/health/ready")
def health_ready():
    payload = readiness_probe(ROOT)
    return JSONResponse(
        payload.model_dump(mode="json"),
        status_code=200 if payload.state in {"ready", "degraded"} else 503,
    )


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    if not metrics_authorized(request):
        return JSONResponse({"detail": "metrics authentication required"}, status_code=401)
    return PlainTextResponse(
        METRICS.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


@router.get("/api/system/polyglot-health")
def polyglot_health() -> dict:
    return PolyglotHealthService(PolyglotSettings.from_environment()).snapshot()


@router.get("/api/openapi-contract")
def openapi_contract(request: Request) -> dict:
    return request.app.openapi()

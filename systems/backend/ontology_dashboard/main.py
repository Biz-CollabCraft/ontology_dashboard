"""Canonical Ontology Dashboard application composition root."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.dataset import DatasetAccessError
from app.dataset.dataset_router import create_dataset_router
from app.maintenance import MaintenanceAccessError
from app.maintenance.maintenance_router import build_maintenance_router

from .application import create_app
from .dependencies import (
    client_ip,
    current_principal,
    get_dataset_catalog_service,
    get_dashboard_service,
    get_export_service,
    get_governance_service,
    get_identity_service,
    get_maintenance_application_service,
    get_ontology_service,
    get_ontology_planner_service,
    get_project_service,
    get_predictive_maintenance_runtime_service,
    get_rate_limiter,
    get_role_workflow_service,
    get_service,
    rate_limit_subject,
    require_csrf,
    require_permission,
    set_auth_cookies,
)
from app.report import build_report_router
from app.dashboard import (
    DashboardAccessError,
    DashboardNotFoundError,
    build_dashboard_router,
)
from app.governance import GovernanceAccessError, build_governance_router
from app.identity import AuthError
from app.identity.identity_router import build_identity_router, identity_http_status
from app.project import ProjectError
from app.project.project_router import build_project_router, project_http_status
from .openapi_contracts import apply_response_contracts
from .routers.adapters import router as adapters_router
from .routers.agent import router as agent_router
from .routers.admin import router as admin_router
from .routers.analyses import router as analyses_router
from .routers.manufacturing import router as manufacturing_router
from .routers.modeling import router as modeling_router
from .routers.ontology import router as ontology_router
from .routers.planner import router as planner_router
from .routers.platform import router as platform_router
from .routers.project3 import router as project3_router
from .routers.role_workspaces import router as role_workspaces_router
from .routers.system import router as system_router
from app.common.exceptions import RateLimitExceeded
from app.diagnosis.diagnosis_router import create_diagnosis_router
from app.equipment import (
    EquipmentNotFoundError,
    EquipmentStateVersionConflictError,
    InvalidEquipmentStatePatchError,
)
from .service import EventNotFound

app = create_app()
predictive_maintenance_runtime_router = create_diagnosis_router(
    require_permission=require_permission,
    get_identity_service=get_identity_service,
    get_runtime_service=get_predictive_maintenance_runtime_service,
    require_csrf=require_csrf,
)

auth_router = build_identity_router(
    get_identity_service=get_identity_service,
    get_rate_limiter=get_rate_limiter,
    current_principal=current_principal,
    require_csrf=require_csrf,
    client_ip=client_ip,
    rate_limit_subject=rate_limit_subject,
    set_auth_cookies=set_auth_cookies,
)

datasets_router = create_dataset_router(
    get_dataset_catalog_service=get_dataset_catalog_service,
    require_csrf=require_csrf,
    require_permission=require_permission,
)

projects_router = build_project_router(
    get_project_service=get_project_service,
    get_event_query=get_service,
    require_permission=require_permission,
    require_csrf=require_csrf,
)

dashboards_router = build_dashboard_router(
    get_dashboard_service=get_dashboard_service,
    get_identity_service=get_identity_service,
    get_ontology_service=get_ontology_service,
    get_role_workflow_service=get_role_workflow_service,
    get_event_query_service=get_service,
    require_csrf=require_csrf,
    require_permission=require_permission,
)
exports_router = build_report_router(
    get_report_service=get_export_service,
    get_identity_service=get_identity_service,
    get_rate_limiter=get_rate_limiter,
    rate_limit_subject=rate_limit_subject,
    require_csrf=require_csrf,
    require_permission=require_permission,
)
governance_router = build_governance_router(
    get_governance_service=get_governance_service,
    require_permission=require_permission,
    require_csrf=require_csrf,
)

maintenance_router = build_maintenance_router(
    get_maintenance_service=get_maintenance_application_service,
    require_permission=require_permission,
    require_csrf=require_csrf,
)


@app.exception_handler(DashboardNotFoundError)
async def dashboard_not_found_handler(_: Request, exc: DashboardNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "not_found", "message": f"resource not found: {exc.args[0]}"}},
    )


@app.exception_handler(DashboardAccessError)
async def dashboard_access_error_handler(_: Request, exc: DashboardAccessError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(EventNotFound)
async def not_found_handler(_: Request, exc: EventNotFound) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "not_found",
                "message": f"resource not found: {exc.args[0]}",
            }
        },
    )


@app.exception_handler(EquipmentNotFoundError)
async def equipment_not_found_handler(
    _: Request, exc: EquipmentNotFoundError
) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "not_found",
                "message": f"resource not found: {exc.args[0]}",
            }
        },
    )


@app.exception_handler(EquipmentStateVersionConflictError)
async def equipment_state_version_conflict_handler(
    _: Request, exc: EquipmentStateVersionConflictError
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "equipment_state_version_conflict",
                "message": str(exc),
            }
        },
    )


@app.exception_handler(InvalidEquipmentStatePatchError)
async def invalid_equipment_state_patch_handler(
    _: Request, exc: InvalidEquipmentStatePatchError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "invalid_equipment_state_patch",
                "message": str(exc),
            }
        },
    )


@app.exception_handler(AuthError)
async def auth_error_handler(_: Request, exc: AuthError) -> JSONResponse:
    return JSONResponse(
        status_code=identity_http_status(exc),
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(DatasetAccessError)
async def dataset_access_error_handler(_: Request, exc: DatasetAccessError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(ProjectError)
async def project_error_handler(_: Request, exc: ProjectError) -> JSONResponse:
    return JSONResponse(
        status_code=project_http_status(exc),
        content={"error": {"code": exc.code, "message": exc.message}},
    )

@app.exception_handler(MaintenanceAccessError)
async def maintenance_access_error_handler(
    _: Request,
    exc: MaintenanceAccessError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(GovernanceAccessError)
async def governance_access_error_handler(_: Request, exc: GovernanceAccessError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(ValueError)
async def validation_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "contract_validation_failed",
                "message": str(exc),
            }
        },
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(_: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(exc.retry_after)},
        content={
            "error": {
                "code": "rate_limit_exceeded",
                "message": "요청이 너무 많습니다. 잠시 후 다시 시도하세요.",
                "bucket": exc.bucket,
                "retry_after": exc.retry_after,
            }
        },
    )


for feature_router in (
    system_router,
    auth_router,
    agent_router,
    adapters_router,
    datasets_router,
    ontology_router,
    analyses_router,
    projects_router,
    dashboards_router,
    exports_router,
    governance_router,
    planner_router,
    platform_router,
    project3_router,
    predictive_maintenance_runtime_router,
    modeling_router,
    role_workspaces_router,
    maintenance_router,
    manufacturing_router,
    admin_router,
):
    apply_response_contracts(feature_router)
    app.include_router(feature_router)


__all__ = [
    "app",
    "get_identity_service",
    "get_ontology_planner_service",
    "get_rate_limiter",
    "get_service",
]

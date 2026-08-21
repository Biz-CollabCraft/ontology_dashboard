"""Minimal application composition dependencies.

Only capabilities used by the current product runtime are wired here.  Removed
prototype workbenches are intentionally not dependencies of ``app.main``.
"""

from __future__ import annotations

import ipaddress
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Callable

from argon2 import PasswordHasher
from fastapi import Depends, HTTPException, Request, Response, status

from app.common.rate_limit import RateLimiter
from app.common.runtime_settings import project_root, trust_proxy_headers, trusted_proxy_networks
from app.dashboard import DashboardService
from app.dashboard.dashboard_schema import DashboardBoard, DashboardTab, DashboardTemplatePublishRequest
from app.dashboard.visualizations import (
    FieldProfile,
    SemanticVisualizationPlanRequest,
    SemanticVisualizationPlanResponse,
    VISUALIZATION_REGISTRY,
    VisualizationCandidate,
    build_typed_query_plan,
    build_v3_1_semantic_catalog,
    compile_postgresql_query,
    context_from_source,
    validate_override,
    validate_override_channel_mapping,
)
from app.dataset import DatasetCatalogService
from app.diagnosis.evidence import FixtureContextProvider
from app.diagnosis.runtime_service import (
    PredictiveMaintenanceRuntimeService,
    V3_1_MODEL_VERSION,
    V3_1_RESULT_SCHEMA,
    V3_1_SOURCE_VERSION,
)
from app.diagnosis.contracts import load_fixture
from app.governance import GovernanceService
from app.identity import CSRF_COOKIE, SESSION_COOKIE, AuthError, IdentityService, Principal
from app.infra.db.dashboard_repository import DashboardRepository
from app.infra.db.dataset_ingestion_repository import DatasetIngestionRepository
from app.infra.db.dataset_repository import DatasetRepository
from app.infra.db.diagnosis_runtime_repository import PredictiveMaintenanceRuntimeRepository
from app.infra.db.identity_repository import IdentityRepository as SQLiteIdentityRepository
from app.infra.db.migrations import migrate
from app.infra.db.ontology_action_repository import OntologyActionRepository
from app.infra.db.ontology_instance_repository import OntologyInstanceRepository
from app.infra.db.postgresql_bundle_ingestion import PostgreSQLPredictiveMaintenanceBundleIngestor
from app.infra.db.prediction_result_repository import PredictionResultRepository
from app.infra.db.project_repository import (
    ProjectRepository as SQLiteProjectRepository,
    SQLiteProjectContextResolver,
)
from app.infra.db.report_repository import ReportRepository
from app.infra.db.settings import database_location
from app.infra.context import Project3HttpContextProvider, ResilientContextProvider
from app.infra.llm import configured_provider
from app.infra.rate_limit import InMemoryRateLimiter, RedisRateLimiter
from app.maintenance.live_service import LivePredictiveMaintenanceService
from app.ontology import OntologyService
from app.planner import LayoutPlanner, OntologyDashboardPlannerService
from app.project import ProjectService
from app.report import ReportService
from app.report.generation_provider import ReportAgent

from app.dataset.ingestion.api_service import AdapterService
from app.equipment import EquipmentService
from app.equipment.adapters import FixtureEquipmentRepository
from app.infra.db.postgresql_ontology_repository import PostgreSQLOntologyInstanceRepository
from app.infra.db.postgresql_repositories import (
    PostgreSQLAdapterRepository,
    PostgreSQLAuditRepository,
    PostgreSQLDashboardRepository,
    PostgreSQLExportRepository,
    PostgreSQLIdentityRepository,
    PostgreSQLOntologyActionRepository,
    PostgreSQLPredictionResultRepository,
    PostgreSQLProjectRepository,
    PostgreSQLRoleWorkflowRepository,
    is_postgresql,
    seed_runtime_reference_data,
)
from app.infra.db.project_repository import SQLiteProjectContextResolver as RuntimeProjectContextResolver
from app.infra.db.role_workflow_repository import RoleWorkflowRepository
from app.infra.db.mvp_audit_repository import AuditRepository
from app.mvp.role_workflow_service import RoleWorkflowService
from app.mvp.service import ManufacturingPredictiveMaintenanceService


ROOT = project_root()
MANUFACTURING_WORKSPACE = "manufacturing-demo"
_MIGRATION_LOCK = Lock()


def database_target() -> str:
    return database_location(ROOT)


@lru_cache(maxsize=1)
def ensure_database_migrations() -> tuple[str, ...]:
    with _MIGRATION_LOCK:
        return tuple(migrate(database_target()))


def _mvp_fixture_masters(root: Path) -> list[tuple[str, dict[str, Any]]]:
    fixture_root = root / "data" / "fixtures"
    masters: list[tuple[str, dict[str, Any]]] = []
    for pattern in ("GS-*.json", "AZ-*.json", "MPT-*.json"):
        for path in fixture_root.glob(pattern):
            fixture = load_fixture(path)
            masters.append(
                (
                    str(fixture.get("project_id") or "manufacturing-demo-project"),
                    fixture["equipment"],
                )
            )
    return masters


def _mvp_context_provider(fixture: dict[str, Any]):
    fallback = FixtureContextProvider()
    if fixture["runtime"]["context_provider"] == "project3_http":
        return ResilientContextProvider(Project3HttpContextProvider(), fallback)
    return fallback


def build_manufacturing_service(
    database_path: str | Path,
    *,
    root: Path = ROOT,
) -> ManufacturingPredictiveMaintenanceService:
    """Compose the MVP application service with concrete runtime adapters."""

    target = str(database_path)
    migrate(target)
    audit_repository = (
        PostgreSQLAuditRepository(target)
        if is_postgresql(target)
        else AuditRepository(target)
    )
    provider = configured_provider()
    equipment_service = EquipmentService(
        FixtureEquipmentRepository(_mvp_fixture_masters(root))
    )
    return ManufacturingPredictiveMaintenanceService(
        root,
        repository=audit_repository,
        equipment_service=equipment_service,
        report_agent=ReportAgent(root, provider),
        layout_planner=LayoutPlanner(root, provider),
        context_provider_factory=_mvp_context_provider,
    )


@lru_cache(maxsize=1)
def get_service() -> ManufacturingPredictiveMaintenanceService:
    return build_manufacturing_service(database_target())


def _password_hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1, hash_len=32, salt_len=16)


@lru_cache(maxsize=1)
def get_identity_service() -> IdentityService:
    ensure_database_migrations()
    target = database_target()
    repository = (
        PostgreSQLIdentityRepository(
            target,
            password_hasher=_password_hasher(),
            seed_reference_data=seed_runtime_reference_data(),
        )
        if is_postgresql(target)
        else SQLiteIdentityRepository(target, password_hasher=_password_hasher())
    )
    return IdentityService(repository, rate_limit_namespace=f"identity:{target}")


@lru_cache(maxsize=1)
def get_project_service() -> ProjectService:
    ensure_database_migrations()
    target = database_target()
    repository = PostgreSQLProjectRepository(target) if is_postgresql(target) else SQLiteProjectRepository(target)
    return ProjectService(repository, audit_port=get_identity_service().repository)


@lru_cache(maxsize=1)
def get_adapter_service() -> AdapterService:
    return build_adapter_service(database_target())


def build_adapter_service(
    database_path: str | Path,
    *,
    root: Path = ROOT,
) -> AdapterService:
    """Compose Dataset ingestion with persistence and Diagnosis ports."""

    target = str(database_path)
    migrate(target)
    if is_postgresql(target):
        repository = PostgreSQLAdapterRepository(target)
        predictions = PostgreSQLPredictionResultRepository(target)
    else:
        repository = DatasetIngestionRepository(target)
        predictions = PredictionResultRepository(
            target,
            project_context=RuntimeProjectContextResolver(target),
        )
    return AdapterService(
        target,
        root=root,
        repository=repository,
        prediction_repository=predictions,
        dataset_catalog=DatasetCatalogService(DatasetRepository(target)),
        bundle_ingestor_factory=PostgreSQLPredictiveMaintenanceBundleIngestor,
    )


def build_live_predictive_maintenance_service(
    database_url: str | None = None,
) -> LivePredictiveMaintenanceService:
    """Compose the live worker application service with its infrastructure adapter."""

    from app.infra.live_predictive_maintenance_runtime import (
        LivePredictiveMaintenanceRuntime,
    )

    return LivePredictiveMaintenanceService(
        LivePredictiveMaintenanceRuntime(database_url or database_target())
    )


def _ontology_principal(
    request: Request,
    identity: IdentityService = Depends(get_identity_service),
) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthError("authentication_required", "로그인이 필요합니다.")
    return identity.principal_for_token(
        token,
        user_agent=request.headers.get("User-Agent"),
        client_ip=client_ip(request),
    )


def get_ontology_service(
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    principal: Principal = Depends(_ontology_principal),
) -> OntologyService:
    target = str(service.repository.path)
    if is_postgresql(target):
        project_id = principal.active_project_id or (principal.project_scopes[0] if len(principal.project_scopes) == 1 else None)
        if not project_id:
            raise AuthError("active_project_required", "Ontology를 조회하기 전에 Project를 활성화해야 합니다.")
        field_actions = PostgreSQLRoleWorkflowRepository(target)
        return OntologyService(
            service,
            action_repository=PostgreSQLOntologyActionRepository(target),
            instance_repository=PostgreSQLOntologyInstanceRepository(
                target,
                organization_id=principal.organization_id,
                project_id=project_id,
            ),
            field_actions=field_actions,
        )
    project_context = SQLiteProjectContextResolver(target)
    field_actions = RoleWorkflowRepository(target)
    return OntologyService(
        service,
        action_repository=OntologyActionRepository(target, project_context=project_context),
        instance_repository=OntologyInstanceRepository(target, project_context=project_context),
        field_actions=field_actions,
    )


def get_dashboard_service(
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
) -> DashboardService:
    target = str(service.repository.path)
    repository = (
        PostgreSQLDashboardRepository(target)
        if is_postgresql(target)
        else DashboardRepository(target, project_context=SQLiteProjectContextResolver(target))
    )
    return DashboardService(repository=repository)


def get_role_workflow_service(
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    ontology: OntologyService = Depends(get_ontology_service),
    dashboards: DashboardService = Depends(get_dashboard_service),
) -> RoleWorkflowService:
    target = str(service.repository.path)
    repository = PostgreSQLRoleWorkflowRepository(target) if is_postgresql(target) else RoleWorkflowRepository(target)
    return RoleWorkflowService(service, repository=repository, ontology=ontology, dashboards=dashboards)


class _DashboardReportSnapshotAdapter:
    def __init__(self, dashboards: DashboardService) -> None:
        self.dashboards = dashboards

    def dashboard_snapshot(self, *, principal: Principal, workspace_id: str) -> dict[str, Any]:
        return self.dashboards.resolve(principal=principal, workspace_id=workspace_id).model_dump(mode="json")


class _DiagnosisReportSnapshotAdapter:
    def __init__(self, service: ManufacturingPredictiveMaintenanceService) -> None:
        self.service = service

    def event_report_snapshot(self, *, event_id: str, principal: Principal) -> dict[str, Any]:
        return {
            "event": self.service.event(event_id),
            "evidence": self.service.evidence_snapshot(event_id),
            "activity": self.service.repository.event_activity(event_id),
        }


class _RoleWorkspaceReportAdapter:
    def __init__(self, workflows: RoleWorkflowService, service: ManufacturingPredictiveMaintenanceService, dashboards: DashboardService) -> None:
        self.workflows = workflows
        self.service = service
        self.dashboards = dashboards

    def role_workspace_snapshot(self, *, principal: Principal, workspace_id: str) -> dict[str, Any]:
        return self.dashboards.resolve(principal=principal, workspace_id=workspace_id).model_dump(mode="json")


class _ReportAuditAdapter:
    def __init__(self, service: ManufacturingPredictiveMaintenanceService) -> None:
        self.service = service

    def record_report_audit(self, **command: Any) -> dict[str, Any]:
        return self.service.repository.record_audit(**command)


def get_export_service(
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    dashboards: DashboardService = Depends(get_dashboard_service),
    workflows: RoleWorkflowService = Depends(get_role_workflow_service),
) -> ReportService:
    target = str(service.repository.path)
    repository = (
        PostgreSQLExportRepository(target)
        if is_postgresql(target)
        else ReportRepository(target, project_context=SQLiteProjectContextResolver(target))
    )
    return ReportService(
        repository=repository,
        dashboard=_DashboardReportSnapshotAdapter(dashboards),
        diagnosis=_DiagnosisReportSnapshotAdapter(service),
        maintenance=_RoleWorkspaceReportAdapter(workflows, service, dashboards),
        audit=_ReportAuditAdapter(service),
    )


@lru_cache(maxsize=1)
def get_dataset_catalog_service() -> DatasetCatalogService:
    target = database_target()
    migrate(target)
    return DatasetCatalogService(DatasetRepository(target))


def get_governance_service(
    workflows: RoleWorkflowService = Depends(get_role_workflow_service),
) -> GovernanceService:
    return GovernanceService(datasets=get_dataset_catalog_service().repository, approvals=workflows.repository)


@lru_cache(maxsize=1)
def get_predictive_maintenance_runtime_service() -> PredictiveMaintenanceRuntimeService:
    target = database_target()
    migrate(target)
    if not is_postgresql(target):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Predictive-maintenance live runtime requires PostgreSQL",
        )
    return PredictiveMaintenanceRuntimeService(PredictiveMaintenanceRuntimeRepository(target))


class DashboardPlannerAdapter:
    def __init__(self, service: DashboardService) -> None:
        self.service = service

    def resolve(self, *, principal: Principal, workspace_id: str):
        return self.service.resolve(principal=principal, workspace_id=workspace_id)

    def catalog(self, *, principal: Principal, role_code: str):
        return self.service.catalog(principal=principal, role_code=role_code)

    def current_template(self, *, workspace_id: str, role_code: str):
        return self.service.current_template(workspace_id=workspace_id, role_code=role_code)

    @staticmethod
    def make_board(**values):
        return DashboardBoard(**values)

    @staticmethod
    def make_tab(**values):
        return DashboardTab(**values)

    @staticmethod
    def make_publish_request(**values):
        return DashboardTemplatePublishRequest(**values)

    def validate_template_draft(self, *, role_code: str, template, request):
        return self.service.validate_template_draft(role_code=role_code, template=template, request=request)


class VisualizationPlannerAdapter:
    source_version = V3_1_SOURCE_VERSION
    model_version = V3_1_MODEL_VERSION
    result_schema_version = V3_1_RESULT_SCHEMA
    registry_kinds = frozenset(item.kind for item in VISUALIZATION_REGISTRY)

    @staticmethod
    def _payload(value):
        return value.model_dump(mode="python") if hasattr(value, "model_dump") else value

    def parse_field_profile(self, value):
        return FieldProfile.model_validate(self._payload(value))

    def parse_candidate(self, value):
        return VisualizationCandidate.model_validate(self._payload(value))

    def parse_semantic_request(self, value):
        return value if isinstance(value, SemanticVisualizationPlanRequest) else SemanticVisualizationPlanRequest.model_validate(self._payload(value))

    @staticmethod
    def context_from_source(source):
        return context_from_source(source)

    @staticmethod
    def build_semantic_catalog(context):
        return build_v3_1_semantic_catalog(context)

    @staticmethod
    def build_typed_query_plan(request, catalog, *, selected_kind=None):
        return build_typed_query_plan(request, catalog, selected_kind=selected_kind)

    @staticmethod
    def validate_override(override, plan, catalog):
        return validate_override(override, plan, catalog)

    @staticmethod
    def validate_override_channel_mapping(override, plan) -> None:
        validate_override_channel_mapping(override, plan)

    @staticmethod
    def compile_query(plan, catalog, *, clamp_limits: bool):
        return compile_postgresql_query(plan, catalog, clamp_limits=clamp_limits)

    @staticmethod
    def make_semantic_response(**values):
        return SemanticVisualizationPlanResponse(**values)


def get_ontology_planner_service(
    service: ManufacturingPredictiveMaintenanceService = Depends(get_service),
    ontology: OntologyService = Depends(get_ontology_service),
    dashboards: DashboardService = Depends(get_dashboard_service),
) -> OntologyDashboardPlannerService:
    provider_name = os.getenv("LLM_PROVIDER", "deterministic").strip().lower()
    provider = None if provider_name in {"", "none", "deterministic", "offline"} else configured_provider()
    return OntologyDashboardPlannerService(
        service,
        provider=provider,
        ontology=ontology,
        dashboards=DashboardPlannerAdapter(dashboards),
        visualizations=VisualizationPlannerAdapter(),
    )


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    redis_url = os.getenv("ONTOLOGY_DASHBOARD_REDIS_URL", "").strip()
    return RedisRateLimiter(redis_url) if redis_url else InMemoryRateLimiter()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client is not None else "unknown"
    if not trust_proxy_headers():
        return peer
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_address in network for network in trusted_proxy_networks()):
        return peer
    forwarded = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    try:
        return str(ipaddress.ip_address(forwarded)) if forwarded else peer
    except ValueError:
        return peer


def rate_limit_subject(*parts: str) -> str:
    return InMemoryRateLimiter.anonymized_key(*parts)


def set_auth_cookies(*, response: Response, identity: IdentityService, token: str, csrf_token: str, expires_at: datetime) -> None:
    max_age = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, expires=expires_at, httponly=True, secure=identity.secure_cookies, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf_token, max_age=max_age, expires=expires_at, httponly=False, secure=identity.secure_cookies, samesite="lax", path="/")


def current_principal(request: Request, identity: IdentityService = Depends(get_identity_service)) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthError("authentication_required", "로그인이 필요합니다.")
    return identity.principal_for_token(token, user_agent=request.headers.get("User-Agent"), client_ip=client_ip(request))


def require_permission(permission: str) -> Callable[..., Principal]:
    def dependency(
        principal: Principal = Depends(current_principal),
        identity: IdentityService = Depends(get_identity_service),
    ) -> Principal:
        identity.require_permission(principal, permission)
        return principal

    return dependency


def require_manufacturing_scope(
    principal: Principal = Depends(require_permission("events.read")),
    identity: IdentityService = Depends(get_identity_service),
) -> Principal:
    identity.require_workspace(principal, MANUFACTURING_WORKSPACE)
    return principal


def require_csrf(request: Request, identity: IdentityService = Depends(get_identity_service)) -> None:
    identity.verify_csrf(request.cookies.get(CSRF_COOKIE), request.headers.get("X-CSRF-Token"))


__all__ = [name for name in globals() if name.startswith("get_") or name in {
    "MANUFACTURING_WORKSPACE", "client_ip", "current_principal", "rate_limit_subject",
    "require_csrf", "require_manufacturing_scope", "require_permission", "set_auth_cookies",
}]

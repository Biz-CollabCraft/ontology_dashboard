"""Maintenance-owned HTTP commands for the two-stage Closed-loop workflow."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from app.identity import AuthError

from .api_schema import (
    InspectionResultCreateRequest,
    InspectionWorkOrderCreateRequest,
    OperationsManualRecommendationCreateRequest,
    RecommendationDecisionCreateRequest,
)
from .maintenance_domain import IdempotencyConflict, InvalidTransition
from .maintenance_schema import WorkOrderStatus
from .service import MaintenanceLoopService


PermissionDependencyFactory = Callable[[str], Callable[..., Any]]


def _require_scope(
    *, principal: Any, identity: Any, project_id: str, workspace_id: str
) -> None:
    identity.require_project(principal, project_id)
    identity.require_workspace(principal, workspace_id)


def _require_product_role(principal: Any, project_id: str, role: str) -> None:
    roles = set(principal.roles)
    roles.update(principal.project_roles.get(project_id, []))
    if principal.active_project_id == project_id:
        roles.update(principal.active_project_roles)
    if role not in roles:
        raise AuthError(
            "role_context_denied",
            f"이 작업은 {role} 역할에서만 수행할 수 있습니다.",
        )


def _execute(command: Callable[[], Any]) -> Any:
    try:
        return command()
    except KeyError as exc:
        return _error(404, "not_found", f"resource not found: {exc.args[0]}")
    except IdempotencyConflict as exc:
        return _error(409, "idempotency_key_conflict", str(exc))
    except InvalidTransition as exc:
        return _error(409, "invalid_state_transition", str(exc))
    except ValueError as exc:
        return _error(422, "contract_validation_failed", str(exc))


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def create_maintenance_router(
    *,
    require_permission: PermissionDependencyFactory,
    get_identity_service: Callable[..., Any],
    get_maintenance_service: Callable[..., MaintenanceLoopService],
    require_csrf: Callable[..., None],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/projects/{project_id}/workspaces/{workspace_id}/maintenance",
        tags=["maintenance"],
    )
    manager_command = require_permission("events.decision")
    engineer_command = require_permission("field.tasks.update")
    events_read = require_permission("events.read")

    @router.post("/inspection-work-orders")
    def request_inspection_work_order(
        project_id: str,
        workspace_id: str,
        payload: InspectionWorkOrderCreateRequest,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=8, max_length=200
        ),
        principal: Any = Depends(manager_command),
        _: None = Depends(require_csrf),
        identity: Any = Depends(get_identity_service),
        service: MaintenanceLoopService = Depends(get_maintenance_service),
    ):
        _require_scope(
            principal=principal,
            identity=identity,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        _require_product_role(principal, project_id, "process_manager")
        return _execute(
            lambda: service.request_inspection(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                payload=payload,
                actor_id=principal.user_id,
                actor_display_name=principal.display_name,
                idempotency_key=idempotency_key,
            )
        )

    @router.post("/inspection-work-orders/{work_order_id}/approve")
    def approve_inspection_work_order(
        project_id: str,
        workspace_id: str,
        work_order_id: str,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=8, max_length=200
        ),
        principal: Any = Depends(manager_command),
        _: None = Depends(require_csrf),
        identity: Any = Depends(get_identity_service),
        service: MaintenanceLoopService = Depends(get_maintenance_service),
    ):
        _require_scope(
            principal=principal,
            identity=identity,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        _require_product_role(principal, project_id, "process_manager")
        return _execute(
            lambda: service.transition_inspection(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                work_order_id=work_order_id,
                target=WorkOrderStatus.APPROVED,
                actor_id=principal.user_id,
                actor_display_name=principal.display_name,
                idempotency_key=idempotency_key,
            )
        )

    @router.post("/inspection-work-orders/{work_order_id}/start")
    def start_inspection_work_order(
        project_id: str,
        workspace_id: str,
        work_order_id: str,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=8, max_length=200
        ),
        principal: Any = Depends(engineer_command),
        _: None = Depends(require_csrf),
        identity: Any = Depends(get_identity_service),
        service: MaintenanceLoopService = Depends(get_maintenance_service),
    ):
        _require_scope(
            principal=principal,
            identity=identity,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        _require_product_role(principal, project_id, "process_engineer")
        return _execute(
            lambda: service.transition_inspection(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                work_order_id=work_order_id,
                target=WorkOrderStatus.IN_PROGRESS,
                actor_id=principal.user_id,
                actor_display_name=principal.display_name,
                idempotency_key=idempotency_key,
            )
        )

    @router.post("/inspection-work-orders/{work_order_id}/complete")
    def complete_inspection_work_order(
        project_id: str,
        workspace_id: str,
        work_order_id: str,
        payload: InspectionResultCreateRequest,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=8, max_length=200
        ),
        principal: Any = Depends(engineer_command),
        _: None = Depends(require_csrf),
        identity: Any = Depends(get_identity_service),
        service: MaintenanceLoopService = Depends(get_maintenance_service),
    ):
        _require_scope(
            principal=principal,
            identity=identity,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        _require_product_role(principal, project_id, "process_engineer")
        return _execute(
            lambda: service.complete_inspection(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                work_order_id=work_order_id,
                payload=payload,
                actor_id=principal.user_id,
                actor_display_name=principal.display_name,
                idempotency_key=idempotency_key,
            )
        )

    @router.post("/inspection-results/{inspection_result_id}/recommendations")
    def create_operations_manual_recommendation(
        project_id: str,
        workspace_id: str,
        inspection_result_id: str,
        payload: OperationsManualRecommendationCreateRequest,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=8, max_length=200
        ),
        principal: Any = Depends(manager_command),
        _: None = Depends(require_csrf),
        identity: Any = Depends(get_identity_service),
        service: MaintenanceLoopService = Depends(get_maintenance_service),
    ):
        _require_scope(
            principal=principal,
            identity=identity,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        _require_product_role(principal, project_id, "process_manager")
        return _execute(
            lambda: service.create_manual_recommendation(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                inspection_result_id=inspection_result_id,
                payload=payload,
                actor_id=principal.user_id,
                actor_display_name=principal.display_name,
                idempotency_key=idempotency_key,
            )
        )

    @router.post("/recommendations/{recommendation_id}/decisions")
    def decide_operations_manual_recommendation(
        project_id: str,
        workspace_id: str,
        recommendation_id: str,
        payload: RecommendationDecisionCreateRequest,
        idempotency_key: str = Header(
            alias="Idempotency-Key", min_length=8, max_length=200
        ),
        principal: Any = Depends(manager_command),
        _: None = Depends(require_csrf),
        identity: Any = Depends(get_identity_service),
        service: MaintenanceLoopService = Depends(get_maintenance_service),
    ):
        _require_scope(
            principal=principal,
            identity=identity,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        _require_product_role(principal, project_id, "process_manager")
        return _execute(
            lambda: service.decide_manual_recommendation(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                recommendation_id=recommendation_id,
                payload=payload,
                actor_id=principal.user_id,
                actor_display_name=principal.display_name,
                idempotency_key=idempotency_key,
            )
        )

    @router.get("/events/{event_id}/lineage")
    def event_lineage(
        project_id: str,
        workspace_id: str,
        event_id: str,
        principal: Any = Depends(events_read),
        identity: Any = Depends(get_identity_service),
        service: MaintenanceLoopService = Depends(get_maintenance_service),
    ):
        _require_scope(
            principal=principal,
            identity=identity,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        return _execute(
            lambda: service.event_lineage(
                organization_id=principal.organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                event_id=event_id,
            )
        )

    return router


__all__ = ["create_maintenance_router"]

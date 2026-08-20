"""Maintenance application orchestration over canonical public ports."""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from .maintenance_exception import MaintenanceAccessError
from .maintenance_schema import DecisionRequest, NoteRequest
from .ports import MaintenanceActionExecutionPort, MaintenanceEventAccessPort


class MaintenancePrincipal(Protocol):
    is_admin: bool
    project_scopes: list[str]
    active_project_id: str | None


class MaintenanceApplicationService:
    """Own compatibility Maintenance application flow without legacy imports."""

    def __init__(
        self,
        *,
        events: MaintenanceEventAccessPort,
        actions: MaintenanceActionExecutionPort,
        workspace_id: str,
        configured_action_project_id: str,
    ) -> None:
        self.events = events
        self.actions = actions
        self.workspace_id = workspace_id
        self.configured_action_project_id = configured_action_project_id

    def _require_active_event_project(
        self,
        principal: MaintenancePrincipal,
        event_id: str,
    ) -> str:
        project_id = self.events.project_id_for_event(event_id)
        if not principal.is_admin and project_id not in principal.project_scopes:
            raise MaintenanceAccessError(
                403,
                "project_scope_denied",
                "허용된 Project 범위를 벗어난 Event입니다.",
            )
        if principal.active_project_id != project_id:
            raise MaintenanceAccessError(
                409,
                "active_project_mismatch",
                "먼저 Event가 속한 Project를 활성화해야 합니다.",
            )
        return project_id

    def _require_configured_action_project(self, project_id: str) -> None:
        if project_id != self.configured_action_project_id:
            raise MaintenanceAccessError(
                422,
                "project_action_not_configured",
                "이 showcase Project는 현재 Evidence 조회 전용입니다. Action mapping을 먼저 게시해야 합니다.",
            )

    def record_decision(
        self,
        *,
        event_id: str,
        request: DecisionRequest,
        principal: MaintenancePrincipal,
    ) -> dict[str, Any]:
        project_id = self._require_active_event_project(principal, event_id)
        self._require_configured_action_project(project_id)
        return self.actions.execute(
            action_type="record_operational_decision",
            target_kind="risk_event",
            target_id=event_id,
            workspace_id=self.workspace_id,
            parameters={"decision": request.decision, "note": request.note},
            idempotency_key=f"legacy-decision:{uuid.uuid4()}",
            principal=principal,
        )

    def add_note(
        self,
        *,
        event_id: str,
        request: NoteRequest,
        principal: MaintenancePrincipal,
    ) -> dict[str, Any]:
        project_id = self._require_active_event_project(principal, event_id)
        self._require_configured_action_project(project_id)
        return self.actions.execute(
            action_type="record_inspection_note",
            target_kind="inspection",
            target_id=event_id,
            workspace_id=self.workspace_id,
            parameters={"body": request.body},
            idempotency_key=f"legacy-note:{uuid.uuid4()}",
            principal=principal,
        )

    def event_activity(
        self,
        *,
        event_id: str,
        principal: MaintenancePrincipal,
    ) -> list[dict[str, Any]]:
        self._require_active_event_project(principal, event_id)
        self.events.ensure_event(event_id)
        return self.events.event_activity(event_id)


__all__ = ["MaintenanceApplicationService", "MaintenancePrincipal"]

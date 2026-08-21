"""Ports required by the manufacturing MVP application layer.

The MVP package is intentionally adapter-agnostic.  Concrete SQLite/PostgreSQL
repositories are assembled in ``app.dependencies`` and only these small
protocols cross the composition boundary.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class AuditRepositoryPort(Protocol):
    path: str | Path

    def event_activity(self, event_id: str) -> dict[str, Any]: ...

    def record_decision(
        self,
        event_id: str,
        actor: str,
        decision: str,
        note: str | None,
    ) -> dict[str, Any]: ...

    def add_note(self, event_id: str, actor: str, body: str) -> dict[str, Any]: ...

    def add_conversation(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def record_audit(self, **command: Any) -> dict[str, Any]: ...

    def reset(self) -> None: ...


class RoleWorkflowRepositoryPort(Protocol):
    def list_field_actions(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]: ...

    def list_export_checkpoints(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]: ...

    def create_export_checkpoint(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def latest_field_statuses(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def record_field_action(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def list_workflow_requests(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]: ...

    def create_template_publish_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def create_model_release_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...

    def get_workflow_request(self, *args: Any, **kwargs: Any) -> dict[str, Any] | None: ...

    def decide_workflow_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]: ...


class ReportAgentPort(Protocol):
    def generate(self, *args: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]: ...


class LayoutPlannerPort(Protocol):
    def plan(self, *args: Any, **kwargs: Any) -> tuple[Any, dict[str, Any]]: ...


__all__ = [
    "AuditRepositoryPort",
    "LayoutPlannerPort",
    "ReportAgentPort",
    "RoleWorkflowRepositoryPort",
]

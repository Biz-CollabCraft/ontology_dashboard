"""Project-owned domain contracts shared with other Backend domains."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

ProjectId: TypeAlias = str
ProjectScope: TypeAlias = str


@dataclass(frozen=True, slots=True)
class ProjectContext:
    organization_id: str
    project_id: ProjectId
    workspace_id: str


class ProjectAuditPort(Protocol):
    """Narrow audit capability supplied by application composition."""

    def record_admin_audit(
        self,
        *,
        actor_user_id: str,
        target_user_id: str | None,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> Any: ...


class ProjectEventQueryPort(Protocol):
    """Compatibility query boundary for Project-scoped event reads."""

    def list_events(self, project_id: ProjectId) -> list[dict[str, Any]]: ...


__all__ = [
    "ProjectAuditPort",
    "ProjectContext",
    "ProjectEventQueryPort",
    "ProjectId",
    "ProjectScope",
]

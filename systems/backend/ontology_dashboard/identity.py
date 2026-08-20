"""Project-membership lifecycle remaining for Phase 3 project migration.

The canonical IAM service lives in :mod:`app.identity`.  This module is not a
compatibility facade: it retains only the Project-owned membership lifecycle
that Issue #54 will move into ``app/project``.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.identity import AuthError, Principal, ProjectMembershipUpdateRequest


class ProjectMembershipRepository(Protocol):
    def list_project_members(
        self, *, organization_id: str, project_id: str
    ) -> list[dict[str, Any]]: ...

    def update_project_membership(
        self,
        *,
        actor_user_id: str,
        organization_id: str,
        project_id: str,
        target_user_id: str,
        status: str,
        roles: list[str],
    ) -> dict[str, Any]: ...


class ProjectIdentityService:
    """Temporary Project-owned membership lifecycle split from Identity."""

    def __init__(self, repository: ProjectMembershipRepository) -> None:
        self.repository = repository

    @staticmethod
    def _require_permission(principal: Principal, permission: str) -> None:
        if permission not in principal.permissions:
            raise AuthError(403, "permission_denied", "이 작업을 수행할 권한이 없습니다.")

    @staticmethod
    def _require_project(principal: Principal, project_id: str) -> None:
        if project_id not in principal.project_scopes:
            raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 요청입니다.")

    def list_project_members(
        self,
        *,
        principal: Principal,
        project_id: str,
    ) -> list[dict[str, Any]]:
        self._require_permission(principal, "admin.users.read")
        self._require_project(principal, project_id)
        return self.repository.list_project_members(
            organization_id=principal.organization_id,
            project_id=project_id,
        )

    def update_project_membership(
        self,
        *,
        principal: Principal,
        project_id: str,
        target_user_id: str,
        request: ProjectMembershipUpdateRequest,
    ) -> dict[str, Any]:
        self._require_permission(principal, "admin.users.manage")
        self._require_project(principal, project_id)
        return self.repository.update_project_membership(
            actor_user_id=principal.user_id,
            organization_id=principal.organization_id,
            project_id=project_id,
            target_user_id=target_user_id,
            status=request.status,
            roles=request.roles,
        )


__all__ = ["ProjectIdentityService", "ProjectMembershipRepository"]

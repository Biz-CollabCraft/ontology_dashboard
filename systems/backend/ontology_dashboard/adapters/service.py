"""Prediction persistence compatibility service retained for Diagnosis phase #58."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.identity import AuthError, Principal
from app.diagnosis.diagnosis_schema import PredictionResult
from app.infra.db.project_repository import SQLiteProjectContextResolver
from app.infra.db.prediction_result_repository import PredictionResultRepository


class AdapterService:
    """Remaining legacy Prediction slice after Dataset ingestion ownership moved to app/dataset."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        prediction_repository: PredictionResultRepository | None = None,
    ) -> None:
        self.database = str(database_path)
        self.path = (
            self.database
            if self.database.startswith(("postgresql://", "postgresql+psycopg://"))
            else Path(self.database)
        )
        self.predictions = prediction_repository or PredictionResultRepository(
            self.path,
            project_context=SQLiteProjectContextResolver(self.path),
        )

    @staticmethod
    def _require_permission(principal: Principal, permission: str) -> None:
        if permission not in principal.permissions:
            raise AuthError(403, "permission_denied", "이 작업을 수행할 권한이 없습니다.")

    @staticmethod
    def _require_active_project(principal: Principal, project_id: str) -> None:
        if project_id not in principal.project_scopes:
            raise AuthError(403, "project_scope_denied", "허용된 Project 범위를 벗어난 요청입니다.")
        if principal.active_project_id != project_id:
            raise AuthError(409, "active_project_mismatch", "먼저 해당 Project를 활성화해야 합니다.")

    @staticmethod
    def _require_workspace(principal: Principal, workspace_id: str) -> None:
        if workspace_id not in principal.workspace_scopes:
            raise AuthError(403, "workspace_scope_denied", "허용된 Workspace 범위를 벗어난 요청입니다.")

    def save_prediction(
        self,
        principal: Principal,
        project_id: str,
        result: PredictionResult,
    ) -> dict[str, Any]:
        self._require_permission(principal, "predictions.ingest")
        self._require_active_project(principal, project_id)
        self._require_workspace(principal, result.workspace_id)
        if result.organization_id != principal.organization_id:
            raise AuthError(403, "tenant_scope_denied", "다른 조직의 Prediction Result는 수집할 수 없습니다.")
        if result.project_id != project_id:
            raise AuthError(
                422,
                "project_context_mismatch",
                "Prediction Result의 Project가 요청 경로와 일치하지 않습니다.",
            )
        return self.predictions.save(result)

    def list_predictions(
        self,
        principal: Principal,
        project_id: str,
        *,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_permission(principal, "datasets.read")
        self._require_active_project(principal, project_id)
        if workspace_id is not None:
            self._require_workspace(principal, workspace_id)
        return self.predictions.list(
            organization_id=principal.organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            limit=max(1, min(limit, 500)),
        )


__all__ = ["AdapterService", "PredictionResult"]

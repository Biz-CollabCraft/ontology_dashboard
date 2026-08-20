"""Typed Dashboard projection over Diagnosis persistence summaries."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .dashboard_schema import DashboardDiagnosisSummary


class _DiagnosisSummarySource(Protocol):
    """Narrow source surface matching the Diagnosis persistence summary query."""

    def list(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> Sequence[Mapping[str, Any]]: ...


class DashboardDiagnosisProjection:
    """Translate persistence rows into the Dashboard-owned typed read model."""

    def __init__(self, source: _DiagnosisSummarySource) -> None:
        self.source = source

    def diagnosis_read_model(
        self,
        *,
        organization_id: str,
        project_id: str,
        workspace_id: str | None = None,
        limit: int = 100,
    ) -> list[DashboardDiagnosisSummary]:
        rows = self.source.list(
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            limit=limit,
        )
        return [self._project(row) for row in rows]

    @staticmethod
    def _project(row: Mapping[str, Any]) -> DashboardDiagnosisSummary:
        return DashboardDiagnosisSummary(
            result_id=str(row["prediction_id"]),
            workspace_id=str(row["workspace_id"]),
            subject_type=str(row["subject_object_type"]),
            subject_id=str(row["subject_object_id"]),
            status=str(row["prediction_status"]),
            model_version=str(row["model_version"]),
            dataset_version=str(row["dataset_version"]),
            created_at=row["created_at"],
        )

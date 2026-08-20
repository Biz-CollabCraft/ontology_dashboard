from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.dashboard import (
    DashboardDiagnosisProjection,
    DashboardDiagnosisSummary,
    DashboardService,
    build_dashboard_router,
)
from app.dashboard.ports import (
    DiagnosisReadModelQueryPort,
    EquipmentStatusQueryPort,
    MaintenanceQueryPort,
)


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "systems" / "backend" / "app" / "dashboard"
LEGACY = ROOT / "systems" / "backend" / "ontology_dashboard"


def test_dashboard_sources_are_physically_canonical() -> None:
    legacy_sources = (
        "dashboard_catalog.py",
        "dashboard_models.py",
        "dashboard_repository.py",
        "dashboard_service.py",
        "routers/dashboards.py",
        "visualizations/__init__.py",
        "visualizations/models.py",
        "visualizations/profiler.py",
        "visualizations/recommender.py",
        "visualizations/semantic.py",
    )
    for relative in legacy_sources:
        assert not (LEGACY / relative).exists(), relative

    for relative in (
        "dashboard_schema.py",
        "catalog.py",
        "dashboard_service.py",
        "dashboard_router.py",
        "ports.py",
        "visualizations/models.py",
        "visualizations/semantic.py",
    ):
        assert (DASHBOARD / relative).is_file(), relative


def test_dashboard_application_does_not_import_legacy_or_infra_implementations() -> None:
    violations: list[str] = []
    for path in DASHBOARD.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            for name in names:
                if name == "ontology_dashboard" or name.startswith("ontology_dashboard."):
                    violations.append(f"{path.name}: {name}")
                if name.startswith("app.infra"):
                    violations.append(f"{path.name}: {name}")
    assert violations == []


def test_dashboard_exposes_owner_query_boundaries_without_recomputing_domain_state() -> None:
    assert DashboardService
    assert build_dashboard_router
    assert EquipmentStatusQueryPort
    assert DiagnosisReadModelQueryPort
    assert MaintenanceQueryPort


def test_dashboard_diagnosis_projection_is_typed_and_hides_persistence_fields() -> None:
    class DiagnosisSummarySource:
        def list(self, **_: object) -> list[dict[str, object]]:
            return [
                {
                    "prediction_id": "prediction-001",
                    "organization_id": "org-a",
                    "project_id": "project-a",
                    "workspace_id": "workspace-a",
                    "subject_object_type": "Equipment",
                    "subject_object_id": "EQ-001",
                    "prediction_status": "warning",
                    "model_version": "model-v1",
                    "dataset_version": "dataset-v3",
                    "created_at": "2026-08-20T06:30:00+00:00",
                    "received_at": "2026-08-20T06:30:01+00:00",
                    "persistence_internal": "must-not-leak",
                }
            ]

    projection = DashboardDiagnosisProjection(DiagnosisSummarySource())
    rows = projection.diagnosis_read_model(
        organization_id="org-a",
        project_id="project-a",
        workspace_id="workspace-a",
    )

    assert rows == [
        DashboardDiagnosisSummary(
            result_id="prediction-001",
            workspace_id="workspace-a",
            subject_type="Equipment",
            subject_id="EQ-001",
            status="warning",
            model_version="model-v1",
            dataset_version="dataset-v3",
            created_at="2026-08-20T06:30:00+00:00",
        )
    ]
    payload = rows[0].model_dump(mode="json")
    assert "received_at" not in payload
    assert "persistence_internal" not in payload
    assert "organization_id" not in payload
    assert "project_id" not in payload


def test_dashboard_diagnosis_query_port_returns_owned_projection_type() -> None:
    annotation = inspect.signature(
        DiagnosisReadModelQueryPort.diagnosis_read_model
    ).return_annotation
    assert "DashboardDiagnosisSummary" in str(annotation)

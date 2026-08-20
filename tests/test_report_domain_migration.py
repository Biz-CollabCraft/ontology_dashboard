from __future__ import annotations

import ast
from pathlib import Path

from app.report import (
    ReportAgent,
    ReportDiagnosisEvidenceSnapshot,
    ReportService,
    build_report_router,
    project_diagnosis_evidence_snapshot,
    render_report,
)
from app.report.ports import (
    DiagnosisEvidencePort,
    MaintenanceHistoryPort,
    ReportGenerationProviderPort,
)
from app.infra.db.report_repository import ReportRepository


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "systems" / "backend" / "app" / "report"
LEGACY = ROOT / "systems" / "backend" / "ontology_dashboard"


def test_report_sources_are_physically_canonical() -> None:
    for relative in (
        "reports.py",
        "llm.py",
        "export_models.py",
        "export_repository.py",
        "export_service.py",
        "routers/exports.py",
    ):
        assert not (LEGACY / relative).exists(), relative

    for relative in (
        "report_schema.py",
        "report_service.py",
        "report_router.py",
        "generation.py",
        "generation_provider.py",
        "ports.py",
    ):
        assert (REPORT / relative).is_file(), relative
    assert (ROOT / "systems/backend/app/infra/db/report_repository.py").is_file()


def test_report_domain_has_no_legacy_or_infra_implementation_imports() -> None:
    violations: list[str] = []
    for path in REPORT.rglob("*.py"):
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


def test_report_public_generation_and_consumer_ports_are_explicit() -> None:
    assert ReportService
    assert ReportRepository
    assert ReportAgent
    assert render_report
    assert build_report_router
    assert ReportGenerationProviderPort
    assert DiagnosisEvidencePort
    assert MaintenanceHistoryPort


def test_report_projects_raw_diagnosis_evidence_into_owned_typed_snapshot() -> None:
    snapshot = project_diagnosis_evidence_snapshot(
        event={
            "event_id": "EVT-1",
            "project_id": "project-a",
            "scenario_id": "scenario-a",
            "equipment": {
                "equipment_id": "EQ-1",
                "display_name": "Lathe 1",
                "line": "Line A",
                "criticality": "high",
                "assigned_engineer": "Engineer A",
                "estimated_downtime_minutes": 120,
            },
            "observation": {"raw_sensor": 123},
            "runtime": {"provider": "internal"},
        },
        evidence={
            "evidence_id": "EVD-1",
            "event_id": "EVT-1",
            "status": "warning",
            "recommended_decision": "request_inspection",
            "confidence": "high",
            "failure_probability": 0.82,
            "threshold": 0.7,
            "predicted_failure_type": "tool_wear_failure",
            "model": {"model_version": "m1", "policy_version": "p1", "artifact": {"secret": True}},
            "lineage": {"project_id": "project-a", "dataset_version": "ds-v1", "fixture_id": "raw"},
            "detected_interval": {"start": "2026-08-20T00:00:00Z", "end": "2026-08-20T00:05:00Z"},
            "top_factors": [
                {
                    "evidence_field_id": "factor.1.tool_wear_min",
                    "feature": "tool_wear_min",
                    "display_name": "Tool wear",
                    "value": 230,
                    "unit": "min",
                    "direction": "high",
                    "contribution": 0.75,
                    "source_type": "observed",
                    "raw_debug": "must-not-leak",
                }
            ],
            "data_quality_warnings": [],
            "generated_at": "2026-08-20T00:05:00Z",
            "observation": {"raw_sensor": 123},
            "history": [{"raw": True}],
        },
        activity={
            "decisions": [{"id": "d1", "event_id": "EVT-1", "actor": "manager", "decision": "inspect", "note": "check", "created_at": "now"}],
            "notes": [],
            "conversations": [],
        },
    )

    assert isinstance(snapshot, ReportDiagnosisEvidenceSnapshot)
    payload = snapshot.model_dump(mode="json")
    assert payload["evidence"]["model_version"] == "m1"
    assert payload["evidence"]["top_factors"][0]["feature"] == "tool_wear_min"
    assert payload["equipment"]["assigned_engineer"] == "Engineer A"
    rendered = str(payload)
    assert "raw_sensor" not in rendered
    assert "estimated_downtime_minutes" not in rendered
    assert "secret" not in rendered

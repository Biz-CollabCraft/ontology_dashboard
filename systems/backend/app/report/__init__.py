"""Canonical Report generation, draft, and export package."""

from .generation import render_report
from .generation_provider import ReportAgent
from .report_exception import ReportConflictError
from .report_router import build_report_router
from .diagnosis_projection import project_diagnosis_evidence_snapshot
from .report_schema import ReportDiagnosisEvidenceSnapshot
from .report_schema import (
    ExportArtifact,
    ExportCheckpoint,
    ExportRequest,
    GroundedReport,
    ReportDraftRecord,
    ReportDraftSaveRequest,
    ReportRequest,
)
from .report_service import ExportService, ReportService

__all__ = [
    "ExportArtifact",
    "ExportCheckpoint",
    "ExportRequest",
    "ExportService",
    "GroundedReport",
    "ReportAgent",
    "ReportConflictError",
    "ReportDraftRecord",
    "ReportDraftSaveRequest",
    "ReportRequest",
    "ReportService",
    "build_report_router",
    "project_diagnosis_evidence_snapshot",
    "ReportDiagnosisEvidenceSnapshot",
    "render_report",
]

"""Canonical Dashboard application/read-model package."""

from .dashboard_exception import (
    DashboardAccessError,
    DashboardNotFoundError,
    DashboardPreferenceConflict,
)
from .dashboard_router import build_dashboard_router
from .diagnosis_projection import DashboardDiagnosisProjection
from .dashboard_schema import DashboardDiagnosisSummary
from .dashboard_service import DashboardService

__all__ = [
    "DashboardAccessError",
    "DashboardNotFoundError",
    "DashboardPreferenceConflict",
    "DashboardDiagnosisProjection",
    "DashboardDiagnosisSummary",
    "DashboardService",
    "build_dashboard_router",
]

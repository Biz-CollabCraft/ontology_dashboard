from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.dataset.dataset_domain import ObservationDatasetQuery
from app.diagnosis.diagnosis_schema import PredictionResult
from app.diagnosis.ports import (
    DiagnosisRuntimeRepositoryPort,
    EquipmentSnapshotQueryPort,
    ObservationDatasetQueryPort,
    PredictionResultRepositoryPort,
)
from app.diagnosis.runtime_service import PredictiveMaintenanceRuntimeService
from app.equipment.equipment_schema import EquipmentCurrentStateQuery
from app.infra.db.prediction_result_repository import PredictionResultRepository


ROOT = Path(__file__).resolve().parents[1]
APP_DIAGNOSIS = ROOT / "systems" / "backend" / "app" / "diagnosis"
LEGACY = ROOT / "systems" / "backend" / "ontology_dashboard"


def test_diagnosis_runtime_sources_are_physically_canonical() -> None:
    for relative in (
        "predictive_maintenance_runtime/models.py",
        "predictive_maintenance_runtime/repository.py",
        "predictive_maintenance_runtime/service.py",
        "product_result_evidence_projection.py",
        "adapters/prediction_repository.py",
        "routers/predictive_maintenance_runtime.py",
    ):
        assert not (LEGACY / relative).exists(), relative

    for relative in (
        "runtime_schema.py",
        "runtime_service.py",
        "ports.py",
        "evidence_projection.py",
        "model_contracts.py",
        "diagnosis_router.py",
    ):
        assert (APP_DIAGNOSIS / relative).is_file(), relative


def test_canonical_diagnosis_has_no_legacy_or_infra_implementation_imports() -> None:
    violations: list[str] = []
    for path in APP_DIAGNOSIS.rglob("*.py"):
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


def test_diagnosis_public_contracts_are_importable() -> None:
    assert PredictionResult.model_fields["prediction_id"]
    assert PredictiveMaintenanceRuntimeService
    assert DiagnosisRuntimeRepositoryPort
    assert EquipmentSnapshotQueryPort is EquipmentCurrentStateQuery
    assert ObservationDatasetQueryPort is ObservationDatasetQuery


def test_prediction_result_repository_port_matches_migrated_adapter_surface() -> None:
    for method_name in ("save", "get_payload", "list"):
        port_method = getattr(PredictionResultRepositoryPort, method_name)
        implementation_method = getattr(PredictionResultRepository, method_name)
        assert tuple(inspect.signature(port_method).parameters) == tuple(
            inspect.signature(implementation_method).parameters
        )

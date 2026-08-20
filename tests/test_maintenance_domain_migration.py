from __future__ import annotations

import ast
from pathlib import Path

from app.maintenance import MaintenanceApplicationService, MaintenanceEvent, WorkOrder
from app.maintenance.ports import (
    DiagnosisResultQueryPort,
    EquipmentStatePatchPort,
    MaintenanceActionExecutionPort,
    MaintenanceEventAccessPort,
)
from app.infra.db.maintenance_repository import MaintenanceRepository


ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / "systems" / "backend" / "app" / "maintenance"
LEGACY = ROOT / "systems" / "backend" / "ontology_dashboard" / "closed_loop"


def test_closed_loop_package_is_physically_migrated() -> None:
    assert not list(LEGACY.glob("*.py"))
    for relative in (
        "__init__.py",
        "maintenance_domain.py",
        "maintenance_schema.py",
        "maintenance_service.py",
        "maintenance_router.py",
        "maintenance_exception.py",
        "integration.py",
        "ports.py",
    ):
        assert (MAINTENANCE / relative).is_file(), relative
    assert (
        ROOT / "systems" / "backend" / "app" / "infra" / "db" / "maintenance_repository.py"
    ).is_file()


def test_maintenance_domain_does_not_import_legacy_or_infra_implementations() -> None:
    violations: list[str] = []
    for path in MAINTENANCE.rglob("*.py"):
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


def test_maintenance_public_contracts_are_importable() -> None:
    assert WorkOrder.model_fields["work_order_id"]
    assert MaintenanceEvent.model_fields["maintenance_event_id"]
    assert MaintenanceRepository
    assert MaintenanceApplicationService
    assert DiagnosisResultQueryPort
    assert EquipmentStatePatchPort
    assert MaintenanceActionExecutionPort
    assert MaintenanceEventAccessPort


def test_shared_manufacturing_router_no_longer_owns_maintenance_endpoints() -> None:
    source = (
        ROOT
        / "systems"
        / "backend"
        / "ontology_dashboard"
        / "routers"
        / "manufacturing.py"
    ).read_text(encoding="utf-8")
    assert '"/events/{event_id}/decision"' not in source
    assert '"/events/{event_id}/notes"' not in source
    assert '"/events/{event_id}/activity"' not in source

    router = (MAINTENANCE / "maintenance_router.py").read_text(encoding="utf-8")
    assert '"/events/{event_id}/decision"' in router
    assert '"/events/{event_id}/notes"' in router
    assert '"/events/{event_id}/activity"' in router

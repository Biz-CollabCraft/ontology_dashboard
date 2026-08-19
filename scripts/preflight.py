#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
from pathlib import Path

REQUIRED_PYTHON_MODULES = [
    "argon2",
    "fastapi",
    "httpx",
    "jsonschema",
    "joblib",
    "numpy",
    "pandas",
    "pydantic",
    "reportlab",
    "sklearn",
    "uvicorn",
    "yaml",
]
REQUIRED_FILES = [
    "systems/backend/ontology_dashboard/__init__.py",
    "systems/backend/ontology_dashboard/app.py",
    "systems/backend/ontology_dashboard/main.py",
    "systems/backend/app/common/runtime_settings.py",
    "systems/backend/app/common/rate_limit.py",
    "systems/backend/app/infra/db/settings.py",
    "systems/backend/app/infra/db/connection.py",
    "systems/backend/app/infra/db/pool.py",
    "systems/backend/app/infra/rate_limit.py",
    "systems/backend/app/infra/external/project3/client.py",
    "systems/backend/app/infra/external/project3/models.py",
    "systems/backend/app/infra/llm/provider.py",
    "systems/backend/app/infra/observability/runtime.py",
    "systems/backend/app/infra/storage/object_storage.py",
    "systems/backend/ontology_dashboard/context.py",
    "systems/backend/ontology_dashboard/contracts.py",
    "systems/backend/app/identity/identity_schema.py",
    "systems/backend/app/identity/identity_repository.py",
    "systems/backend/app/identity/identity_service.py",
    "systems/backend/app/identity/identity_router.py",
    "systems/backend/app/identity/ports.py",
    "systems/backend/app/project/project_domain.py",
    "systems/backend/app/project/project_exception.py",
    "systems/backend/app/project/project_schema.py",
    "systems/backend/app/project/project_repository.py",
    "systems/backend/app/project/project_service.py",
    "systems/backend/app/project/project_router.py",
    "systems/backend/ontology_dashboard/repository.py",
    "systems/backend/ontology_dashboard/service.py",
    "systems/backend/ontology_dashboard/ontology.py",
    "systems/backend/ontology_dashboard/ontology_adapter.py",
    "systems/backend/ontology_dashboard/ontology_repository.py",
    "systems/backend/ontology_dashboard/ontology_service.py",
    "systems/backend/ontology_dashboard/conversation.py",
    "systems/backend/ontology_dashboard/llm.py",
    "systems/backend/ontology_dashboard/reports.py",
    "systems/backend/app/dashboard/dashboard_schema.py",
    "systems/backend/app/dashboard/catalog.py",
    "systems/backend/app/dashboard/dashboard_service.py",
    "systems/backend/app/dashboard/dashboard_router.py",
    "systems/backend/app/dashboard/ports.py",
    "systems/backend/app/infra/db/dashboard_repository.py",
    "systems/backend/ontology_dashboard/analysis_models.py",
    "systems/backend/ontology_dashboard/analysis_repository.py",
    "systems/backend/ontology_dashboard/analysis_service.py",
    "systems/backend/ontology_dashboard/role_workflow_models.py",
    "systems/backend/ontology_dashboard/role_workflow_repository.py",
    "systems/backend/ontology_dashboard/role_workflow_service.py",
    "systems/backend/ontology_dashboard/ontology_planner_models.py",
    "systems/backend/ontology_dashboard/ontology_planner_service.py",
    "systems/backend/ontology_dashboard/export_models.py",
    "systems/backend/ontology_dashboard/export_repository.py",
    "systems/backend/ontology_dashboard/export_service.py",
    "ml/src/ontology_dashboard_manufacturing_ml/__init__.py",
    "ml/src/factory_signal_ml/cli.py",
    "systems/backend/ontology_dashboard/application.py",
    "systems/backend/ontology_dashboard/migrations.py",
    "systems/backend/ontology_dashboard/ontology_instance_repository.py",
    "systems/backend/app/dataset/bundle_contract.py",
    "systems/backend/app/dataset/ingestion/bundle_file_adapter.py",
    "systems/backend/app/dataset/ingestion/predictive_maintenance_v2.py",
    "systems/backend/app/infra/db/postgresql_bundle_ingestion.py",
    "systems/backend/ontology_dashboard/domain_packs/predictive_maintenance/materialization.py",
    "systems/backend/app/diagnosis/runtime_schema.py",
    "systems/backend/app/diagnosis/runtime_service.py",
    "systems/backend/app/diagnosis/ports.py",
    "systems/backend/app/diagnosis/evidence_projection.py",
    "systems/backend/app/diagnosis/diagnosis_router.py",
    "systems/backend/app/infra/db/diagnosis_runtime_repository.py",
    "systems/backend/app/infra/db/prediction_result_repository.py",
    "systems/backend/migrations/postgresql/0011_predictive_maintenance_domain_pack.sql",
    "systems/backend/migrations/postgresql/0012_predictive_maintenance_v3_materialization.sql",
    "systems/backend/migrations/postgresql/0013_project3_graph_projection.sql",
    "systems/backend/migrations/postgresql/0014_predictive_maintenance_replay.sql",
    "systems/backend/migrations/postgresql/0015_identity_permission_overrides.sql",
    "systems/backend/migrations/postgresql/0016_adaptive_modeling_foundation.sql",
    "systems/backend/migrations/postgresql/0017_adaptive_model_registry.sql",
    "systems/backend/ontology_dashboard/modeling/models.py",
    "systems/backend/ontology_dashboard/modeling/repository.py",
    "systems/backend/ontology_dashboard/modeling/service.py",
    "systems/backend/ontology_dashboard/modeling/experiments.py",
    "scripts/run_modeling_experiment_worker.py",
    "contracts/schemas/input-event.schema.json",
    "contracts/schemas/evidence-package.schema.json",
    "contracts/schemas/report.schema.json",
    "contracts/schemas/ui-block.schema.json",
    "contracts/schemas/ontology-core.schema.json",
    "contracts/schemas/dashboard-platform.schema.json",
    "contracts/schemas/role-workspaces.schema.json",
    "contracts/schemas/ontology-planner.schema.json",
    "contracts/schemas/export.schema.json",
    "contracts/schemas/dataset-manifest.schema.json",
    "contracts/schemas/dataset-bundle-manifest.schema.json",
    "contracts/schemas/prediction-result.schema.json",
    "contracts/schemas/project3-graph-projection.schema.json",
    "scripts/ingest_predictive_maintenance_bundle.py",
    "scripts/verify_predictive_maintenance_ingestion.py",
    "scripts/materialize_predictive_maintenance_ontology.py",
    "scripts/verify_predictive_maintenance_materialization.py",
    "evaluation/gold_scenarios.yml",
    "systems/frontend/package.json",
    "systems/frontend/src/features/dashboard/DashboardShell.tsx",
    "systems/frontend/src/features/roles/RoleBoardRenderer.tsx",
    "systems/frontend/src/features/planner/PlannerAssistantBoard.tsx",
    "systems/frontend/src/features/predictive-maintenance/PredictiveMaintenanceReplayPanel.tsx",
]


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    checks: list[dict[str, object]] = []

    for name in REQUIRED_PYTHON_MODULES:
        present = importlib.util.find_spec(name) is not None
        checks.append({"name": f"python:{name}", "pass": present})

    for command in ["node", "npm"]:
        path = shutil.which(command)
        checks.append({"name": f"command:{command}", "pass": path is not None, "path": path})

    for relative in REQUIRED_FILES:
        present = (root / relative).is_file()
        checks.append({"name": f"file:{relative}", "pass": present})

    fixture_count = len(list((root / "data" / "fixtures").glob("GS-*.json")))
    checks.append({"name": "gold_fixture_count", "pass": fixture_count == 8, "value": fixture_count})
    api_port = int(os.getenv("API_PORT", "8100"))
    web_port = int(os.getenv("WEB_PORT", "3100"))
    checks.append({"name": f"port:{api_port}", "pass": port_available(api_port)})
    checks.append({"name": f"port:{web_port}", "pass": port_available(web_port)})

    failed = [check for check in checks if not check["pass"]]
    report = {
        "python": sys.version,
        "root": str(root),
        "checks": checks,
        "failed": failed,
        "pass": not failed,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["pass"] else 1)


if __name__ == "__main__":
    main()

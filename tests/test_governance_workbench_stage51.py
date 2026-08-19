from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dataset import (
    DatasetCatalogService,
    DatasetCreateRequest,
    DatasetVersionCreateRequest,
)
from app.infra.db.dataset_repository import DatasetRepository
from ontology_dashboard.dependencies import get_governance_service
from app.governance import GovernanceAccessError, GovernanceService
from app.identity import CSRF_COOKIE, AuthError, IdentityService
from identity_test_support import build_identity_service
from ontology_dashboard.main import app, get_identity_service, get_service
from ontology_dashboard.migrations import migrate
from ontology_dashboard.role_workflow_service import RoleWorkflowService
from ontology_dashboard.service import ManufacturingPredictiveMaintenanceService

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def setup(tmp_path: Path):
    database = tmp_path / "governance.db"
    migrate(str(database))
    identity = build_identity_service(database, app_env="test", seed_demo=True)
    domain = ManufacturingPredictiveMaintenanceService(ROOT, database_path=database)
    datasets = DatasetRepository(database)
    catalog = DatasetCatalogService(datasets)
    workflows = RoleWorkflowService(domain)
    service = GovernanceService(datasets=datasets, approvals=workflows.repository)

    fde_user = identity.repository.authenticate("fde@ontology.local", "FDE!2026")
    fde = identity.repository.principal(
        fde_user["id"],
        active_project_id="manufacturing-demo-project",
    )
    quality_user = identity.repository.authenticate("quality@ontology.local", "Quality!2026")
    quality = identity.repository.principal(
        quality_user["id"],
        active_project_id="manufacturing-demo-project",
    )

    dataset = catalog.create_dataset(
        principal=fde,
        request=DatasetCreateRequest(
            id="ds-governance-fixture",
            project_id="manufacturing-demo-project",
            workspace_id="manufacturing-demo",
            slug="governance-fixture",
            display_name="Governance Fixture",
            source_type="fixture",
        ),
    )
    version = catalog.create_version(
        principal=fde,
        project_id=dataset.project_id,
        dataset_id=dataset.id,
        request=DatasetVersionCreateRequest(
            source_version="fixture-governance-v1",
            checksum_sha256="b" * 64,
            schema={"fields": [{"name": "equipment_id", "type": "string"}]},
            profile={"null_ratio": 0.0},
            record_count=1,
        ),
    )
    graph = next(
        item
        for item in datasets.list_projections(
            organization_id=fde.organization_id,
            project_id=dataset.project_id,
            dataset_id=dataset.id,
            version_id=version.id,
        )
        if item["store_kind"] == "graph"
    )
    datasets.claim_projection(
        organization_id=fde.organization_id,
        project_id=dataset.project_id,
        projection_id=graph["id"],
    )
    datasets.fail_projection(
        organization_id=fde.organization_id,
        project_id=dataset.project_id,
        projection_id=graph["id"],
        error_message="neo4j fixture unavailable",
    )

    return database, identity, domain, service, fde, quality, graph["id"], version.id


def test_governance_overview_reconstructs_projection_approval_and_lineage_without_agent_surface(setup) -> None:
    _, _, _, service, _, quality, projection_id, version_id = setup
    overview = service.overview(
        principal=quality,
        project_id="manufacturing-demo-project",
        workspace_id="manufacturing-demo",
    )

    assert overview.counts.datasets == 1
    assert overview.counts.dataset_versions == 1
    assert overview.counts.failed_projections == 1
    assert overview.access.can_retry_projection is False
    failed = next(item for item in overview.projections if item.id == projection_id)
    assert failed.status == "failed"
    assert failed.dataset_version_id == version_id
    assert failed.can_retry is False
    assert overview.lineage[0].latest_version_id == version_id
    assert overview.access.tenant_admin_controls_excluded is True
    assert not hasattr(overview, "agent_runs")
    assert not hasattr(service, "agent_run")


def test_projection_retry_requires_governance_permission_and_scope(setup) -> None:
    _, _, _, service, fde, quality, projection_id, _ = setup

    with pytest.raises(GovernanceAccessError) as denied:
        service.retry_projection(
            principal=quality,
            project_id="manufacturing-demo-project",
            workspace_id="manufacturing-demo",
            projection_id=projection_id,
        )
    assert denied.value.code == "permission_denied"

    result = service.retry_projection(
        principal=fde,
        project_id="manufacturing-demo-project",
        workspace_id="manufacturing-demo",
        projection_id=projection_id,
    )
    assert result.projection.status == "pending"

    with pytest.raises(GovernanceAccessError) as scope_error:
        service.overview(
            principal=fde,
            project_id="azure-fleet-maintenance-project",
            workspace_id="manufacturing-demo",
        )
    assert scope_error.value.code == "active_project_mismatch"


@pytest.fixture()
def client(setup):
    _, identity, domain, service, *_ = setup
    app.dependency_overrides[get_identity_service] = lambda: identity
    app.dependency_overrides[get_service] = lambda: domain
    app.dependency_overrides[get_governance_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def login(client: TestClient, email: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    return {"X-CSRF-Token": token}


def test_governance_routes_are_project_scoped_and_retry_is_fde_only(client: TestClient, setup) -> None:
    *_, projection_id, _ = setup
    login(client, "quality@ontology.local", "Quality!2026")
    overview = client.get(
        "/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/governance"
    )
    assert overview.status_code == 200, overview.text
    assert overview.json()["counts"]["failed_projections"] == 1
    removed_agent_surface = client.get(
        "/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/governance/agent-runs/agent-run-governance"
    )
    assert removed_agent_surface.status_code == 404
    denied = client.post(
        f"/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/governance/projections/{projection_id}/retry"
    )
    assert denied.status_code == 403

    client.post("/api/auth/logout")
    csrf = login(client, "fde@ontology.local", "FDE!2026")
    retried = client.post(
        f"/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/governance/projections/{projection_id}/retry",
        headers=csrf,
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["projection"]["status"] == "pending"

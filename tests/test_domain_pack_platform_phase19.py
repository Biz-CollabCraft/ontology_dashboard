from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontology_dashboard.dependencies import get_project_service
from app.identity import IdentityService
from identity_test_support import build_identity_service
from ontology_dashboard.main import app
from ontology_dashboard.main import get_identity_service, get_service
from app.project import ProjectService
from app.infra.db.project_repository import ProjectRepository
from ontology_dashboard.service import ManufacturingPredictiveMaintenanceService


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path: Path):
    database = tmp_path / "phase19.db"
    identity = build_identity_service(database, app_env="test", seed_demo=True)
    domain_service = ManufacturingPredictiveMaintenanceService(ROOT, database_path=database)
    project_service = ProjectService(ProjectRepository(database))
    app.dependency_overrides[get_identity_service] = lambda: identity
    app.dependency_overrides[get_service] = lambda: domain_service
    app.dependency_overrides[get_project_service] = lambda: project_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_generic_domain_pack_registry_and_v4_application_are_retired(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login",
        json={"email": "manager@ontology.local", "password": "Manager!2026"},
    )
    assert login.status_code == 200
    assert client.get("/api/domain-packs").status_code == 404
    assert client.get("/api/platform/domain-packs").status_code == 404
    assert client.get(
        "/api/platform/projects/manufacturing-demo-project/applications/v4"
    ).status_code == 404


def test_ontology_registry_exposes_concepts_without_pack_selection(client: TestClient) -> None:
    login = client.post(
        "/api/auth/login",
        json={"email": "manager@ontology.local", "password": "Manager!2026"},
    )
    assert login.status_code == 200
    response = client.get("/api/ontology/registry")
    assert response.status_code == 200
    payload = response.json()
    assert "domain_packs" not in payload
    assert {"object_types", "link_types", "action_types"} == set(payload)

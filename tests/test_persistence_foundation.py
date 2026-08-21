from __future__ import annotations

import sqlite3
from pathlib import Path

from app.identity import IdentityService
from app.infra.db.migrations import migrate
from app.infra.db.ontology_action_repository import OntologyActionRepository
from app.infra.db.ontology_instance_repository import OntologyInstanceRepository
from app.infra.db.project_repository import SQLiteProjectContextResolver
from app.ontology.ontology_service import OntologyService
from app.infra.db.role_workflow_repository import RoleWorkflowRepository
from app.dependencies import build_manufacturing_service
from identity_test_support import build_identity_service

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "manufacturing-demo"


def test_migrations_are_idempotent_and_create_outbox(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    first = migrate(str(database))
    second = migrate(str(database))
    assert first == [
        "0001_platform_core",
        "0002_project_layer",
        "0003_project_scoped_operations",
        "0004_prediction_results",
        "0005_project_memberships",
        "0006_outbox_worker",
        "0007_analysis_engine",
        "0008_dataset_projection_pipeline",
            "0009_agent_orchestration",
            "0010_analysis_run_lifecycle",
            "0011_adaptive_modeling_foundation",
            "0012_adaptive_model_registry",
            "0019_tenant_transaction_convergence",
            "0020_enterprise_identity_access",
            "0021_distributed_execution_runtime",
            "0022_object_storage_artifact_governance",
            "0023_production_connectors_ingestion",
            "0024_ontology_interfaces_actions_functions",
            "0025_global_branching_lineage_markings",
            "0026_object_views_search_application_runtime",
            "0027_scalable_pipeline_analysis",
            "0028_continuous_mlops_runtime",
            "0029_governed_event_automation",
            "0030_closed_loop_operations",
        ]
    assert second == []

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "schema_migrations" in tables
    assert "transactional_outbox" in tables
    assert "ontology_schema_versions" in tables
    assert "ontology_source_mappings" in tables
    assert {"analyses", "analysis_boards", "analysis_runs"} <= tables
    assert {
        "closed_loop_recommendations",
        "closed_loop_recommendation_decisions",
        "closed_loop_work_orders",
        "closed_loop_maintenance_actions",
        "closed_loop_maintenance_events",
        "closed_loop_equipment_state",
        "closed_loop_activities",
        "closed_loop_idempotency_records",
    } <= tables
    with sqlite3.connect(database) as connection:
        activity_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(closed_loop_activities)")
        }
    assert {
        "equipment_id",
        "recommendation_id",
        "work_order_id",
        "maintenance_action_id",
        "maintenance_event_id",
        "actor_user_id",
        "actor_display_name",
        "before_status",
        "after_status",
        "created_at",
    } <= activity_columns
    with sqlite3.connect(database) as connection:
        maintenance_action_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(closed_loop_maintenance_actions)")
        }
        maintenance_event_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(closed_loop_maintenance_events)")
        }
    assert "restart_at" in maintenance_action_columns
    assert "restart_at" not in maintenance_event_columns


def test_ontology_adapter_materializes_persistent_objects_and_links(tmp_path: Path) -> None:
    database = tmp_path / "ontology.db"
    build_identity_service(database, app_env="test", seed_demo=True)
    service = build_manufacturing_service(database, root=ROOT)
    project_context = SQLiteProjectContextResolver(database)
    ontology = OntologyService(
        service,
        action_repository=OntologyActionRepository(database, project_context=project_context),
        instance_repository=OntologyInstanceRepository(database, project_context=project_context),
    )

    result = ontology.query_objects(
        workspace_id=WORKSPACE,
        object_type="risk_event",
        search=None,
    )
    assert result["total"] == 8

    repository = OntologyInstanceRepository(database, project_context=project_context)
    assert len(repository.list_objects(workspace_id=WORKSPACE)) >= 8
    assert len(repository.list_links(workspace_id=WORKSPACE)) >= 8
    ingestion = repository.latest_ingestion(workspace_id=WORKSPACE)
    assert ingestion is not None
    assert ingestion["source_system"] == "manufacturing-predictive-maintenance"


def test_field_action_and_outbox_are_committed_together(tmp_path: Path) -> None:
    database = tmp_path / "outbox.db"
    build_identity_service(database, app_env="test", seed_demo=True)
    migrate(str(database))
    repository = RoleWorkflowRepository(database)

    result = repository.record_field_action(
        workspace_id=WORKSPACE,
        event_id="EVT-GS-002",
        action="complete",
        actor_user_id="test-user",
        actor_display_name="Test User",
        payload={"checklist": ["visual inspection"], "measurements": {}},
    )
    assert result["status"] == "completed"

    with sqlite3.connect(database) as connection:
        action_count = connection.execute(
            "SELECT COUNT(*) FROM field_task_actions WHERE id=?",
            (result["id"],),
        ).fetchone()[0]
        outbox = connection.execute(
            """
            SELECT organization_id,workspace_id,aggregate_id,event_type,status
            FROM transactional_outbox
            WHERE aggregate_type='field_task' AND aggregate_id=?
            """,
            ("EVT-GS-002",),
        ).fetchone()
    assert action_count == 1
    assert outbox == (
        "org-ontology-demo",
        WORKSPACE,
        "EVT-GS-002",
        "field_task.complete",
        "pending",
    )

"""Disposable synthetic Product Result fixture. No production or provider access."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ORG = "org-ontology-demo"
PROJECT = "manufacturing-demo-project"
WORKSPACE = "manufacturing-demo"
ASSETS = [f"{kind}-{n:03d}" for n in range(1, 6) for kind in ("CMP", "CNC")]


def _guard(database):
    parsed = urlsplit(database)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.port != 55433 or not parsed.path[1:].startswith("ontology_p0_"):
        raise ValueError("fixture requires dedicated ontology_p0_* database at localhost:55433")


def _scope(connection):
    connection.execute("SELECT set_config('app.organization_id',%s,true)", (ORG,))
    connection.execute("SELECT set_config('app.project_id',%s,true)", (PROJECT,))


def setup(database, work_dir=None):
    """Migrate and ingest ten valid synthetic assets into a fresh disposable DB."""
    _guard(database)
    from app.infra.db.migrations import migrate
    from app.dataset.ingestion import BundleFileAdapter, PredictiveMaintenanceCanonicalV2Adapter
    from app.infra.db.postgresql_bundle_ingestion import PostgreSQLPredictiveMaintenanceBundleIngestor
    from tests.test_predictive_maintenance_bundle_adapter import create_small_package, refresh_contracts, write_csv, write_jsonl

    applied = migrate(database)
    with psycopg.connect(database) as connection:
        connection.execute("INSERT INTO organizations(id,slug,name) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (ORG, ORG, "P0 synthetic organization"))
        connection.execute("INSERT INTO projects(id,organization_id,slug,display_name,domain_pack_code) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (PROJECT, ORG, PROJECT, "P0 synthetic project", "predictive-maintenance"))
        connection.execute("INSERT INTO workspaces(id,organization_id,project_id,slug,display_name,domain_pack) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (WORKSPACE, ORG, PROJECT, WORKSPACE, "P0 synthetic workspace", "predictive-maintenance"))
    if work_dir is None:
        work_dir = Path(__file__).parent / "work" / urlsplit(database).path[1:]
    package = create_small_package(Path(work_dir))
    for path in sorted(package.rglob("*")):
        if path.suffix not in {".csv", ".jsonl"}:
            continue
        if path.suffix == ".csv":
            with path.open(newline="") as stream:
                rows = list(csv.DictReader(stream))
        else:
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        expanded = []
        for n in range(1, 6):
            for row in rows:
                text = json.dumps(row)
                for prefix in ("CMP", "CNC", "PRD", "MNT"):
                    text = text.replace(prefix + "-001", f"{prefix}-{n:03d}")
                expanded.append(json.loads(text))
        (write_csv if path.suffix == ".csv" else write_jsonl)(path, expanded)
    refresh_contracts(package)
    manifest = PredictiveMaintenanceCanonicalV2Adapter.build_manifest(
        package, organization_id=ORG, project_id=PROJECT,
        workspace_id=WORKSPACE, manifest_id="ontology-p0-synthetic-ten-assets")
    validation = BundleFileAdapter(allowed_roots=[package]).validate(manifest)
    if validation.status != "completed" or validation.quarantined_record_count:
        raise RuntimeError(str(validation))
    result = PostgreSQLPredictiveMaintenanceBundleIngestor(database).ingest_validated_bundle(manifest=manifest, validation=validation)
    return {
        "assets": list(ASSETS), "dataset_version_id": result.dataset_version_id,
        "fixture_sha256": manifest.bundle_checksum_sha256,
        "migrations": list(applied), "organization_id": ORG, "project_id": PROJECT,
        "workspace_id": WORKSPACE, "fixture_path": str(package),
        "source_record_count": validation.source_record_count,
    }


def emit(database, event):
    """Append one synthetic result at Product Result boundary; exact repeats reuse ID."""
    _guard(database)
    asset = event["asset_id"]
    if asset not in ASSETS:
        raise ValueError(asset)
    event_id = event["event_id"]
    observed_at = event.get("observed_at") or datetime.now(timezone.utc).isoformat()
    probability = float(event.get("failure_probability", 0.30))
    source_sha = event.get("source_sha256") or hashlib.sha256(json.dumps(event, sort_keys=True, default=str).encode()).hexdigest()
    with psycopg.connect(database, row_factory=dict_row) as connection:
        _scope(connection)
        source = connection.execute(
            "SELECT * FROM pm_prediction_snapshots WHERE organization_id=%s AND project_id=%s AND workspace_id=%s AND asset_id=%s ORDER BY observed_at DESC LIMIT 1",
            (ORG, PROJECT, WORKSPACE, asset)).fetchone()
        if source is None:
            raise ValueError("missing synthetic source prediction")
        existing = connection.execute("SELECT source_sha256,observed_at FROM pm_result_artifacts WHERE dataset_version_id=%s AND artifact_id=%s", (source["dataset_version_id"], event_id)).fetchone()
        if existing:
            source_sha = existing["source_sha256"]
            observed_at = existing["observed_at"].isoformat()
        else:
            factors = [{"rank": 1, "feature": "feature-a", "feature_value": 1.0,
                        "signed_contribution": 0.2, "absolute_contribution": 0.2,
                        "direction": "positive", "explanation_method": "linear",
                        "source_type": "derived_model_output"}]
            prediction_result_id = "P0-" + hashlib.sha256(event_id.encode()).hexdigest()
            provenance = {"prediction_id": source["prediction_id"],
                          "model_version": source["model_version"],
                          "dataset_version": source["dataset_version_id"],
                          "source_type": "product_runtime_inference",
                          "canonical_source_mutated": False}
            payload = {
                "artifact_id": event_id, "artifact_type": "predictive_maintenance_result",
                "schema_version": "result-artifact-v1.0", "asset_id": asset,
                "asset_type": source["asset_type"], "observed_at": observed_at,
                "generated_at": observed_at, "prediction_horizon_hours": 24,
                "prediction_task": "binary_failure_within_horizon",
                "failure_probability": probability, "predicted_failure_type": "no_significant_risk",
                "status_grade": "normal", "confidence": source["confidence"],
                "top_factors": factors, "recommended_action": {},
                "provenance": provenance}
            from app.diagnosis.evidence import validate_product_result_artifact
            validate_product_result_artifact(payload)
            connection.execute(
                """INSERT INTO prediction_results(prediction_id,organization_id,
                project_id,workspace_id,subject_object_type,subject_object_id,
                prediction_status,model_version,dataset_version,payload_json,created_at,received_at)
                VALUES (%s,%s,%s,%s,'equipment',%s,'normal',%s,%s,%s,%s,now())""",
                (prediction_result_id, ORG, PROJECT, WORKSPACE, asset,
                 source["model_version"], "canonical-independent-v1.0",
                 Jsonb(payload), observed_at))
            connection.execute(
                """INSERT INTO pm_result_artifacts(
                organization_id,project_id,workspace_id,dataset_version_id,artifact_id,
                prediction_id,prediction_result_id,asset_id,asset_type,observed_at,
                prediction_horizon_hours,prediction_task,failure_probability,
                predicted_failure_type,status_grade,confidence,top_factors,
                recommended_action,provenance,schema_version,model_version,source_sha256)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,24,
                'binary_failure_within_horizon',%s,'no_significant_risk','normal',
                %s,%s,%s,%s,'result-artifact-v1.0',%s,%s)""",
                (ORG, PROJECT, WORKSPACE, source["dataset_version_id"], event_id,
                 source["prediction_id"], prediction_result_id, asset,
                 source["asset_type"], observed_at, probability, source["confidence"],
                 Jsonb(factors), Jsonb({}), Jsonb(provenance),
                 source["model_version"], source_sha))
    return {"source_kind": "live_result", "asset_id": asset,
            "event_id": event_id, "dataset_version_id": source["dataset_version_id"],
            "source_sha256": source_sha, "observed_at": observed_at}


def mutate_context(database, candidate, version=1):
    """Append a real synthetic owner production context effective at this event."""
    _guard(database)
    from copy import deepcopy
    from datetime import timedelta
    from app.infra.db.operational_context_repository import ContextSnapshot, OperationalContextRepository
    from scripts.build_operational_context_demo_seed import build_seed
    row = deepcopy(next(x for x in build_seed(ORG, PROJECT, WORKSPACE) if x["owner_domain"] == "production"))
    observed = datetime.fromisoformat(str(candidate["observed_at"]).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    revision = int(version)
    updated = observed - timedelta(seconds=1000-revision)
    asset = candidate["asset_id"]
    row.update(asset_id=asset, evidence_snapshot_id=candidate["event_id"],
               source_version=f"ontology-p0-{candidate['event_id']}-v{revision}",
               source_ref=f"synthetic_demo:ontology-p0:{candidate['event_id']}:v{revision}",
               source_updated_at=updated.isoformat(),
               valid_from=(observed-timedelta(days=1)).isoformat(),
               valid_to=(observed+timedelta(days=1)).isoformat(), max_age_seconds=172800)
    for order in row["payload"]["production_orders"]:
        order["assigned_asset_id"] = asset
        order["completed_quantity"] = 600 + revision
        order["due_at"] = (observed+timedelta(hours=8)).isoformat()
    for item in row["payload"]["wip"]:
        item["asset_id"] = asset
    for item in row["payload"]["alternative_resources"]:
        item["available_from"] = (observed+timedelta(hours=1)).isoformat()
        item["available_to"] = (observed+timedelta(hours=5)).isoformat()
    return OperationalContextRepository(database).import_snapshots([ContextSnapshot.model_validate(row)])


def restricted_runtime_database(database):
    """Grant the dedicated runtime role access without ownership or RLS bypass."""
    _guard(database)
    from psycopg import sql
    from urllib.parse import urlunsplit
    role, password = "ontology_p0_app", "ontology-p0-app-synthetic-only"
    with psycopg.connect(database, autocommit=True) as connection:
        exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
        if not exists:
            connection.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD {}").format(sql.Identifier(role), sql.Literal(password)))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(role)))
    parsed = urlsplit(database)
    runtime = urlunsplit((parsed.scheme, f"{role}:{password}@{parsed.hostname}:{parsed.port}", parsed.path, parsed.query, ""))
    with psycopg.connect(runtime) as connection:
        flags = connection.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        assert flags == (False, False)
        _scope(connection)
        visible = connection.execute("SELECT count(*) FROM pm_assets").fetchone()[0]
        connection.execute("SELECT set_config('app.project_id','ontology-p0-wrong-scope',true)")
        hidden = connection.execute("SELECT count(*) FROM pm_assets").fetchone()[0]
        if visible != 10 or hidden != 0:
            raise AssertionError(f"RLS probe failed visible={visible} hidden={hidden}")
    return runtime


def snapshot_business(database):
    """Digest scoped business tables, excluding intentional input and summary/audit writes."""
    _guard(database)
    tables = ["closed_loop_recommendations", "closed_loop_recommendation_decisions",
              "closed_loop_work_orders", "closed_loop_maintenance_actions",
              "closed_loop_maintenance_events", "closed_loop_equipment_state",
              "closed_loop_activities", "closed_loop_idempotency_records",
              "closed_loop_inspection_results"]
    result = {}
    with psycopg.connect(database) as connection:
        _scope(connection)
        for table in tables:
            rows = connection.execute(
                "SELECT row_to_json(t)::text FROM " + table + " t WHERE organization_id=%s AND project_id=%s",
                (ORG, PROJECT)).fetchall()
            texts = sorted(row[0] for row in rows)
            result[table] = {"count": len(texts), "sha256": hashlib.sha256("\n".join(texts).encode()).hexdigest()}
    return result

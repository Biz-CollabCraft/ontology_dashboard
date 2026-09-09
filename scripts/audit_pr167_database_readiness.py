"""Inspect configured team DB without migrations, writes, or LLM calls."""
import argparse
import json
from pathlib import Path
from datetime import UTC, datetime
from dotenv import dotenv_values
import psycopg

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = dotenv_values(args.env_file)
    prefix = "ONTOLOGY_DASHBOARD_TEAM_DB_"
    kwargs = {key: config[prefix+name] for key, name in (
        ("host","HOST"),("port","PORT"),("dbname","NAME"),("user","USER"),
        ("password","PASSWORD"),("sslmode","SSLMODE")) if config.get(prefix+name)}
    queries = {
        "rls_state": "SELECT c.relname,c.relrowsecurity,c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=\'public\' AND c.relname IN (\'pm_result_artifacts\',\'operational_context_sources\')",
        "role_privileges": "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user",
        "session_scope": "SELECT current_setting(\'app.organization_id\',true),current_setting(\'app.project_id\',true)",
        "result_counts": "SELECT count(*) AS rows, count(DISTINCT asset_id) AS assets, min(observed_at) AS earliest, max(observed_at) AS latest FROM pm_result_artifacts",
        "observation_time_counts": "SELECT count(*) FILTER (WHERE observed_at <= CURRENT_TIMESTAMP) AS at_or_before_now, count(*) FILTER (WHERE observed_at > CURRENT_TIMESTAMP) AS future FROM pm_result_artifacts",
        "result_source_types": "SELECT provenance->>\'source_type\',count(*) FROM pm_result_artifacts GROUP BY 1",
        "dataset_model_counts": "SELECT dataset_version_id, model_version, count(*) FROM pm_result_artifacts GROUP BY 1,2 ORDER BY count(*) DESC LIMIT 12",
        "context_source_counts": "SELECT owner_domain, source_classification, count(*) FROM operational_context_sources GROUP BY 1,2 ORDER BY 1,2",
        "context_binding_count": "SELECT count(*) FROM operational_context_bindings",
        "summary_versions": "SELECT summary_schema_version, prompt_version, model_version, status, count(*) FROM agent_review_summaries GROUP BY 1,2,3,4 ORDER BY count(*) DESC LIMIT 20",
        "provenance_key_counts": "SELECT key, count(*) FROM pm_result_artifacts, jsonb_object_keys(provenance) AS key GROUP BY key ORDER BY key",
    }
    report = {"started_at": datetime.now(UTC).isoformat(), "mode": "read_only_team_database_inventory",
              "external_llm_calls": 0, "database_writes": 0, "queries": queries}
    with psycopg.connect(**kwargs, connect_timeout=8,
        options="-c default_transaction_read_only=on -c statement_timeout=15000") as conn:
        with conn.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            # Same explicit scope as scripts/connect_team_db.sh; RLS remains on.
            for setting, key, default in (
                ("app.organization_id", "ORGANIZATION_ID", "org-ontology-demo"),
                ("app.project_id", "PROJECT_ID", "manufacturing-demo-project"),
                ("app.workspace_id", "WORKSPACE_ID", "manufacturing-demo"),
            ):
                cursor.execute("SELECT set_config(%s,%s,true)", (setting, config.get("ONTOLOGY_DASHBOARD_TEAM_"+key) or default))
            cursor.execute("SHOW transaction_read_only")
            report["transaction_read_only"] = cursor.fetchone()[0]
            for name, query in queries.items():
                cursor.execute(query)
                report[name] = cursor.fetchall()
        conn.rollback()
    report["finished_at"] = datetime.now(UTC).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str)+"\n")
    print(json.dumps(report, ensure_ascii=False, default=str))
if __name__ == "__main__":
    main()

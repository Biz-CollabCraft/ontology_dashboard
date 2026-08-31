from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_cost_option_recommendation_migrations_enforce_grouped_lineage() -> None:
    sqlite_sql = (
        ROOT
        / "systems"
        / "backend"
        / "migrations"
        / "sqlite"
        / "0036_cost_option_recommendation_lineage.sql"
    ).read_text(encoding="utf-8")
    postgresql_sql = (
        ROOT
        / "systems"
        / "backend"
        / "migrations"
        / "postgresql"
        / "0038_cost_option_recommendation_lineage.sql"
    ).read_text(encoding="utf-8")

    for sql in (sqlite_sql, postgresql_sql):
        assert "source_cost_analysis_id" in sql
        assert "source_cost_option_id" in sql
        assert "source_action_candidate_id" in sql
        assert "closed_loop_maintenance_cost_analyses" in sql
        assert "product_result_projection" in sql
        assert "operations_manual" in sql

    assert "CREATE TRIGGER" in sqlite_sql
    assert "invalid recommendation cost lineage" in sqlite_sql
    assert "closed_loop_recommendations_cost_lineage_check" in postgresql_sql

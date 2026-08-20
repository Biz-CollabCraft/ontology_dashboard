"""Canonical Maintenance persistence boundary for producer recommendations."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.maintenance import OperationalRecommendedAction


class ProjectScope(Protocol):
    organization_id: str
    project_id: str
    workspace_id: str


class ProjectContextResolverPort(Protocol):
    def resolve(
        self,
        workspace_id: str,
        *,
        expected_organization_id: str | None = None,
        expected_project_id: str | None = None,
        connection: Any | None = None,
    ) -> ProjectScope: ...


class MaintenanceRepository:
    def __init__(self, database: str | Path, *, project_context: ProjectContextResolverPort) -> None:
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.project_context = project_context
        with self._connect() as connection:
            self._ensure_schema(connection)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS closed_loop_recommendations (
              recommendation_id TEXT PRIMARY KEY,
              organization_id TEXT NOT NULL,
              project_id TEXT NOT NULL,
              workspace_id TEXT NOT NULL,
              event_id TEXT NOT NULL,
              asset_id TEXT NOT NULL,
              equipment_id TEXT NOT NULL,
              recommendation_origin TEXT NOT NULL,
              status TEXT NOT NULL,
              materialization_strategy TEXT NOT NULL DEFAULT 'runtime_generated',
              source_action_id TEXT NOT NULL,
              source_product_result_id TEXT NOT NULL,
              source_evidence_id TEXT NOT NULL,
              source_schema_version TEXT NOT NULL,
              source_policy_version TEXT NOT NULL,
              label TEXT NOT NULL,
              kind TEXT NOT NULL,
              requires_human_approval INTEGER NOT NULL,
              basis_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              CHECK(asset_id=equipment_id),
              UNIQUE(organization_id,project_id,workspace_id,source_product_result_id,source_action_id)
            );
            CREATE TABLE IF NOT EXISTS closed_loop_recommendation_decisions (
              decision_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS closed_loop_work_orders (
              work_order_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS closed_loop_maintenance_actions (
              maintenance_action_id TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS closed_loop_maintenance_events (
              maintenance_event_id TEXT PRIMARY KEY
            );
            """
        )

    def save_recommendation(
        self,
        recommendation: OperationalRecommendedAction,
        *,
        recorded_at: datetime | None = None,
    ) -> OperationalRecommendedAction:
        scope = self.project_context.resolve(
            recommendation.workspace_id,
            expected_organization_id=recommendation.organization_id,
            expected_project_id=recommendation.project_id,
        )
        if (
            scope.organization_id != recommendation.organization_id
            or scope.project_id != recommendation.project_id
            or scope.workspace_id != recommendation.workspace_id
        ):
            raise ValueError("recommendation scope does not match project context")
        now = (recorded_at or datetime.now(timezone.utc)).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO closed_loop_recommendations (
                  recommendation_id,organization_id,project_id,workspace_id,event_id,
                  asset_id,equipment_id,recommendation_origin,status,materialization_strategy,
                  source_action_id,source_product_result_id,source_evidence_id,source_schema_version,
                  source_policy_version,label,kind,requires_human_approval,basis_json,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    recommendation.recommendation_id,
                    recommendation.organization_id,
                    recommendation.project_id,
                    recommendation.workspace_id,
                    recommendation.event_id,
                    recommendation.asset_id,
                    recommendation.equipment_id,
                    recommendation.recommendation_origin,
                    recommendation.status.value,
                    recommendation.materialization_strategy.value,
                    recommendation.source_action_id,
                    recommendation.source_product_result_id,
                    recommendation.source_evidence_id,
                    recommendation.source_schema_version,
                    recommendation.source_policy_version,
                    recommendation.label,
                    recommendation.kind,
                    recommendation.requires_human_approval,
                    self._json(list(recommendation.basis)),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM closed_loop_recommendations
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND source_product_result_id=? AND source_action_id=?
                """,
                (
                    recommendation.organization_id,
                    recommendation.project_id,
                    recommendation.workspace_id,
                    recommendation.source_product_result_id,
                    recommendation.source_action_id,
                ),
            ).fetchone()
        if row is None:
            raise RuntimeError("recommendation was not persisted")
        stored = self._from_row(row)
        if stored != recommendation:
            raise ValueError("recommendation materialization conflicts with existing data")
        return stored

    def operational_side_effect_counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {
                "recommendations": connection.execute("SELECT COUNT(*) FROM closed_loop_recommendations").fetchone()[0],
                "decisions": connection.execute("SELECT COUNT(*) FROM closed_loop_recommendation_decisions").fetchone()[0],
                "work_orders": connection.execute("SELECT COUNT(*) FROM closed_loop_work_orders").fetchone()[0],
                "maintenance_actions": connection.execute("SELECT COUNT(*) FROM closed_loop_maintenance_actions").fetchone()[0],
                "maintenance_events": connection.execute("SELECT COUNT(*) FROM closed_loop_maintenance_events").fetchone()[0],
            }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OperationalRecommendedAction:
        return OperationalRecommendedAction(
            organization_id=row["organization_id"],
            project_id=row["project_id"],
            workspace_id=row["workspace_id"],
            recommendation_id=row["recommendation_id"],
            recommendation_origin=row["recommendation_origin"],
            status=row["status"],
            materialization_strategy=row["materialization_strategy"],
            asset_id=row["asset_id"],
            equipment_id=row["equipment_id"],
            event_id=row["event_id"],
            source_action_id=row["source_action_id"],
            source_product_result_id=row["source_product_result_id"],
            source_evidence_id=row["source_evidence_id"],
            source_schema_version=row["source_schema_version"],
            source_policy_version=row["source_policy_version"],
            label=row["label"],
            kind=row["kind"],
            requires_human_approval=bool(row["requires_human_approval"]),
            basis=tuple(json.loads(row["basis_json"])),
        )


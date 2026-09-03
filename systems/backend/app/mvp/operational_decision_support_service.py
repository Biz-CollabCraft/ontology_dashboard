"""Application facade for the bounded read-only operational decision support slice."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from app.mvp.operational_context_contract import OperationalRequestIdentity
from app.mvp.operational_context_ports import (
    FixtureMaintenanceReadinessContextReadPort,
    FixtureProductionDecisionContextReadPort,
    FixtureQualityDeliveryContextReadPort,
)
from app.mvp.operational_decision_agent import (
    BoundedOperationalDecisionAgent,
    OperationalAgentIntent,
    OperationalAgentRequest,
)
from app.mvp.operational_decision_brief import (
    DecisionBriefRole,
    OperationalDecisionBrief,
    compose_operational_decision_brief,
)
from app.mvp.operational_decision_materialization import (
    OperationalBriefSnapshot,
    materialize_operational_brief,
)
from app.mvp.operational_impact_simulation import (
    ImpactOption,
    ImpactSimulationAssumptions,
)


@dataclass(frozen=True)
class DecisionSupportTrace:
    status: str
    reason: str | None
    reused: bool
    workflow_run_id: str | None
    context_version_set: dict[str, str]
    temporal_validation: str
    trajectory: tuple[dict[str, Any], ...] = ()


@dataclass
class OperationalDecisionSupportService:
    root: Path
    database_path: Path | None = None
    _snapshots: dict[str, OperationalBriefSnapshot] = field(default_factory=dict)
    _runs: list[dict[str, Any]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def __post_init__(self) -> None:
        if self.database_path is None:
            return
        with sqlite3.connect(self.database_path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS operational_decision_briefs (
                    cache_key TEXT PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    stored_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_decision_workflow_runs (
                    workflow_run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    run_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operational_decision_runs_lookup_idx
                ON operational_decision_workflow_runs (
                    project_id, asset_id, status, recorded_at DESC
                );
                """
            )

    def cached_brief(
        self,
        *,
        identity: OperationalRequestIdentity,
        actor_role: DecisionBriefRole,
    ) -> tuple[OperationalDecisionBrief | None, DecisionSupportTrace]:
        key = self._cache_key(identity=identity, actor_role=actor_role)
        snapshot = self._load_snapshot(key)
        if snapshot is None:
            return None, DecisionSupportTrace(
                status="pending",
                reason="not_materialized",
                reused=False,
                workflow_run_id=None,
                context_version_set={},
                temporal_validation="not_measured",
            )
        return snapshot.brief, DecisionSupportTrace(
            status="completed",
            reason=None,
            reused=True,
            workflow_run_id=None,
            context_version_set=snapshot.context_version_set,
            temporal_validation="passed",
        )

    def materialize(
        self,
        *,
        identity: OperationalRequestIdentity,
        actor_role: DecisionBriefRole,
        risk_status: str,
        trigger: str,
        now: datetime | None = None,
    ) -> tuple[OperationalDecisionBrief, DecisionSupportTrace]:
        now = now or datetime.now(timezone.utc)
        key = self._cache_key(identity=identity, actor_role=actor_role)
        existing = self._load_snapshot(key)
        if existing is not None and trigger == "manual_materialization":
                return existing.brief, DecisionSupportTrace(
                    status="completed",
                    reason=None,
                    reused=True,
                    workflow_run_id=None,
                    context_version_set=existing.context_version_set,
                    temporal_validation="passed",
                )

        request = OperationalAgentRequest(
            identity=identity,
            actor_role=actor_role.value,
            intent=OperationalAgentIntent.MAINTENANCE_TIMING_DECISION,
            risk_status=risk_status,
        )
        run_id = f"ODR-{uuid.uuid4().hex[:16]}"
        try:
            result = self._agent(identity).run(
                request=request,
                retrieved_at=identity.decision_as_of,
                validated_at=identity.decision_as_of,
            )
            brief = compose_operational_decision_brief(request=request, result=result)
            snapshot = materialize_operational_brief(
                request=request,
                result=result,
                brief=brief,
                stored_at=now,
            )
            trajectory = tuple(
                step.model_dump(mode="json") for step in result.trajectory
            )
            trace = DecisionSupportTrace(
                status="completed",
                reason=None,
                reused=False,
                workflow_run_id=run_id,
                context_version_set=result.context_version_set,
                temporal_validation=(
                    "passed"
                    if result.temporal_validation.get("valid") is True
                    else "failed"
                ),
                trajectory=trajectory,
            )
            run = {
                "workflow_run_id": run_id,
                "asset_id": identity.asset_id,
                "project_id": identity.project_id,
                "status": trace.status,
                "reason": trace.reason,
                "context_version_set": trace.context_version_set,
                "temporal_validation": trace.temporal_validation,
                "trajectory": list(trajectory),
                "recorded_at": now.isoformat(),
            }
            self._store_snapshot_and_run(key=key, snapshot=snapshot, run=run)
            return brief, trace
        except (ValueError, RuntimeError, TimeoutError) as exc:
            self._store_run(
                {
                    "workflow_run_id": run_id,
                    "asset_id": identity.asset_id,
                    "project_id": identity.project_id,
                    "status": "failed",
                    "reason": type(exc).__name__,
                    "context_version_set": {},
                    "temporal_validation": "failed",
                    "trajectory": [],
                    "recorded_at": now.isoformat(),
                }
            )
            raise

    def workflow_runs(
        self,
        *,
        project_id: str,
        asset_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if self.database_path is not None:
            clauses = ["project_id = ?"]
            values: list[Any] = [project_id]
            if asset_id is not None:
                clauses.append("asset_id = ?")
                values.append(asset_id)
            if status is not None:
                clauses.append("status = ?")
                values.append(status)
            values.append(limit)
            with sqlite3.connect(self.database_path) as connection:
                rows = connection.execute(
                    f"""
                    SELECT run_json
                    FROM operational_decision_workflow_runs
                    WHERE {' AND '.join(clauses)}
                    ORDER BY recorded_at DESC
                    LIMIT ?
                    """,
                    values,
                ).fetchall()
            return [json.loads(row[0]) for row in rows]
        with self._lock:
            rows = list(reversed(self._runs))
        return [
            row
            for row in rows
            if row["project_id"] == project_id
            and (asset_id is None or row["asset_id"] == asset_id)
            and (status is None or row["status"] == status)
        ][:limit]

    def _load_snapshot(self, key: str) -> OperationalBriefSnapshot | None:
        if self.database_path is None:
            with self._lock:
                return self._snapshots.get(key)
        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM operational_decision_briefs WHERE cache_key = ?",
                (key,),
            ).fetchone()
        return (
            OperationalBriefSnapshot.model_validate_json(row[0])
            if row is not None
            else None
        )

    def _store_snapshot_and_run(
        self,
        *,
        key: str,
        snapshot: OperationalBriefSnapshot,
        run: dict[str, Any],
    ) -> None:
        if self.database_path is None:
            with self._lock:
                self._snapshots[key] = snapshot
                self._runs.append(run)
            return
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO operational_decision_briefs (
                    cache_key, snapshot_json, stored_at
                ) VALUES (?, ?, ?)
                """,
                (key, snapshot.model_dump_json(), snapshot.stored_at.isoformat()),
            )
            self._insert_run(connection, run)

    def _store_run(self, run: dict[str, Any]) -> None:
        if self.database_path is None:
            with self._lock:
                self._runs.append(run)
            return
        with sqlite3.connect(self.database_path) as connection:
            self._insert_run(connection, run)

    @staticmethod
    def _insert_run(
        connection: sqlite3.Connection,
        run: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO operational_decision_workflow_runs (
                workflow_run_id, project_id, asset_id, status, reason,
                run_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["workflow_run_id"],
                run["project_id"],
                run["asset_id"],
                run["status"],
                run["reason"],
                json.dumps(run, ensure_ascii=False, sort_keys=True),
                run["recorded_at"],
            ),
        )

    def _agent(
        self, identity: OperationalRequestIdentity
    ) -> BoundedOperationalDecisionAgent:
        fixture_root = self.root / "data" / "fixtures" / "operation_context"
        production = _load(fixture_root / "operational-decision-context-evidence-aligned-v1.json")
        maintenance = _load(fixture_root / "maintenance-readiness-context-evidence-aligned-v1.json")
        quality = _load(fixture_root / "quality-delivery-context-evidence-aligned-v1.json")
        for context in (production, maintenance, quality):
            context["scope"]["organization_id"] = identity.organization_id
            context["scope"]["project_id"] = identity.project_id
            context["scope"]["workspace_id"] = identity.workspace_id
        # The public demo path uses the fixture's explicitly satisfiable branch;
        # blocked/partial variants remain covered by the domain and Agent tests.
        maintenance["inventory_snapshots"][0]["reserved_quantity"] = 0
        maintenance["inventory_snapshots"][0]["available_quantity"] = 2
        for lot in quality["quality_lots"]:
            lot["quality_state"] = "released"
            lot["release_required"] = False
        return BoundedOperationalDecisionAgent(
            ports={
                "production": FixtureProductionDecisionContextReadPort(
                    context=production,
                    source_ref="fixture:operational-decision-context-evidence-aligned-v1",
                ),
                "maintenance_readiness": FixtureMaintenanceReadinessContextReadPort(
                    context=maintenance,
                    source_ref="fixture:maintenance-readiness-context-evidence-aligned-v1",
                ),
                "quality_delivery": FixtureQualityDeliveryContextReadPort(
                    context=quality,
                    source_ref="fixture:quality-delivery-context-evidence-aligned-v1",
                ),
            },
            impact_assumptions=ImpactSimulationAssumptions(
                policy_version="operational-impact-demo-v1",
                primary_capacity_units={
                    ImpactOption.STOP_NOW: 0,
                    ImpactOption.PLANNED_MAINTENANCE: 120,
                    ImpactOption.CONTINUE_OPERATION: 200,
                },
                alternative_capacity_allowed={
                    ImpactOption.STOP_NOW: True,
                    ImpactOption.PLANNED_MAINTENANCE: True,
                    ImpactOption.CONTINUE_OPERATION: False,
                },
                source_refs=("policy:operational-impact-demo-v1",),
            ),
        )

    @staticmethod
    def _cache_key(
        *,
        identity: OperationalRequestIdentity,
        actor_role: DecisionBriefRole,
    ) -> str:
        return "|".join(
            (
                identity.organization_id,
                identity.project_id,
                identity.workspace_id,
                identity.asset_id,
                identity.evidence_snapshot_id,
                identity.decision_as_of.isoformat(),
                actor_role.value,
            )
        )


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

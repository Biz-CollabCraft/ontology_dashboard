"""Persistence and transactional outbox boundary for Closed-loop operations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..migrations import migrate
from ..postgresql_compat import PostgreSQLProjectContextResolver, postgres_repository_connection
from app.project import SQLiteProjectContextResolver
from .domain import (
    IdempotencyConflict,
    InvalidTransition,
    apply_recommendation_decision,
    transition_work_order,
)
from .integration import (
    MaintenanceCompletedEvent,
    MaintenanceReplayRequestedEvent,
    MaintenanceStartedEvent,
)
from .models import (
    MaintenanceAction,
    MaintenanceActionStatus,
    OperationalRecommendedAction,
    RecommendationDecision,
    RecommendationDisposition,
    WorkOrder,
    WorkOrderAuthorization,
    WorkOrderStatus,
    WorkOrderType,
)


class ClosedLoopRepository:
    """SQLite adapter; PostgreSQL uses the same conservative SQL through compat."""

    def __init__(self, database: str | Path) -> None:
        self.database = str(database)
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        migrate(self.database)
        self.project_context = SQLiteProjectContextResolver(self.path)

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decoded(value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value

    def _scope(self, connection: Any, record: Any):
        return self.project_context.resolve(
            record.workspace_id,
            expected_organization_id=record.organization_id,
            expected_project_id=record.project_id,
            connection=connection,
        )

    def save_recommendation(
        self,
        recommendation: OperationalRecommendedAction,
        *,
        recorded_at: datetime | None = None,
        actor_user_id: str = "systems/backend",
        actor_display_name: str = "Closed-loop Backend",
    ) -> OperationalRecommendedAction:
        now = (recorded_at or datetime.now(timezone.utc)).isoformat()
        with self._connect() as connection:
            scope = self._scope(connection, recommendation)
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO closed_loop_recommendations (
                    recommendation_id,organization_id,project_id,workspace_id,event_id,
                    asset_id,equipment_id,recommendation_origin,status,source_action_id,
                    source_product_result_id,source_evidence_id,source_schema_version,
                    source_policy_version,label,kind,requires_human_approval,basis_json,
                    created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
            if inserted.rowcount == 1:
                self._record_activity(
                    connection,
                    scope=scope,
                    event_id=recommendation.event_id,
                    equipment_id=recommendation.equipment_id,
                    recommendation_id=recommendation.recommendation_id,
                    aggregate_type="recommendation",
                    aggregate_id=recommendation.recommendation_id,
                    activity_type="recommendation.materialized",
                    actor_user_id=actor_user_id,
                    actor_display_name=actor_display_name,
                    before_status=None,
                    after_status=recommendation.status.value,
                    payload={"recommendation_origin": recommendation.recommendation_origin},
                    created_at=now,
                )
            stored = self._recommendation_row(
                connection,
                scope=scope,
                recommendation_id=recommendation.recommendation_id,
            )
            if stored is None:
                stored = connection.execute(
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
            if stored is None:
                raise RuntimeError("recommendation was not persisted")
            materialized = self._recommendation_from_row(stored)
            if materialized != recommendation:
                raise IdempotencyConflict("recommendation materialization conflicts with existing data")
            return materialized

    def get_recommendation(
        self, *, workspace_id: str, recommendation_id: str
    ) -> OperationalRecommendedAction | None:
        with self._connect() as connection:
            scope = self.project_context.resolve(workspace_id, connection=connection)
            row = connection.execute(
                """
                SELECT * FROM closed_loop_recommendations
                WHERE organization_id=? AND project_id=? AND workspace_id=? AND recommendation_id=?
                """,
                (scope.organization_id, scope.project_id, workspace_id, recommendation_id),
            ).fetchone()
        return None if row is None else self._recommendation_from_row(row)

    def decide_recommendation(
        self,
        *,
        recommendation: OperationalRecommendedAction,
        decision: RecommendationDecision,
        work_order: WorkOrder | None,
        request_idempotency_key: str,
        request_fingerprint: str,
        actor_display_name: str | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope = self._scope(connection, recommendation)
            self._scope(connection, decision)
            current = self._recommendation_row(
                connection,
                scope=scope,
                recommendation_id=recommendation.recommendation_id,
            )
            if current is None:
                raise ValueError("recommendation not found")
            replay = self._reserve_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                command_type="recommendation.decision",
                request_fingerprint=request_fingerprint,
                now=now,
            )
            if replay is not None:
                return replay
            current_recommendation = self._recommendation_from_row(current)
            expected = apply_recommendation_decision(current_recommendation, decision)
            if expected != recommendation:
                raise InvalidTransition("persisted recommendation transition does not match the command")
            if decision.disposition is RecommendationDisposition.ACCEPT:
                if work_order is None:
                    raise ValueError("accepted recommendation must create a requested work order")
                self._validate_accepted_work_order(recommendation, decision, work_order)
                self._scope(connection, work_order)
            elif work_order is not None:
                raise ValueError("rejected or deferred recommendation cannot create a work order")
            connection.execute(
                """
                INSERT INTO closed_loop_recommendation_decisions (
                    decision_id,organization_id,project_id,workspace_id,event_id,
                    recommendation_id,disposition,actor_id,note,decided_at,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision.decision_id,
                    decision.organization_id,
                    decision.project_id,
                    decision.workspace_id,
                    decision.event_id,
                    decision.recommendation_id,
                    decision.disposition.value,
                    decision.actor_id,
                    decision.note,
                    decision.decided_at.isoformat(),
                    now,
                ),
            )
            updated = connection.execute(
                """
                UPDATE closed_loop_recommendations SET status=?,updated_at=?
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND recommendation_id=? AND status=?
                """,
                (
                    recommendation.status.value,
                    now,
                    recommendation.organization_id,
                    recommendation.project_id,
                    recommendation.workspace_id,
                    recommendation.recommendation_id,
                    current["status"],
                ),
            )
            if updated.rowcount != 1:
                raise InvalidTransition("recommendation was changed concurrently")
            if work_order is not None:
                self._insert_work_order(connection, work_order=work_order, now=now)
            self._record_activity(
                connection,
                scope=recommendation,
                event_id=recommendation.event_id,
                aggregate_type="recommendation",
                aggregate_id=recommendation.recommendation_id,
                activity_type=f"recommendation.{recommendation.status.value}",
                equipment_id=recommendation.equipment_id,
                recommendation_id=recommendation.recommendation_id,
                work_order_id=None if work_order is None else work_order.work_order_id,
                actor_user_id=decision.actor_id,
                actor_display_name=actor_display_name or decision.actor_id,
                before_status=current_recommendation.status.value,
                after_status=recommendation.status.value,
                payload=decision.model_dump(mode="json"),
                created_at=decision.decided_at.isoformat(),
            )
            if work_order is not None:
                self._record_activity(
                    connection,
                    scope=scope,
                    event_id=work_order.event_id,
                    equipment_id=work_order.equipment_id,
                    recommendation_id=work_order.authorization.recommendation_id,
                    work_order_id=work_order.work_order_id,
                    aggregate_type="work_order",
                    aggregate_id=work_order.work_order_id,
                    activity_type="work_order.requested",
                    actor_user_id=decision.actor_id,
                    actor_display_name=actor_display_name or decision.actor_id,
                    before_status=None,
                    after_status=work_order.status.value,
                    payload={"decision_id": decision.decision_id},
                    created_at=decision.decided_at.isoformat(),
                )
            result = {
                "decision_id": decision.decision_id,
                "recommendation_id": recommendation.recommendation_id,
                "recommendation_status": recommendation.status.value,
                "work_order_id": None if work_order is None else work_order.work_order_id,
                "replayed": False,
            }
            self._finish_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                response=result,
                now=now,
            )
            return result

    def approve_work_order(
        self,
        *,
        work_order: WorkOrder,
        action: MaintenanceAction,
        simulation_session_id: str,
        actor_id: str,
        approved_at: datetime,
        request_idempotency_key: str,
        request_fingerprint: str,
        action_code: str = "TOOL_REPLACEMENT",
        actor_display_name: str | None = None,
    ) -> dict[str, Any]:
        if action_code != "TOOL_REPLACEMENT":
            raise ValueError("unsupported maintenance action_code")
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope = self._scope(connection, work_order)
            self._scope(connection, action)
            replay = self._reserve_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                command_type="work_order.approve",
                request_fingerprint=request_fingerprint,
                now=now,
            )
            if replay is not None:
                return replay
            current = self._work_order_row(
                connection,
                scope=scope,
                work_order_id=work_order.work_order_id,
            )
            if current is None:
                raise ValueError("work order not found")
            current_work_order = self._work_order_from_row(current)
            if work_order.status is not WorkOrderStatus.APPROVED:
                raise InvalidTransition("work order approval must target approved status")
            transition_work_order(current_work_order.status, work_order.status)
            if current_work_order.model_copy(update={"status": work_order.status}) != work_order:
                raise ValueError("persisted work order does not match the approval command")
            self._validate_planned_action(work_order, action)
            updated = connection.execute(
                """
                UPDATE closed_loop_work_orders SET status=?,updated_at=?
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND work_order_id=? AND status=?
                """,
                (
                    WorkOrderStatus.APPROVED.value,
                    now,
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    work_order.work_order_id,
                    WorkOrderStatus.REQUESTED.value,
                ),
            )
            if updated.rowcount != 1:
                raise InvalidTransition("work order was changed concurrently")
            self._insert_maintenance_action(
                connection,
                action=action,
                simulation_session_id=simulation_session_id,
                action_code=action_code,
                now=now,
            )
            self._record_activity(
                connection,
                scope=scope,
                event_id=work_order.event_id,
                aggregate_type="work_order",
                aggregate_id=work_order.work_order_id,
                activity_type="work_order.approved",
                equipment_id=work_order.equipment_id,
                recommendation_id=action.recommendation_id,
                work_order_id=work_order.work_order_id,
                maintenance_action_id=action.maintenance_action_id,
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=WorkOrderStatus.REQUESTED.value,
                after_status=WorkOrderStatus.APPROVED.value,
                payload={
                    "work_order_id": work_order.work_order_id,
                    "maintenance_action_id": action.maintenance_action_id,
                },
                created_at=approved_at.isoformat(),
            )
            self._record_activity(
                connection,
                scope=scope,
                event_id=action.event_id,
                equipment_id=action.equipment_id,
                recommendation_id=action.recommendation_id,
                work_order_id=action.work_order_id,
                maintenance_action_id=action.maintenance_action_id,
                aggregate_type="maintenance_action",
                aggregate_id=action.maintenance_action_id,
                activity_type="maintenance_action.planned",
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=None,
                after_status=action.status.value,
                payload={"action_code": action_code},
                created_at=approved_at.isoformat(),
            )
            result = {
                "work_order_id": work_order.work_order_id,
                "work_order_status": work_order.status.value,
                "maintenance_action_id": action.maintenance_action_id,
                "maintenance_action_status": action.status.value,
                "replayed": False,
            }
            self._finish_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                response=result,
                now=now,
            )
            return result

    def start_maintenance(
        self,
        event: MaintenanceStartedEvent,
        *,
        workspace_id: str,
        actor_id: str,
        request_idempotency_key: str,
        request_fingerprint: str,
        actor_display_name: str | None = None,
    ) -> dict[str, Any]:
        payload = event.as_payload()
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope = self.project_context.resolve(workspace_id, connection=connection)
            action = self._maintenance_action_row(
                connection,
                scope=scope,
                maintenance_action_id=event.maintenance_action_id,
            )
            if action is None:
                raise ValueError("maintenance action not found")
            replay = self._reserve_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                command_type=event.event_type,
                request_fingerprint=request_fingerprint,
                now=now,
            )
            if replay is not None:
                return replay
            self._require_action_event_match(action, event)
            work_order = self._work_order_row(
                connection,
                scope=scope,
                work_order_id=action["work_order_id"],
            )
            if work_order is None or work_order["status"] != WorkOrderStatus.APPROVED.value:
                raise InvalidTransition("maintenance start requires an approved work order")
            if action["status"] != MaintenanceActionStatus.PLANNED.value:
                raise InvalidTransition("maintenance start requires a planned action")
            if event.state_version <= int(action["lifecycle_state_version"]):
                raise InvalidTransition("maintenance state_version must advance the action lifecycle")
            work_order_updated = connection.execute(
                """
                UPDATE closed_loop_work_orders SET status=?,updated_at=?
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND work_order_id=? AND status=?
                """,
                (
                    WorkOrderStatus.IN_PROGRESS.value,
                    now,
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    action["work_order_id"],
                    WorkOrderStatus.APPROVED.value,
                ),
            )
            if work_order_updated.rowcount != 1:
                raise InvalidTransition("work order was changed concurrently")
            action_updated = connection.execute(
                """
                UPDATE closed_loop_maintenance_actions
                SET status=?,lifecycle_state_version=?,started_at=?,updated_at=?
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND maintenance_action_id=? AND status=? AND lifecycle_state_version=?
                """,
                (
                    MaintenanceActionStatus.IN_PROGRESS.value,
                    event.state_version,
                    event.maintenance_started_at.isoformat(),
                    now,
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    event.maintenance_action_id,
                    MaintenanceActionStatus.PLANNED.value,
                    action["lifecycle_state_version"],
                ),
            )
            if action_updated.rowcount != 1:
                raise InvalidTransition("maintenance action was changed concurrently")
            self._record_activity(
                connection,
                scope=scope,
                event_id=action["event_id"],
                equipment_id=action["equipment_id"],
                recommendation_id=action["recommendation_id"],
                work_order_id=action["work_order_id"],
                maintenance_action_id=event.maintenance_action_id,
                aggregate_type="work_order",
                aggregate_id=action["work_order_id"],
                activity_type="work_order.in_progress",
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=WorkOrderStatus.APPROVED.value,
                after_status=WorkOrderStatus.IN_PROGRESS.value,
                payload={"integration_event_id": event.event_id},
                created_at=event.maintenance_started_at.isoformat(),
            )
            self._record_activity(
                connection,
                scope=scope,
                event_id=action["event_id"],
                equipment_id=action["equipment_id"],
                recommendation_id=action["recommendation_id"],
                work_order_id=action["work_order_id"],
                maintenance_action_id=event.maintenance_action_id,
                aggregate_type="maintenance_action",
                aggregate_id=event.maintenance_action_id,
                activity_type=event.event_type,
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=MaintenanceActionStatus.PLANNED.value,
                after_status=MaintenanceActionStatus.IN_PROGRESS.value,
                payload=payload,
                created_at=event.maintenance_started_at.isoformat(),
            )
            self._enqueue(connection, scope=scope, event=event, payload=payload, now=now)
            result = {
                "status": "in_progress",
                "maintenance_action_id": event.maintenance_action_id,
                "replayed": False,
            }
            self._finish_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                response=result,
                now=now,
            )
            return result

    def complete_maintenance(
        self,
        event: MaintenanceCompletedEvent,
        *,
        workspace_id: str,
        actor_id: str,
        outcome: str,
        request_idempotency_key: str,
        request_fingerprint: str,
        actor_display_name: str | None = None,
    ) -> dict[str, Any]:
        payload = event.as_payload()
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope = self.project_context.resolve(workspace_id, connection=connection)
            action = self._maintenance_action_row(
                connection,
                scope=scope,
                maintenance_action_id=event.maintenance_action_id,
            )
            if action is None:
                raise ValueError("maintenance action not found")
            replay = self._reserve_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                command_type=event.event_type,
                request_fingerprint=request_fingerprint,
                now=now,
            )
            if replay is not None:
                return replay
            self._require_action_event_match(action, event)
            work_order = self._work_order_row(
                connection,
                scope=scope,
                work_order_id=action["work_order_id"],
            )
            if work_order is None or work_order["status"] != WorkOrderStatus.IN_PROGRESS.value:
                raise InvalidTransition("maintenance completion requires an in-progress work order")
            if action["status"] != MaintenanceActionStatus.IN_PROGRESS.value:
                raise InvalidTransition("maintenance completion requires an in-progress action")
            if event.state_version <= int(action["lifecycle_state_version"]):
                raise InvalidTransition("maintenance state_version must advance the action lifecycle")
            started_at = action["started_at"]
            if not started_at:
                raise InvalidTransition("maintenance completion requires a recorded start time")
            if event.maintenance_started_at is not None and event.maintenance_started_at.isoformat() != str(
                started_at
            ):
                raise ValueError("maintenance_started_at does not match the persisted action")
            work_order_updated = connection.execute(
                """
                UPDATE closed_loop_work_orders SET status=?,updated_at=?
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND work_order_id=? AND status=?
                """,
                (
                    WorkOrderStatus.COMPLETED.value,
                    now,
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    action["work_order_id"],
                    WorkOrderStatus.IN_PROGRESS.value,
                ),
            )
            if work_order_updated.rowcount != 1:
                raise InvalidTransition("work order was changed concurrently")
            action_updated = connection.execute(
                """
                UPDATE closed_loop_maintenance_actions
                SET status=?,lifecycle_state_version=?,completed_at=?,updated_at=?
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND maintenance_action_id=? AND status=? AND lifecycle_state_version=?
                """,
                (
                    MaintenanceActionStatus.COMPLETED.value,
                    event.state_version,
                    event.maintenance_completed_at.isoformat(),
                    now,
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    event.maintenance_action_id,
                    MaintenanceActionStatus.IN_PROGRESS.value,
                    action["lifecycle_state_version"],
                ),
            )
            if action_updated.rowcount != 1:
                raise InvalidTransition("maintenance action was changed concurrently")
            state_patch = event.state_patch.model_dump(mode="json")
            existing_state = connection.execute(
                """
                SELECT state_version,state_json FROM closed_loop_equipment_state
                WHERE organization_id=? AND project_id=? AND workspace_id=? AND equipment_id=?
                """,
                (
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    event.equipment_id,
                ),
            ).fetchone()
            expected_equipment_state_version = (
                None if existing_state is None else int(existing_state["state_version"])
            )
            equipment_state_version = (
                1
                if expected_equipment_state_version is None
                else expected_equipment_state_version + 1
            )
            previous_equipment_state = (
                {} if existing_state is None else dict(self._decoded(existing_state["state_json"]))
            )
            applied_equipment_state = self._apply_state_patch(previous_equipment_state, state_patch)
            connection.execute(
                """
                INSERT INTO closed_loop_maintenance_events (
                    maintenance_event_id,organization_id,project_id,workspace_id,
                    maintenance_action_id,work_order_id,event_id,asset_id,equipment_id,
                    recommendation_id,recommendation_decision_id,simulation_session_id,
                    action_code,state_patch_json,maintenance_started_at,completed_at,
                    outcome,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.maintenance_event_id,
                    action["organization_id"],
                    action["project_id"],
                    action["workspace_id"],
                    event.maintenance_action_id,
                    action["work_order_id"],
                    action["event_id"],
                    action["asset_id"],
                    action["equipment_id"],
                    action["recommendation_id"],
                    action["recommendation_decision_id"],
                    action["simulation_session_id"],
                    action["action_code"],
                    self._json(state_patch),
                    started_at,
                    event.maintenance_completed_at.isoformat(),
                    outcome,
                    now,
                ),
            )
            self._persist_equipment_state(
                connection,
                scope=scope,
                equipment_id=action["equipment_id"],
                expected_version=expected_equipment_state_version,
                new_version=equipment_state_version,
                state=applied_equipment_state,
                maintenance_event_id=event.maintenance_event_id,
                updated_at=now,
            )
            self._record_activity(
                connection,
                scope=scope,
                event_id=action["event_id"],
                equipment_id=action["equipment_id"],
                recommendation_id=action["recommendation_id"],
                work_order_id=action["work_order_id"],
                maintenance_action_id=event.maintenance_action_id,
                maintenance_event_id=event.maintenance_event_id,
                aggregate_type="work_order",
                aggregate_id=action["work_order_id"],
                activity_type="work_order.completed",
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=WorkOrderStatus.IN_PROGRESS.value,
                after_status=WorkOrderStatus.COMPLETED.value,
                payload={"integration_event_id": event.event_id},
                created_at=event.maintenance_completed_at.isoformat(),
            )
            self._record_activity(
                connection,
                scope=scope,
                event_id=action["event_id"],
                equipment_id=action["equipment_id"],
                recommendation_id=action["recommendation_id"],
                work_order_id=action["work_order_id"],
                maintenance_action_id=event.maintenance_action_id,
                maintenance_event_id=event.maintenance_event_id,
                aggregate_type="maintenance_action",
                aggregate_id=event.maintenance_action_id,
                activity_type="maintenance_action.completed",
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=MaintenanceActionStatus.IN_PROGRESS.value,
                after_status=MaintenanceActionStatus.COMPLETED.value,
                payload={"outcome": outcome},
                created_at=event.maintenance_completed_at.isoformat(),
            )
            self._record_activity(
                connection,
                scope=scope,
                event_id=action["event_id"],
                equipment_id=action["equipment_id"],
                recommendation_id=action["recommendation_id"],
                work_order_id=action["work_order_id"],
                maintenance_action_id=event.maintenance_action_id,
                maintenance_event_id=event.maintenance_event_id,
                aggregate_type="maintenance_event",
                aggregate_id=event.maintenance_event_id,
                activity_type=event.event_type,
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=None,
                after_status="recorded",
                payload={**payload, "outcome": outcome},
                created_at=event.maintenance_completed_at.isoformat(),
            )
            self._record_activity(
                connection,
                scope=scope,
                event_id=action["event_id"],
                equipment_id=action["equipment_id"],
                recommendation_id=action["recommendation_id"],
                work_order_id=action["work_order_id"],
                maintenance_action_id=event.maintenance_action_id,
                maintenance_event_id=event.maintenance_event_id,
                aggregate_type="equipment",
                aggregate_id=action["equipment_id"],
                activity_type="equipment.state_updated",
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status=(
                    None if existing_state is None else f"state_version:{existing_state['state_version']}"
                ),
                after_status=f"state_version:{equipment_state_version}",
                payload={"state": applied_equipment_state},
                created_at=event.maintenance_completed_at.isoformat(),
            )
            self._enqueue(connection, scope=scope, event=event, payload=payload, now=now)
            result = {
                "status": "completed",
                "maintenance_event_id": event.maintenance_event_id,
                "replayed": False,
            }
            self._finish_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                response=result,
                now=now,
            )
            return result

    def request_replay(
        self,
        event: MaintenanceReplayRequestedEvent,
        *,
        workspace_id: str,
        actor_id: str,
        request_idempotency_key: str,
        request_fingerprint: str,
        actor_display_name: str | None = None,
    ) -> dict[str, Any]:
        payload = event.as_payload()
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope = self.project_context.resolve(workspace_id, connection=connection)
            maintenance = connection.execute(
                """
                SELECT * FROM closed_loop_maintenance_events
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND maintenance_event_id=?
                """,
                (
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    event.maintenance_event_id,
                ),
            ).fetchone()
            if maintenance is None:
                raise InvalidTransition("replay requires a completed maintenance event")
            replay = self._reserve_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                command_type=event.event_type,
                request_fingerprint=request_fingerprint,
                now=now,
            )
            if replay is not None:
                return replay
            if maintenance["maintenance_action_id"] != event.maintenance_action_id:
                raise ValueError("maintenance event does not belong to the action")
            if maintenance["equipment_id"] != event.equipment_id:
                raise ValueError("maintenance event equipment does not match")
            if maintenance["simulation_session_id"] != event.simulation_session_id:
                raise ValueError("simulation session does not match")
            action = self._maintenance_action_row(
                connection,
                scope=scope,
                maintenance_action_id=event.maintenance_action_id,
            )
            if action is None or action["status"] != MaintenanceActionStatus.COMPLETED.value:
                raise InvalidTransition("replay requires a completed maintenance action")
            self._require_action_event_match(action, event)
            completed_at = datetime.fromisoformat(str(maintenance["completed_at"]))
            if event.restart_at < completed_at:
                raise InvalidTransition("restart cannot precede maintenance completion")
            if (
                event.maintenance_completed_at is not None
                and event.maintenance_completed_at != completed_at
            ):
                raise ValueError("maintenance_completed_at does not match the persisted event")
            started_at = datetime.fromisoformat(str(maintenance["maintenance_started_at"]))
            if event.maintenance_started_at is not None and event.maintenance_started_at != started_at:
                raise ValueError("maintenance_started_at does not match the persisted event")
            if event.action_code is not None and event.action_code != maintenance["action_code"]:
                raise ValueError("replay action_code does not match the persisted event")
            if event.state_patch is not None and event.state_patch.model_dump(mode="json") != self._decoded(
                maintenance["state_patch_json"]
            ):
                raise ValueError("replay state_patch does not match the persisted event")
            if event.state_version <= int(action["lifecycle_state_version"]):
                raise InvalidTransition("replay state_version must advance the maintenance lifecycle")
            action_updated = connection.execute(
                """
                UPDATE closed_loop_maintenance_actions
                SET lifecycle_state_version=?,restart_at=?,updated_at=?
                WHERE organization_id=? AND project_id=? AND workspace_id=?
                  AND maintenance_action_id=? AND status=? AND lifecycle_state_version=?
                  AND restart_at IS NULL
                """,
                (
                    event.state_version,
                    event.restart_at.isoformat(),
                    now,
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    event.maintenance_action_id,
                    MaintenanceActionStatus.COMPLETED.value,
                    action["lifecycle_state_version"],
                ),
            )
            if action_updated.rowcount != 1:
                raise InvalidTransition("maintenance action was changed concurrently")
            self._record_activity(
                connection,
                scope=scope,
                event_id=maintenance["event_id"],
                equipment_id=maintenance["equipment_id"],
                recommendation_id=maintenance["recommendation_id"],
                work_order_id=maintenance["work_order_id"],
                maintenance_action_id=maintenance["maintenance_action_id"],
                maintenance_event_id=event.maintenance_event_id,
                aggregate_type="maintenance_event",
                aggregate_id=event.maintenance_event_id,
                activity_type=event.event_type,
                actor_user_id=actor_id,
                actor_display_name=actor_display_name or actor_id,
                before_status="recorded",
                after_status="replay_requested",
                payload=payload,
                created_at=now,
            )
            self._enqueue(connection, scope=scope, event=event, payload=payload, now=now)
            result = {
                "status": "replay_requested",
                "maintenance_event_id": event.maintenance_event_id,
                "replayed": False,
            }
            self._finish_idempotency(
                connection,
                scope=scope,
                idempotency_key=request_idempotency_key,
                response=result,
                now=now,
            )
            return result

    @staticmethod
    def _validate_accepted_work_order(
        recommendation: OperationalRecommendedAction,
        decision: RecommendationDecision,
        work_order: WorkOrder,
    ) -> None:
        if work_order.status is not WorkOrderStatus.REQUESTED:
            raise InvalidTransition("accepted recommendation must create a requested work order")
        if work_order.work_type is not WorkOrderType.MAINTENANCE:
            raise ValueError("accepted recommendation must create a maintenance work order")
        for field in ("organization_id", "project_id", "workspace_id", "event_id", "asset_id", "equipment_id"):
            if getattr(work_order, field) != getattr(recommendation, field):
                raise ValueError(f"work order {field} does not match the recommendation")
        authorization = work_order.authorization
        if (
            authorization.recommendation_id != recommendation.recommendation_id
            or authorization.recommendation_decision_id != decision.decision_id
        ):
            raise ValueError("work order authorization does not preserve recommendation lineage")

    @staticmethod
    def _validate_planned_action(work_order: WorkOrder, action: MaintenanceAction) -> None:
        if action.status is not MaintenanceActionStatus.PLANNED:
            raise InvalidTransition("work order approval must create a planned maintenance action")
        for field in (
            "organization_id",
            "project_id",
            "workspace_id",
            "event_id",
            "asset_id",
            "equipment_id",
            "work_order_id",
        ):
            if getattr(action, field) != getattr(work_order, field):
                raise ValueError(f"maintenance action {field} does not match the work order")
        if (
            action.recommendation_id != work_order.authorization.recommendation_id
            or action.recommendation_decision_id
            != work_order.authorization.recommendation_decision_id
        ):
            raise ValueError("maintenance action does not preserve work order authorization lineage")

    def _insert_work_order(self, connection: Any, *, work_order: WorkOrder, now: str) -> None:
        connection.execute(
            """
            INSERT INTO closed_loop_work_orders (
                work_order_id,organization_id,project_id,workspace_id,event_id,
                asset_id,equipment_id,work_type,status,idempotency_key,
                authorization_json,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                work_order.work_order_id,
                work_order.organization_id,
                work_order.project_id,
                work_order.workspace_id,
                work_order.event_id,
                work_order.asset_id,
                work_order.equipment_id,
                work_order.work_type.value,
                work_order.status.value,
                work_order.idempotency_key,
                work_order.authorization.model_dump_json(),
                now,
                now,
            ),
        )

    def _insert_maintenance_action(
        self,
        connection: Any,
        *,
        action: MaintenanceAction,
        simulation_session_id: str,
        action_code: str,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO closed_loop_maintenance_actions (
                maintenance_action_id,organization_id,project_id,workspace_id,
                work_order_id,event_id,asset_id,equipment_id,recommendation_id,
                recommendation_decision_id,simulation_session_id,action_code,status,
                idempotency_key,started_at,completed_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?,?)
            """,
            (
                action.maintenance_action_id,
                action.organization_id,
                action.project_id,
                action.workspace_id,
                action.work_order_id,
                action.event_id,
                action.asset_id,
                action.equipment_id,
                action.recommendation_id,
                action.recommendation_decision_id,
                simulation_session_id,
                action_code,
                action.status.value,
                action.idempotency_key,
                now,
                now,
            ),
        )

    def list_event_activity(self, *, workspace_id: str, event_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            scope = self.project_context.resolve(workspace_id, connection=connection)
            rows = connection.execute(
                """
                SELECT * FROM closed_loop_activities
                WHERE organization_id=? AND project_id=? AND workspace_id=? AND event_id=?
                ORDER BY created_at,timeline_order,activity_id
                """,
                (scope.organization_id, scope.project_id, workspace_id, event_id),
            ).fetchall()
        return [{**dict(row), "payload": self._decoded(row["payload_json"])} for row in rows]

    def equipment_state(self, *, workspace_id: str, equipment_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            scope = self.project_context.resolve(workspace_id, connection=connection)
            row = connection.execute(
                """
                SELECT * FROM closed_loop_equipment_state
                WHERE organization_id=? AND project_id=? AND workspace_id=? AND equipment_id=?
                """,
                (scope.organization_id, scope.project_id, workspace_id, equipment_id),
            ).fetchone()
        if row is None:
            return None
        return {**dict(row), "state": self._decoded(row["state_json"])}

    @staticmethod
    def _recommendation_row(connection: Any, *, scope: Any, recommendation_id: str):
        return connection.execute(
            """
            SELECT * FROM closed_loop_recommendations
            WHERE organization_id=? AND project_id=? AND workspace_id=? AND recommendation_id=?
            """,
            (scope.organization_id, scope.project_id, scope.workspace_id, recommendation_id),
        ).fetchone()

    @classmethod
    def _work_order_from_row(cls, row: Mapping[str, Any]) -> WorkOrder:
        return WorkOrder(
            organization_id=row["organization_id"],
            project_id=row["project_id"],
            workspace_id=row["workspace_id"],
            work_order_id=row["work_order_id"],
            event_id=row["event_id"],
            asset_id=row["asset_id"],
            equipment_id=row["equipment_id"],
            work_type=row["work_type"],
            status=row["status"],
            idempotency_key=row["idempotency_key"],
            authorization=WorkOrderAuthorization.model_validate(cls._decoded(row["authorization_json"])),
        )

    @classmethod
    def _recommendation_from_row(cls, row: Mapping[str, Any]) -> OperationalRecommendedAction:
        return OperationalRecommendedAction(
            organization_id=row["organization_id"],
            project_id=row["project_id"],
            workspace_id=row["workspace_id"],
            recommendation_id=row["recommendation_id"],
            recommendation_origin=row["recommendation_origin"],
            status=row["status"],
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
            basis=tuple(cls._decoded(row["basis_json"])),
        )

    @staticmethod
    def _maintenance_action_row(connection: Any, *, scope: Any, maintenance_action_id: str):
        return connection.execute(
            """
            SELECT a.*,r.source_product_result_id,r.source_evidence_id
            FROM closed_loop_maintenance_actions a
            JOIN closed_loop_recommendations r
              ON r.organization_id=a.organization_id
             AND r.project_id=a.project_id
             AND r.workspace_id=a.workspace_id
             AND r.recommendation_id=a.recommendation_id
            WHERE a.organization_id=? AND a.project_id=? AND a.workspace_id=?
              AND a.maintenance_action_id=?
            """,
            (
                scope.organization_id,
                scope.project_id,
                scope.workspace_id,
                maintenance_action_id,
            ),
        ).fetchone()

    @staticmethod
    def _work_order_row(connection: Any, *, scope: Any, work_order_id: str):
        return connection.execute(
            """
            SELECT * FROM closed_loop_work_orders
            WHERE organization_id=? AND project_id=? AND workspace_id=? AND work_order_id=?
            """,
            (scope.organization_id, scope.project_id, scope.workspace_id, work_order_id),
        ).fetchone()

    @staticmethod
    def _require_action_event_match(action: Mapping[str, Any], event: Any) -> None:
        if action["equipment_id"] != event.equipment_id:
            raise ValueError("maintenance event equipment does not match the action")
        if action["simulation_session_id"] != event.simulation_session_id:
            raise ValueError("maintenance event simulation session does not match the action")
        event_action_code = getattr(event, "action_code", None)
        if event_action_code is not None and action["action_code"] != event_action_code:
            raise ValueError("maintenance event action_code does not match the action")
        work_order_id = getattr(event, "work_order_id", None)
        if work_order_id is not None and action["work_order_id"] != work_order_id:
            raise ValueError("maintenance event work order does not match the action")
        if action["recommendation_decision_id"] != event.caused_by.decision_id:
            raise ValueError("maintenance event decision lineage does not match the action")
        if action["source_product_result_id"] != event.caused_by.source_product_result_id:
            raise ValueError("maintenance event Product Result lineage does not match the action")
        if action["source_evidence_id"] != event.caused_by.source_evidence_id:
            raise ValueError("maintenance event Evidence lineage does not match the action")

    def _reserve_idempotency(
        self,
        connection: Any,
        *,
        scope: Any,
        idempotency_key: str,
        command_type: str,
        request_fingerprint: str,
        now: str,
    ) -> dict[str, Any] | None:
        if not 8 <= len(idempotency_key) <= 200:
            raise ValueError("HTTP Idempotency-Key must contain 8 to 200 characters")
        if not request_fingerprint or len(request_fingerprint) > 256:
            raise ValueError("canonical request fingerprint must contain 1 to 256 characters")
        existing = connection.execute(
            """
            SELECT * FROM closed_loop_idempotency_records
            WHERE organization_id=? AND project_id=? AND workspace_id=? AND idempotency_key=?
            """,
            (scope.organization_id, scope.project_id, scope.workspace_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if existing["command_type"] != command_type or existing["request_fingerprint"] != request_fingerprint:
                raise IdempotencyConflict("idempotency_key_conflict")
            if existing["state"] != "succeeded" or not existing["response_json"]:
                raise InvalidTransition("idempotent command is not replayable")
            response = dict(self._decoded(existing["response_json"]))
            response["replayed"] = True
            return response
        connection.execute(
            """
            INSERT INTO closed_loop_idempotency_records (
                organization_id,project_id,workspace_id,idempotency_key,command_type,
                request_fingerprint,state,response_json,last_error,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,'running',NULL,NULL,?,?)
            """,
            (
                scope.organization_id,
                scope.project_id,
                scope.workspace_id,
                idempotency_key,
                command_type,
                request_fingerprint,
                now,
                now,
            ),
        )
        return None

    def _finish_idempotency(
        self,
        connection: Any,
        *,
        scope: Any,
        idempotency_key: str,
        response: Mapping[str, Any],
        now: str,
    ) -> None:
        connection.execute(
            """
            UPDATE closed_loop_idempotency_records
            SET state='succeeded',response_json=?,updated_at=?
            WHERE organization_id=? AND project_id=? AND workspace_id=? AND idempotency_key=?
            """,
            (
                self._json(response),
                now,
                scope.organization_id,
                scope.project_id,
                scope.workspace_id,
                idempotency_key,
            ),
        )

    def _record_activity(
        self,
        connection: Any,
        *,
        scope: Any,
        event_id: str,
        equipment_id: str | None = None,
        recommendation_id: str | None = None,
        work_order_id: str | None = None,
        maintenance_action_id: str | None = None,
        maintenance_event_id: str | None = None,
        aggregate_type: str,
        aggregate_id: str,
        activity_type: str,
        actor_user_id: str,
        actor_display_name: str,
        before_status: str | None,
        after_status: str | None,
        payload: Mapping[str, Any],
        created_at: str,
    ) -> None:
        if not actor_user_id or not actor_display_name:
            raise ValueError("activity actor identity is required")
        timeline_order = {
            "recommendation.materialized": 10,
            "recommendation.accepted": 20,
            "recommendation.rejected": 20,
            "recommendation.deferred": 20,
            "work_order.requested": 30,
            "work_order.approved": 40,
            "maintenance_action.planned": 50,
            "work_order.in_progress": 60,
            "maintenance.started": 70,
            "work_order.completed": 80,
            "maintenance_action.completed": 90,
            "maintenance.completed": 100,
            "equipment.state_updated": 110,
            "maintenance.replay_requested": 120,
        }.get(activity_type, 1000)
        connection.execute(
            """
            INSERT INTO closed_loop_activities (
                activity_id,organization_id,project_id,workspace_id,event_id,
                equipment_id,recommendation_id,work_order_id,maintenance_action_id,
                maintenance_event_id,aggregate_type,aggregate_id,activity_type,
                actor_user_id,actor_display_name,before_status,after_status,timeline_order,
                payload_json,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(uuid.uuid4()),
                scope.organization_id,
                scope.project_id,
                scope.workspace_id,
                event_id,
                equipment_id,
                recommendation_id,
                work_order_id,
                maintenance_action_id,
                maintenance_event_id,
                aggregate_type,
                aggregate_id,
                activity_type,
                actor_user_id,
                actor_display_name,
                before_status,
                after_status,
                timeline_order,
                self._json(payload),
                created_at,
            ),
        )

    @staticmethod
    def _apply_state_patch(
        current_state: Mapping[str, Any], state_patch: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Apply an approved maintenance command without persisting command syntax as state."""

        updated = dict(current_state)
        tool_wear = state_patch.get("tool_wear_min")
        if not isinstance(tool_wear, Mapping) or tool_wear.get("operation") != "reset":
            raise ValueError("unsupported equipment state patch")
        updated["tool_wear_min"] = {
            "value": tool_wear.get("value"),
            "unit": tool_wear.get("unit"),
        }
        return updated

    def _persist_equipment_state(
        self,
        connection: Any,
        *,
        scope: Any,
        equipment_id: str,
        expected_version: int | None,
        new_version: int,
        state: Mapping[str, Any],
        maintenance_event_id: str,
        updated_at: str,
    ) -> None:
        expected_new_version = 1 if expected_version is None else expected_version + 1
        if new_version != expected_new_version:
            raise ValueError("equipment state_version must advance exactly once")

        if expected_version is None:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO closed_loop_equipment_state (
                    organization_id,project_id,workspace_id,equipment_id,state_version,
                    state_json,last_maintenance_event_id,updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    scope.organization_id,
                    scope.project_id,
                    scope.workspace_id,
                    equipment_id,
                    new_version,
                    self._json(state),
                    maintenance_event_id,
                    updated_at,
                ),
            )
            if inserted.rowcount != 1:
                raise InvalidTransition("equipment state was created concurrently")
            return

        updated = connection.execute(
            """
            UPDATE closed_loop_equipment_state
            SET state_version=?,state_json=?,last_maintenance_event_id=?,updated_at=?
            WHERE organization_id=? AND project_id=? AND workspace_id=?
              AND equipment_id=? AND state_version=?
            """,
            (
                new_version,
                self._json(state),
                maintenance_event_id,
                updated_at,
                scope.organization_id,
                scope.project_id,
                scope.workspace_id,
                equipment_id,
                expected_version,
            ),
        )
        if updated.rowcount != 1:
            raise InvalidTransition("equipment state was changed concurrently")

    def _enqueue(
        self,
        connection: Any,
        *,
        scope: Any,
        event: Any,
        payload: Mapping[str, Any],
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO transactional_outbox (
                id,organization_id,project_id,workspace_id,aggregate_type,aggregate_id,
                event_type,payload_json,status,attempt_count,created_at,available_at
            ) VALUES (?,?,?,?,?,?,?,?,'pending',0,?,?)
            """,
            (
                event.event_id,
                scope.organization_id,
                scope.project_id,
                scope.workspace_id,
                "maintenance_action",
                event.maintenance_action_id,
                event.event_type,
                self._json(payload),
                now,
                now,
            ),
        )


class PostgreSQLClosedLoopRepository(ClosedLoopRepository):
    """PostgreSQL/RLS adapter using the canonical compatibility connection."""

    def __init__(self, database_url: str) -> None:
        self.database = database_url
        self.path = database_url
        self.project_context = PostgreSQLProjectContextResolver(database_url)

    def _connect(self):
        return postgres_repository_connection(
            self.database,
            resolver=self.project_context,
        )

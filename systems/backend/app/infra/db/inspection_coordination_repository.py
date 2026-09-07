"""Persistent production consultation using the maintenance activity ledger."""
from __future__ import annotations
import uuid
from app.maintenance.maintenance_domain import InvalidTransition
from app.maintenance.maintenance_schema import WorkOrderStatus, WorkOrderType

class InspectionCoordinationRepositoryMixin:
    def _coordination_history(self, connection, *, scope, work_order_id):
        rows = connection.execute(
            """SELECT payload_json FROM closed_loop_activities
               WHERE organization_id=? AND project_id=? AND workspace_id=?
                 AND work_order_id=? AND aggregate_type='inspection_coordination'
               ORDER BY created_at, timeline_order, activity_id""",
            (scope.organization_id, scope.project_id, scope.workspace_id, work_order_id),
        ).fetchall()
        return [self._decoded(row["payload_json"]) for row in rows]

    def _lock_coordination_order(self, connection, *, scope, work_order_id):
        # Serializes consultation/replies/start against the same row on both adapters.
        connection.execute(
            """UPDATE closed_loop_work_orders SET updated_at=updated_at
               WHERE organization_id=? AND project_id=? AND workspace_id=? AND work_order_id=?""",
            (scope.organization_id, scope.project_id, scope.workspace_id, work_order_id),
        )

    def record_inspection_coordination(self, *, work_order, phase, payload,
                                      actor_id, actor_display_name,
                                      request_idempotency_key, request_fingerprint):
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope = self._scope(connection, work_order)
            replay = self._reserve_idempotency(
                connection, scope=scope, idempotency_key=request_idempotency_key,
                command_type=f"inspection.coordination.{phase}",
                request_fingerprint=request_fingerprint, now=self._now())
            if replay is not None:
                return replay
            self._lock_coordination_order(connection, scope=scope, work_order_id=work_order.work_order_id)
            row = self._work_order_row(connection, scope=scope, work_order_id=work_order.work_order_id)
            if row is None:
                raise KeyError(work_order.work_order_id)
            current = self._work_order_from_row(row)
            if current.work_type is not WorkOrderType.INSPECTION or current.status is not WorkOrderStatus.APPROVED:
                raise InvalidTransition("production consultation requires an accepted, not-started inspection")
            history = self._coordination_history(connection, scope=scope, work_order_id=current.work_order_id)
            previous = history[-1] if history else None
            now = self._now()
            if phase == "request":
                if current.assigned_to != actor_id:
                    raise PermissionError("only the assigned technician may request production consultation")
                if previous and previous["status"] == "pending":
                    raise InvalidTransition("a production consultation is already pending")
                result = dict(
                    work_order_id=current.work_order_id, asset_id=current.asset_id,
                    event_id=current.event_id, request_id=str(uuid.uuid4()), status="pending",
                    request=payload, requested_by=actor_id,
                    requested_by_name=actor_display_name, requested_at=now,
                    response=None, responded_by=None, responded_by_name=None, responded_at=None,
                )
            else:
                if not previous or previous["status"] != "pending" or previous["request_id"] != payload["request_id"]:
                    raise InvalidTransition("consultation changed; reload before replying")
                result = {**previous, "status": payload["decision"], "response": payload,
                          "responded_by": actor_id, "responded_by_name": actor_display_name, "responded_at": now}
            self._record_activity(
                connection, scope=scope, event_id=current.event_id,
                equipment_id=current.equipment_id, work_order_id=current.work_order_id,
                aggregate_type="inspection_coordination", aggregate_id=current.work_order_id,
                activity_type=f"inspection.coordination.{result['status']}",
                actor_user_id=actor_id, actor_display_name=actor_display_name,
                before_status=previous["status"] if previous else None, after_status=result["status"],
                payload=result, created_at=now,
            )
            self._finish_idempotency(connection, scope=scope, idempotency_key=request_idempotency_key, response=result, now=now)
            return result

    def list_inspection_coordination(self, *, organization_id, project_id, workspace_id):
        with self._connect() as connection:
            scope = self.project_context.resolve(
                workspace_id, expected_organization_id=organization_id,
                expected_project_id=project_id, connection=connection)
            rows = connection.execute(
                """SELECT DISTINCT work_order_id FROM closed_loop_activities
                   WHERE organization_id=? AND project_id=? AND workspace_id=?
                     AND aggregate_type='inspection_coordination'""",
                (scope.organization_id, scope.project_id, scope.workspace_id),
            ).fetchall()
            items = []
            for row in rows:
                history = self._coordination_history(connection, scope=scope, work_order_id=row["work_order_id"])
                order_row = self._work_order_row(connection, scope=scope, work_order_id=row["work_order_id"])
                if not history or order_row is None:
                    continue
                order = self._work_order_from_row(order_row)
                result_rows = connection.execute(
                    """SELECT outcome,findings_json,note FROM closed_loop_inspection_results
                       WHERE organization_id=? AND project_id=? AND workspace_id=? AND work_order_id=?
                       ORDER BY recorded_at DESC""",
                    (scope.organization_id, scope.project_id, scope.workspace_id, order.work_order_id),
                ).fetchall()
                latest_result = dict(result_rows[0]) if result_rows else None
                if latest_result:
                    latest_result["findings"] = self._decoded(latest_result.pop("findings_json"))
                items.append({**history[-1], "work_order_status": order.status.value,
                              "work_order_created_at": order_row["created_at"],
                              "history": history, "inspection_result": latest_result})
            return {"items": sorted(items, key=lambda item: (item["status"] != "pending", item["requested_at"], item["work_order_id"]))}

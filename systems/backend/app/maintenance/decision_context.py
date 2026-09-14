"""Read-only next-action policy. Command endpoints remain authoritative."""
from typing import Any


def available_workflow_actions(
    lineage: dict[str, Any], *, roles: set[str], permissions: set[str], actor_id: str,
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    def add(action_id: str, target_type: str, target_id: str, label: str,
            role: str, permission: str, reason: str | None = None) -> None:
        if not target_id:
            return
        actions.append(dict(action_id=action_id, target_type=target_type,
                            target_id=target_id, label=label,
                            disabled_reason=reason or (
                                None if role in roles and permission in permissions
                                else "담당 역할의 확인이 필요합니다."
                            )))

    # Most recent state wins; never offer a transition on an older work order.
    orders = list(reversed(lineage.get("work_orders") or []))
    for order in orders:
        if order.get("work_type") != "inspection":
            continue
        status = order.get("status")
        action = {
            "requested": ("accept_inspection_work_order", "점검 요청 수락"),
            "approved": ("start_inspection_work_order", "현장 점검 시작"),
            "in_progress": ("complete_inspection_work_order", "점검 결과 등록"),
        }.get(status)
        if action:
            reason = ("배정된 점검 담당자만 진행할 수 있습니다."
                      if status != "requested" and order.get("assigned_to") != actor_id else None)
            add(action[0], "work_order", order["work_order_id"], action[1],
                "process_engineer", "field.tasks.update", reason)
            return actions
        break

    for action in (lineage.get("maintenance_actions") or [])[-1:]:
        status = action.get("status")
        command = {"planned": ("start_maintenance_action", "정비 시작"),
                   "in_progress": ("complete_maintenance_action", "작업 완료 기록")}.get(status)
        if command:
            add(command[0], "maintenance_action", action["maintenance_action_id"],
                command[1], "maintenance_technician", "field.tasks.update")
            return actions
    latest_action = (lineage.get("maintenance_actions") or [None])[-1]
    maintenance_event = (lineage.get("maintenance_events") or [None])[-1]
    if (latest_action and maintenance_event and latest_action.get("status") == "completed"
            and maintenance_event.get("maintenance_action_id") == latest_action.get("maintenance_action_id")
            and not latest_action.get("restart_at")
            and lineage.get("runtime_status") not in {"ready", "predicted"}):
        add("request_maintenance_replay", "maintenance_event",
            maintenance_event["maintenance_event_id"], "조치 후 관측 재개",
            "maintenance_technician", "field.tasks.update")
        return actions
    maintenance_orders = [order for order in orders if order.get("work_type") == "maintenance"]
    for order in maintenance_orders[:1]:
        if order.get("status") == "requested":
            add("approve_maintenance_work_order", "work_order", order["work_order_id"],
                "정비 작업 승인", "process_manager", "events.decision")
            return actions
    for recommendation in (lineage.get("recommendations") or [])[-1:]:
        if recommendation.get("recommendation_origin") == "operations_manual" and recommendation.get("status") == "proposed":
            add("decide_operations_manual_recommendation", "recommendation",
                recommendation["recommendation_id"], "정비안 승인", "process_manager", "events.decision")
            return actions
    return actions

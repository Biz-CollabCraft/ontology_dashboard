"""Adapt exact demo file observations through the existing artifact contract."""
from copy import deepcopy
from datetime import datetime
from fastapi import HTTPException

from app.operations.asset_detail_view_model import compose_asset_detail_view_model
from app.operations.agent_review_packet import compose_agent_review_packet


def filesystem_briefing_packet(*, asset_id, event_id, dataset_version_id, project_id, history_window, service):
    from app.diagnosis.runtime_router import _latest_complete_file_tick, _filesystem_event_artifact
    if project_id != "manufacturing-demo-project" or not event_id.startswith("FILE#"):
        raise KeyError(event_id)
    stream, latest_at, records, complete_ticks = _latest_complete_file_tick()
    run_id = stream.parents[1].name
    if dataset_version_id and dataset_version_id != run_id:
        raise KeyError(event_id)
    ticks = complete_ticks or [(latest_at, {str(row["asset_id"]): row for row in records})]
    for observed_at, rows in reversed(ticks):
        record = rows.get(asset_id)
        if not record:
            continue
        expected = f"FILE#{run_id}#{record.get('observation_id', asset_id)}"
        if expected != event_id:
            continue
        artifact = _filesystem_event_artifact(run_id=run_id, observed_at=observed_at, record=record, event_id=event_id)
        for rank, factor in enumerate(artifact.get("top_factors", []), 1):
            factor.setdefault("rank", rank)
            factor.setdefault("explanation_method", "filesystem-risk-policy-v1")
        closed_loop, workflow_as_of = filesystem_workflow_context(
            service=service, asset_id=asset_id, event_id=event_id,
            project_id=project_id, observed_at=observed_at)
        view = compose_asset_detail_view_model(
            asset={"asset_id": asset_id, "asset_type": artifact["asset_type"], "display_name": asset_id},
            result_artifact=artifact, event_id=event_id, history_window=history_window, closed_loop=closed_loop,
        )
        packet = compose_agent_review_packet(project_id=project_id, view_model=view,
            sop_retrieval={"provider": "runtime_product_result", "query": {"asset_id": asset_id, "event_id": event_id, "dataset_version_id": run_id}, "top_k": 0, "returned_count": 0, "results": []})
        packet["maintenance_history_summary"]["workflow_as_of"] = workflow_as_of
        return packet
    raise KeyError(event_id)


def filesystem_workflow_context(*, service, asset_id, event_id, project_id, observed_at):
    """Read exact-event owner records; failure must never become an empty history."""
    try:
        if service.maintenance_lineage_query is None:
            raise RuntimeError("maintenance history reader unavailable")
        lineage = service.maintenance_lineage_query.event_lineage(
            workspace_id="manufacturing-demo", event_id=event_id)
        if lineage.get("event_id") != event_id:
            raise ValueError("event scope mismatch")
        groups = ("work_orders", "inspection_results", "maintenance_actions", "maintenance_events", "activities")
        context = {key: deepcopy(lineage.get(key) or []) for key in groups}
        for rows in context.values():
            for row in rows:
                for key, expected in (("project_id", project_id), ("workspace_id", "manufacturing-demo"),
                                      ("event_id", event_id), ("asset_id", asset_id), ("equipment_id", asset_id)):
                    if row.get(key) not in (None, "", expected):
                        raise ValueError("record scope mismatch")
        # The event ledger is already ordered by the owning repository.
        coordinations = {}
        for activity in context["activities"]:
            if activity.get("aggregate_type") == "inspection_coordination":
                value = activity.get("payload") or {}
                if value.get("event_id") != event_id or value.get("asset_id") != asset_id:
                    raise ValueError("coordination scope mismatch")
                coordinations[value["work_order_id"]] = value
        for order in context["work_orders"]:
            coordination = coordinations.get(order["work_order_id"])
            if coordination:
                order["production_coordination"] = coordination
                coordination["work_order_status"] = order["status"]
                labels = {"pending": "생산 관리자 승인 대기", "confirmed": "생산 관리자 승인 완료", "changes_requested": "생산 관리자 재협의 요청"}
                request = coordination.get("request") or {}
                response = coordination.get("response") or {}
                order["note"] = ("점검 결과 기록 후 생산 협의 상태. "
                    f"{labels.get(coordination.get('status'), '생산 협의 상태 확인 필요')}. "
                    f"정비 내용: {request.get('work_summary', '')}. 요청 정지: {request.get('downtime_minutes')}분. "
                    f"생산 영향: {request.get('affected_items', '')}. 승인 일정: {response.get('scheduled_window', '')}")
                # Read-model phase, not a mutation of the owner's work-order status.
                order["status"] = {
                    "pending": "inspection_completed_pending_production_approval",
                    "confirmed": "production_approval_confirmed",
                    "changes_requested": "production_changes_requested",
                }.get(coordination.get("status"), order["status"])
        stamps = [observed_at]
        for rows in context.values():
            for row in rows:
                stamps.extend(row[k] for k in ("created_at", "updated_at", "recorded_at", "completed_at") if row.get(k))
        workflow_as_of = max(stamps, key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")))
        context["available_actions"] = []
        return context, workflow_as_of
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"code": "briefing_history_unavailable",
            "message": "점검·승인 이력을 조회하지 못해 브리핑을 구성할 수 없습니다."}) from exc

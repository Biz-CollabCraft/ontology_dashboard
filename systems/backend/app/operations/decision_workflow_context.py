"""Read-only current workflow overlay for event-bound DecisionSessions.

Prediction evidence keeps its observation time. Workflow facts advance with
persisted owner records, not with polling time or a fabricated prediction.
"""
from copy import deepcopy
from datetime import datetime, timezone

from app.operations.agent_briefing_context import record_context
from app.operations.context_providers import MaintenanceHistoryContextProvider


def with_decision_workflow(packet, lineage, identity, *, now=None):
    now = now or datetime.now(timezone.utc)
    result = deepcopy(packet)
    basis = result.get("snapshot_basis") or {}
    if result.get("asset_id") != identity.asset_id or basis.get("event_id") != identity.evidence_snapshot_id:
        raise ValueError("decision_workflow_identity_mismatch")
    for collection in ("work_orders", "inspection_results", "maintenance_actions", "maintenance_events", "activities"):
        for record in lineage.get(collection) or []:
            for key, expected in (
                ("organization_id", identity.organization_id), ("project_id", identity.project_id),
                ("workspace_id", identity.workspace_id), ("event_id", basis["event_id"]),
                ("asset_id", identity.asset_id), ("equipment_id", identity.asset_id),
            ):
                if record.get(key) is not None and record[key] != expected:
                    raise ValueError("decision_workflow_scope_mismatch")
    history = MaintenanceHistoryContextProvider().context_for_packet(
        view_model={"closed_loop": lineage}
    ).maintenance_history_summary
    previous = result.get("maintenance_history_summary") or {}
    for key in ("recent_equipment_history", "last_maintenance_days_ago", "similar_events_30d", "similar_events"):
        if key in previous:
            history[key] = deepcopy(previous[key])
    # Validate all owner timestamps against the server clock before deriving a
    # stable revision time. Never promote future or unscoped records to facts.
    result["maintenance_history_summary"] = history
    history["workflow_as_of"] = now.isoformat()
    stamps = [datetime.fromisoformat(basis["observed_at"].replace("Z", "+00:00"))]
    excluded = []
    for collection in ("work_orders", "inspection_results", "maintenance_actions", "maintenance_events", "activities"):
        accepted = []
        for record in history[collection]:
            scoped = record_context(record, packet=result)
            scope = scoped["record_context"]
            if (scope["temporal_relation"] != "at_or_before_basis"
                    or scope["asset_scope"] != "matches_asset"
                    or scope["event_relation"] != "matches_event"):
                excluded.append({"record_id": record["record_id"], "scope": {
                    key: value for key, value in scope.items() if key != "decision_as_of"
                }})
                continue
            accepted.append(record)
            owner = record.get("owner_record_provenance") or {}
            for value in [record.get("recorded_at"), *[owner.get(key) for key in
                    ("created_at", "updated_at", "approved_at", "started_at", "completed_at", "recorded_at")]]:
                if value:
                    stamps.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
        history[collection] = accepted
    history["workflow_as_of"] = max(stamps).isoformat()
    history["excluded_records"] = excluded
    history["source_refs"] = list(dict.fromkeys(
        record["source_ref"] for collection in
        ("work_orders", "inspection_results", "maintenance_actions", "maintenance_events", "activities")
        for record in history[collection]
    ))
    result["source_refs"] = list(dict.fromkeys([*(result.get("source_refs") or []), *history["source_refs"]]))
    return result

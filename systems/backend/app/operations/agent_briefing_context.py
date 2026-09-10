"""Read-only SOP and owner-record projections for briefing consumers."""
from copy import deepcopy
from datetime import datetime
from typing import Any


def pick(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: deepcopy(value[key]) for key in keys if key in value}


def compact_sop_guidance(guidance: dict[str, Any]) -> dict[str, Any]:
    result = pick(guidance, "sop_id", "sop_version", "schema_version", "procedure_title",
                  "component_id", "component_label", "location_label", "inspection_method",
                  "check_items", "checklist_draft", "source_ref", "location_source_ref",
                  "source_type", "maturity", "disclaimer")
    replacement = guidance.get("replacement_review_guidance")
    if isinstance(replacement, dict):
        result["replacement_review_guidance"] = pick(
            replacement, "review_label", "review_triggers", "required_measurements",
            "operator_review_items", "decision_boundary")
    judgment = guidance.get("sensor_judgment")
    if isinstance(judgment, dict):
        result["sensor_judgment"] = pick(judgment, "judgment_scope", "allowed_outcomes",
                                         "inspection_result_mapping", "claim_boundaries")
        criteria = []
        for item in judgment.get("criteria") or []:
            if not isinstance(item, dict):
                continue
            criterion = pick(item, "criterion_id", "factor_key", "operator", "outcome_if_met",
                             "evidence_role", "human_check_required", "notes")
            if isinstance(item.get("threshold"), dict):
                criterion["threshold"] = pick(item["threshold"], "kind", "value", "values", "unit")
            criteria.append(criterion)
        result["sensor_judgment"]["criteria"] = criteria
    return result


def preserve_inspection_details(item: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Do not derive an approval/outcome from a checklist or an assigned actor."""
    record.update(pick(item, "outcome", "inspection_result_id", "work_order_id"))
    # Coordination is a separate production decision, not work-order acceptance.
    if isinstance(item.get("production_coordination"), dict):
        record["production_coordination"] = deepcopy(item["production_coordination"])
    elif str(item.get("activity_type", "")).startswith("inspection.coordination."):
        payload = item.get("payload") or {}
        if isinstance(payload, dict):
            coordination = pick(payload, "request_id", "work_order_id", "status")
            coordination.update({k: payload[k] for k in (
                "requested_at", "responded_at", "requested_by_name", "responded_by_name"
            ) if isinstance(payload.get(k), str)})
            coordination["request"] = pick(payload.get("request") or {},
                "work_summary", "downtime_minutes", "affected_items", "note")
            coordination["response"] = pick(payload.get("response") or {},
                "decision", "scheduled_window", "production_response")
            record["production_coordination"] = coordination
            record["status"] = str(payload.get("status") or record.get("status") or "")
    if "findings" in item:
        record["findings"] = [v for v in item["findings"] or [] if isinstance(v, str)]
    for name, fields in (("measurements", ("name", "value", "unit")),
                         ("checklist", ("item_id", "status", "note"))):
        if name in item:
            record[name] = [pick(v, *fields) for v in item[name] or [] if isinstance(v, dict)]
    return record


def briefing_activities(activities):
    """Keep decision/execution evidence even when routine timeline entries exceed five."""
    important = [r for r in activities if str(r.get("activity_type", "")).startswith(
        ("inspection.coordination.", "inspection.execution."))]
    routine = [r for r in activities if r not in important]
    return [*routine[-5:], *important]


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def record_context(item: dict[str, Any], *, packet: dict[str, Any]) -> dict[str, Any]:
    result = pick(item, "record_id", "record_type", "status", "activity_type", "recorded_at",
                  "summary", "source_ref", "owner_record_provenance")
    preserve_inspection_details(item, result)
    owner = item.get("owner_record_provenance") or {}
    # A row created earlier but updated/approved later cannot be backdated to its creation.
    stamps = [item.get("recorded_at")] + [owner.get(k) for k in (
        "recorded_at", "created_at", "updated_at", "approved_at", "started_at", "completed_at")]
    supplied = [v for v in stamps if v not in (None, "")]
    parsed = [_instant(v) for v in supplied]
    basis = packet.get("snapshot_basis") or {}
    as_of = (packet.get("maintenance_history_summary") or {}).get("workflow_as_of") or basis.get("observed_at") or packet.get("generated_at")
    cutoff = _instant(as_of)
    if cutoff is None or not parsed or any(v is None for v in parsed):
        temporal = "unknown"
    else:
        temporal = "after_basis" if max(parsed) > cutoff else "at_or_before_basis"
    identities = [owner[k] for k in ("asset_id", "equipment_id") if owner.get(k)]
    scope = "mismatch" if any(v != packet.get("asset_id") for v in identities) else (
        "matches_asset" if identities else "inherited_packet_scope")
    event = owner.get("event_id")
    result["record_context"] = {
        "decision_as_of": as_of, "temporal_relation": temporal, "asset_scope": scope,
        "event_relation": "other_event" if event and event != basis.get("event_id") else (
            "matches_event" if event else "unspecified"),
        "interpretation": "Recorded owner state only; not a new inspection, approval or execution.",
    }
    return result

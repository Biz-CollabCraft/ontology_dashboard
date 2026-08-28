"""Validation helpers for read-only agent review summaries."""

from __future__ import annotations

from typing import Any


FORBIDDEN_SUMMARY_FIELDS = {
    "action",
    "actions",
    "action_id",
    "approval",
    "approval_state",
    "approved",
    "auto_approve",
    "create_work_order",
    "maintenance_action",
    "maintenance_event",
    "replay",
    "state_patch",
    "work_order",
}

FORBIDDEN_SUMMARY_CLAIMS = (
    "실제 고장 예방 입증",
    "정비로 downtime 절감",
    "정비 완료 후 정상화",
    "SOP가 자동 정비 승인",
    "자동 승인 완료",
    "create_work_order",
    "approve_work_order",
    "start_maintenance_action",
    "complete_maintenance_action",
    "create_maintenance_event",
    "request_replay",
    "auto_approve",
)


def validate_agent_review_summary(
    summary: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> list[str]:
    """Return deterministic validation errors for an agent review summary."""

    errors: list[str] = []
    forbidden_fields = sorted(_walk_forbidden_fields(summary))
    if forbidden_fields:
        errors.append(f"forbidden_fields:{','.join(forbidden_fields)}")

    forbidden_claims = sorted(_walk_forbidden_claims(summary))
    if forbidden_claims:
        errors.append(f"forbidden_claims:{','.join(forbidden_claims)}")

    allowed_refs = {str(ref) for ref in packet.get("source_refs") or [] if str(ref)}
    summary_refs = [str(ref) for ref in summary.get("source_refs") or [] if str(ref)]
    if not summary_refs:
        errors.append("source_refs_missing")
    all_summary_refs = _collect_source_refs(summary)
    unknown_refs = sorted(all_summary_refs - allowed_refs)
    if unknown_refs:
        errors.append(f"source_refs_unknown:{','.join(unknown_refs)}")

    if summary.get("asset_id") != packet.get("asset_id"):
        errors.append("asset_id_mismatch")
    if summary.get("packet_schema_version") != packet.get("schema_version"):
        errors.append("packet_schema_version_mismatch")

    return errors


def _collect_source_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "source_refs" and isinstance(child, list):
                refs.update(str(item) for item in child if str(item))
            else:
                refs.update(_collect_source_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_collect_source_refs(child))
    return refs


def _walk_forbidden_fields(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key) in FORBIDDEN_SUMMARY_FIELDS:
                found.add(str(key))
            found.update(_walk_forbidden_fields(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_walk_forbidden_fields(child))
    return found


def _walk_forbidden_claims(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        for claim in FORBIDDEN_SUMMARY_CLAIMS:
            if claim in value:
                found.add(claim)
    elif isinstance(value, dict):
        for child in value.values():
            found.update(_walk_forbidden_claims(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_walk_forbidden_claims(child))
    return found

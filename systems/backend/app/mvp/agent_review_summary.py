"""Validation helpers for read-only agent review summaries."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


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


def compose_deterministic_agent_review_summary(packet: dict[str, Any]) -> dict[str, Any]:
    """Compose a read-only fallback summary from an Agent Review Packet."""

    draft = packet.get("review_draft") or {}
    targets = packet.get("inspection_targets") or []
    risk = packet.get("risk_summary") or {}
    source_refs = _packet_source_refs(packet)
    evidence_gaps = packet.get("evidence_gaps") or []
    confidence_label = _confidence_label(packet)
    title = _summary_title(packet)
    summary = _summary_text(packet=packet, draft=draft, risk=risk, targets=targets)

    return {
        "schema_version": "agent-review-summary-v1.0",
        "packet_schema_version": str(packet.get("schema_version") or ""),
        "asset_id": str(packet.get("asset_id") or ""),
        "generated_at": str(packet.get("generated_at") or ""),
        "mode": "deterministic_fallback",
        "title": title,
        "summary": summary,
        "history_summary": [str(item) for item in draft.get("history_summary") or []],
        "inspection_focus": [
            _inspection_focus(target=target, fallback_source_refs=source_refs)
            for target in targets
        ],
        "evidence_gaps": [
            {
                "field": str(gap.get("field") or ""),
                "reason": str(gap.get("reason") or ""),
                "owner_domain": str(gap.get("owner_domain") or ""),
            }
            for gap in evidence_gaps
        ],
        "source_refs": source_refs,
        "boundary_note": str(
            draft.get("boundary_note")
            or "읽기 전용 검토 요약이며 정비 상태를 변경하지 않습니다."
        ),
        "confidence_label": confidence_label,
        "limitations": [str(item) for item in packet.get("limitations") or []],
    }


def validated_agent_review_summary(
    *,
    packet: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Return a candidate summary when valid, otherwise return deterministic fallback."""

    if candidate is not None:
        errors = validate_agent_review_summary_contract(candidate, packet=packet)
        if candidate.get("mode") != "llm":
            errors.append("mode_invalid_for_candidate")
        if not errors:
            return candidate, []

    fallback = compose_deterministic_agent_review_summary(packet)
    return fallback, validate_agent_review_summary_contract(fallback, packet=packet)


def validate_agent_review_summary_contract(
    summary: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> list[str]:
    """Validate both the public schema shape and packet-grounding invariants."""

    return [
        *_summary_schema_errors(summary),
        *validate_agent_review_summary(summary, packet=packet),
    ]


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
    if summary.get("generated_at") != packet.get("generated_at"):
        errors.append("generated_at_mismatch")
    if summary.get("packet_schema_version") != packet.get("schema_version"):
        errors.append("packet_schema_version_mismatch")
    if summary.get("confidence_label") != _confidence_label(packet):
        errors.append("confidence_label_mismatch")

    inspection_errors = _validate_inspection_focus(summary, packet=packet)
    errors.extend(inspection_errors)
    gap_errors = _validate_evidence_gaps(summary, packet=packet)
    errors.extend(gap_errors)

    return errors


def _summary_title(packet: dict[str, Any]) -> str:
    asset_id = str(packet.get("asset_id") or "설비")
    risk = packet.get("risk_summary") or {}
    status = risk.get("status_grade")
    if status:
        return f"AI 검토 요약 · {asset_id} · {status}"
    return f"AI 검토 요약 · {asset_id} · 데이터 품질 보류"


def _summary_text(
    *,
    packet: dict[str, Any],
    draft: dict[str, Any],
    risk: dict[str, Any],
    targets: list[dict[str, Any]],
) -> str:
    status = risk.get("status_grade")
    probability = risk.get("failure_probability")
    if isinstance(probability, (int, float)) and not isinstance(probability, bool):
        probability_text = f"{float(probability) * 100:.1f}%"
    else:
        probability_text = "미제공"

    if status:
        base = f"{packet.get('asset_id', '')}는 현재 {status} 상태이며 예측 위험도는 {probability_text}입니다."
    else:
        base = (
            f"{packet.get('asset_id', '')}는 데이터 품질 보류 상태라 위험 등급과 "
            "예측 위험도를 확정하지 않습니다."
        )

    if targets:
        labels = ", ".join(
            str(target.get("component_label") or target.get("component_id") or "의심 부품")
            for target in targets[:3]
        )
        return f"{base} {labels} 중심으로 이력, 현장 위치, 관측 근거를 함께 확인해야 합니다."

    if packet.get("evidence_gaps"):
        return f"{base} 근거 공백이 있어 확정 판단보다 데이터 보강과 이력 조회가 우선입니다."

    return str(draft.get("summary") or base)


def _inspection_focus(
    *,
    target: dict[str, Any],
    fallback_source_refs: list[str],
) -> dict[str, Any]:
    refs = [
        str(target.get("source_ref") or ""),
        str(target.get("location_source_ref") or ""),
    ]
    source_refs = [ref for ref in refs if ref and ref in fallback_source_refs]
    return {
        "component_id": str(target.get("component_id") or ""),
        "component_label": str(target.get("component_label") or ""),
        "location_label": target.get("location_label"),
        "basis_refs": [str(ref) for ref in target.get("basis_refs") or []],
        "source_refs": source_refs or fallback_source_refs[:1],
    }


def _confidence_label(packet: dict[str, Any]) -> str:
    risk = packet.get("risk_summary") or {}
    if risk.get("status_grade") is None or risk.get("failure_probability") is None:
        return "data_quality_hold"
    if packet.get("sop_guidance") and packet.get("inspection_targets"):
        return "grounded"
    if packet.get("inspection_targets") or packet.get("evidence_gaps"):
        return "partial"
    return "fallback"


def _packet_source_refs(packet: dict[str, Any]) -> list[str]:
    refs = [str(ref) for ref in packet.get("source_refs") or [] if str(ref)]
    return list(dict.fromkeys(refs))


def _validate_inspection_focus(summary: dict[str, Any], *, packet: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    targets_by_component = {
        str(target.get("component_id") or ""): target
        for target in packet.get("inspection_targets") or []
        if str(target.get("component_id") or "")
    }
    focus_items = summary.get("inspection_focus") or []
    if focus_items and not targets_by_component:
        return ["inspection_focus_unavailable"]

    for index, focus in enumerate(focus_items):
        component_id = str(focus.get("component_id") or "")
        target = targets_by_component.get(component_id)
        if target is None:
            errors.append(f"inspection_focus[{index}].component_id_unknown:{component_id}")
            continue
        if focus.get("component_label") != target.get("component_label"):
            errors.append(f"inspection_focus[{index}].component_label_mismatch")
        if focus.get("location_label") != target.get("location_label"):
            errors.append(f"inspection_focus[{index}].location_label_mismatch")
        allowed_basis_refs = {str(ref) for ref in target.get("basis_refs") or [] if str(ref)}
        unknown_basis_refs = sorted(
            str(ref)
            for ref in focus.get("basis_refs") or []
            if str(ref) not in allowed_basis_refs
        )
        if unknown_basis_refs:
            errors.append(
                f"inspection_focus[{index}].basis_refs_unknown:{','.join(unknown_basis_refs)}"
            )
    return errors


def _validate_evidence_gaps(summary: dict[str, Any], *, packet: dict[str, Any]) -> list[str]:
    packet_gaps = {_gap_key(gap) for gap in packet.get("evidence_gaps") or []}
    summary_gaps = {_gap_key(gap) for gap in summary.get("evidence_gaps") or []}
    missing_gaps = sorted(packet_gaps - summary_gaps)
    if not missing_gaps:
        return []
    rendered = ",".join("|".join(gap) for gap in missing_gaps)
    return [f"evidence_gaps_missing:{rendered}"]


def _gap_key(gap: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(gap.get("field") or ""),
        str(gap.get("reason") or ""),
        str(gap.get("owner_domain") or ""),
    )


def _summary_schema_errors(summary: dict[str, Any]) -> list[str]:
    errors = sorted(
        _summary_schema_validator().iter_errors(summary),
        key=lambda item: list(item.absolute_path),
    )
    return [
        f"schema:{'.'.join(str(part) for part in error.absolute_path) or '$'}:{error.message}"
        for error in errors
    ]


@lru_cache(maxsize=1)
def _summary_schema_validator() -> Draft202012Validator:
    schema_path = (
        Path(__file__).resolve().parents[4]
        / "contracts"
        / "schemas"
        / "agent-review-summary.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


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

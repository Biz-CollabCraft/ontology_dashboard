"""Validation helpers for read-only agent review summaries."""

from __future__ import annotations

import json
import re
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

FORBIDDEN_PROSE_CLAIMS = (
    "승인 절차가 자동으로 진행",
    "자동승인 완료",
    "자동 승인 완료",
    "정비를 마감 처리",
    "정비 마감 처리",
    "작업요청 종결",
    "작업 요청 종결",
    "교체 완료",
    "정비 완료",
    "수리 완료",
    "repair success",
    "execute approval",
    "auto approval",
)

ROLE_SUMMARY_DEFINITIONS = (
    ("field_operator", "현장 담당자"),
    ("process_manager", "공정 관리자"),
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
        "role_summaries": _role_summaries(packet=packet, source_refs=source_refs),
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
        "data_footnotes": _data_footnotes(packet=packet, source_refs=source_refs),
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
    text_errors = _validate_natural_language_grounding(summary, packet=packet)
    errors.extend(text_errors)

    return errors


def _summary_title(packet: dict[str, Any]) -> str:
    asset_label = _asset_label(packet)
    risk = packet.get("risk_summary") or {}
    status = risk.get("status_grade")
    if status:
        return f"AI 검토 요약 · {asset_label} · {status}"
    return f"AI 검토 요약 · {asset_label} · 데이터 품질 보류"


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
        base = f"{_asset_label(packet)}는 현재 {status} 상태이며 예측 위험도는 {probability_text}입니다."
    else:
        base = (
            f"{_asset_label(packet)}는 데이터 품질 보류 상태라 위험 등급과 "
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


def _role_summaries(
    *,
    packet: dict[str, Any],
    source_refs: list[str],
) -> list[dict[str, Any]]:
    risk = packet.get("risk_summary") or {}
    targets = packet.get("inspection_targets") or []
    operation_context = packet.get("operation_context_summary") or {}
    asset_label = _asset_label(packet)
    status = str(risk.get("status_grade") or "데이터 품질 보류")
    production_impact = _production_impact_label(operation_context.get("production_impact"))
    downtime = operation_context.get("estimated_downtime_minutes")
    lost_units = operation_context.get("estimated_lost_units")
    lost_units_text = f"{int(lost_units)}개" if isinstance(lost_units, (int, float)) else "추정 물량"
    downtime_text = f"{int(downtime)}분" if isinstance(downtime, (int, float)) else "예상 정지"
    component_text = _component_text(targets)
    location_text = _location_text(targets)
    factor_text = _factor_text(targets)
    primary_refs = source_refs[:3] or _packet_source_refs(packet)[:1]

    quotes = {
        "field_operator": (
            f"{asset_label}은 {status} 알림이며 {component_text}{_object_particle(component_text)} "
            f"{location_text}에서 먼저 확인할 대상으로 잡습니다. "
            f"근거 지표는 {factor_text}이고, 현장 확인 결과는 승인 판단 전 조회 이력에 붙일 수 있습니다."
        ),
        "process_manager": (
            f"현재 생산 영향은 {production_impact}입니다. {downtime_text} 기준 {lost_units_text} 손실 가능성이 있어 "
            "점검 승인 여부와 셀 작업 순서 조정을 함께 봐야 합니다."
        ),
    }
    return [
        {
            "role": role,
            "label": label,
            "quote": quotes[role],
            "source_refs": primary_refs,
        }
        for role, label in ROLE_SUMMARY_DEFINITIONS
    ]


def _asset_label(packet: dict[str, Any]) -> str:
    return str(packet.get("asset_label") or packet.get("asset_id") or "설비")


def _data_footnotes(
    *,
    packet: dict[str, Any],
    source_refs: list[str],
) -> list[dict[str, Any]]:
    refs = source_refs[:1]
    footnotes = [
        {
            "code": str(gap.get("field") or ""),
            "note": _gap_note(gap),
            "owner_domain": str(gap.get("owner_domain") or ""),
            "source_refs": refs,
        }
        for gap in packet.get("evidence_gaps") or []
    ]
    operation_context = packet.get("operation_context_summary") or {}
    for index, limitation in enumerate(operation_context.get("limitations") or []):
        text = str(limitation)
        if not text:
            continue
        footnotes.append(
            {
                "code": f"operation_context.limitations.{index + 1}",
                "note": _limitation_note(text),
                "owner_domain": "operations",
                "source_refs": refs,
            }
        )
    return footnotes[:7]


def _production_impact_label(value: Any) -> str:
    labels = {
        "none": "없음",
        "low": "낮은 수준",
        "medium": "중간 수준",
        "high": "높은 수준",
    }
    return labels.get(str(value), "미제공")


def _component_text(targets: list[dict[str, Any]]) -> str:
    labels = [
        str(target.get("component_label") or target.get("component_id") or "")
        for target in targets[:2]
    ]
    labels = [label for label in labels if label]
    return ", ".join(labels) if labels else "의심 계통"


def _object_particle(value: str) -> str:
    if not value:
        return "을"
    code = ord(value[-1])
    if not (0xAC00 <= code <= 0xD7A3):
        return "을"
    return "을" if (code - 0xAC00) % 28 else "를"


def _location_text(targets: list[dict[str, Any]]) -> str:
    locations = [
        str(target.get("location_label") or "")
        for target in targets[:2]
        if str(target.get("location_label") or "")
    ]
    return ", ".join(locations) if locations else "연결된 점검 위치"


def _factor_text(targets: list[dict[str, Any]]) -> str:
    refs = []
    for target in targets:
        refs.extend(str(ref).split(".", 2)[-1] for ref in target.get("basis_refs") or [])
    refs = [ref for ref in refs if ref]
    return ", ".join(list(dict.fromkeys(refs))[:3]) if refs else "패킷 근거"


def _gap_note(gap: dict[str, Any]) -> str:
    field = str(gap.get("field") or "unknown")
    labels = {
        "risk_series": "위험도 시계열이 부족해 악화 추세를 확정하기 어렵습니다.",
        "maintenance_context.similar_events_30d": "최근 30일 유사 이벤트 이력이 없어 재발 판단은 보류됩니다.",
        "maintenance_context.open_work_order_exists": "열린 작업요청 여부가 없어 중복 요청 여부를 확정하기 어렵습니다.",
        "operation_context.load_level": "부하 수준이 없어 생산 맥락의 압박도를 확정하기 어렵습니다.",
        "operation_context.runtime_hours_7d": "최근 7일 가동 시간이 없어 누적 운전 맥락을 확정하기 어렵습니다.",
        "operation_context.production_impact": "생산 영향도가 없어 공정 우선순위 판단이 제한됩니다.",
        "review_priority": "우선순위 입력 일부가 없어 자동 산정 결과를 확정하지 않습니다.",
    }
    return labels.get(field, f"{field} 데이터가 없어 해당 판단은 보류됩니다.")


def _limitation_note(value: str) -> str:
    if "MES" in value or "loss" in value.lower():
        return "실제 MES 실적이 연결되기 전까지 손실 물량은 계획 기준 추정입니다."
    if "납기" in value:
        return "납기 영향은 별도 수주/출하 일정이 연결될 때 확정할 수 있습니다."
    if "Maintenance" in value or "maintenance" in value:
        return "정비 후 효과는 조치 완료 뒤 재관측 데이터가 쌓여야 판단할 수 있습니다."
    return value


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
    packet_targets = packet.get("inspection_targets") or []
    targets_by_component = _targets_by_component(packet)
    focus_items = summary.get("inspection_focus") or []
    if focus_items and not targets_by_component:
        return ["inspection_focus_unavailable"]
    if len(focus_items) != len(packet_targets):
        errors.append(
            f"inspection_focus_count_mismatch:{len(focus_items)}!={len(packet_targets)}"
        )

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
        allowed_source_refs = _target_allowed_source_refs(target, packet=packet)
        focus_source_refs = {
            str(ref) for ref in focus.get("source_refs") or [] if str(ref)
        }
        if not focus_source_refs:
            errors.append(f"inspection_focus[{index}].source_refs_missing")
        unknown_source_refs = sorted(focus_source_refs - allowed_source_refs)
        if unknown_source_refs:
            errors.append(
                f"inspection_focus[{index}].source_refs_not_target_grounded:{','.join(unknown_source_refs)}"
            )
    return errors


def _validate_evidence_gaps(summary: dict[str, Any], *, packet: dict[str, Any]) -> list[str]:
    packet_gaps = {_gap_key(gap) for gap in packet.get("evidence_gaps") or []}
    summary_gaps = {_gap_key(gap) for gap in summary.get("evidence_gaps") or []}
    missing_gaps = sorted(packet_gaps - summary_gaps)
    extra_gaps = sorted(summary_gaps - packet_gaps)
    errors = []
    if missing_gaps:
        rendered = ",".join("|".join(gap) for gap in missing_gaps)
        errors.append(f"evidence_gaps_missing:{rendered}")
    if extra_gaps:
        rendered = ",".join("|".join(gap) for gap in extra_gaps)
        errors.append(f"evidence_gaps_unknown:{rendered}")
    return errors


def _validate_natural_language_grounding(
    summary: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    draft = packet.get("review_draft") or {}
    if summary.get("boundary_note") != draft.get("boundary_note"):
        errors.append("boundary_note_mismatch")

    missing_limitations = sorted(
        set(str(item) for item in packet.get("limitations") or [])
        - set(str(item) for item in summary.get("limitations") or [])
    )
    if missing_limitations:
        errors.append("limitations_missing")

    if [str(item) for item in summary.get("history_summary") or []] != [
        str(item) for item in draft.get("history_summary") or []
    ]:
        errors.append("history_summary_mismatch")

    prose_values = _generated_natural_language_values(summary)
    forbidden_claims = sorted(_normalized_forbidden_prose_claims(prose_values))
    if forbidden_claims:
        errors.append(f"forbidden_prose_claims:{','.join(forbidden_claims)}")

    directive_claims = sorted(_directive_prose_claims(prose_values))
    if directive_claims:
        errors.append(f"directive_prose_claims:{','.join(directive_claims)}")

    echoed_actions = sorted(_available_action_echoes(prose_values, packet=packet))
    if echoed_actions:
        errors.append(f"available_action_echo:{','.join(echoed_actions)}")

    probability_errors = _validate_prose_probabilities(prose_values, packet=packet)
    errors.extend(probability_errors)
    priority_errors = _validate_prose_priorities(prose_values, packet=packet)
    errors.extend(priority_errors)
    return errors


def _gap_key(gap: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(gap.get("field") or ""),
        str(gap.get("reason") or ""),
        str(gap.get("owner_domain") or ""),
    )


def _targets_by_component(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(target.get("component_id") or ""): target
        for target in packet.get("inspection_targets") or []
        if str(target.get("component_id") or "")
    }


def _target_allowed_source_refs(
    target: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> set[str]:
    refs = {
        str(target.get("source_ref") or ""),
        str(target.get("location_source_ref") or ""),
    }
    component_id = str(target.get("component_id") or "")
    refs.update(
        str(guidance.get("source_ref") or "")
        for guidance in packet.get("sop_guidance") or []
        if str(guidance.get("component_id") or "") == component_id
    )
    refs.update(
        str(guidance.get("location_source_ref") or "")
        for guidance in packet.get("sop_guidance") or []
        if str(guidance.get("component_id") or "") == component_id
    )
    return {ref for ref in refs if ref}


def _generated_natural_language_values(summary: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("title", "summary"):
        value = summary.get(key)
        if isinstance(value, str):
            values.append(value)
    for item in summary.get("role_summaries") or []:
        if isinstance(item, dict) and isinstance(item.get("quote"), str):
            values.append(str(item["quote"]))
    for item in summary.get("data_footnotes") or []:
        if isinstance(item, dict) and isinstance(item.get("note"), str):
            values.append(str(item["note"]))
    return values


def _normalized_forbidden_prose_claims(values: list[str]) -> set[str]:
    text = _normalize_claim_text(" ".join(values))
    return {
        claim
        for claim in FORBIDDEN_PROSE_CLAIMS
        if _normalize_claim_text(claim) in text
    }


def _directive_prose_claims(values: list[str]) -> set[str]:
    text = " ".join(values)
    patterns = (
        r"(?:교체|생성|승인|발행|마감|종결|완료|수리|정비)[^.?!\n]{0,20}(?:하십시오|하세요|바랍니다)",
        r"(?:정비|교체|수리)[^.?!\n]{0,20}반드시\s*필요",
    )
    claims: set[str] = set()
    for pattern in patterns:
        claims.update(match.group(0).strip() for match in re.finditer(pattern, text, flags=re.IGNORECASE))
    return claims


def _available_action_echoes(values: list[str], *, packet: dict[str, Any]) -> set[str]:
    text = _normalize_claim_text(" ".join(values))
    return {
        action_id
        for action_id in (
            str(item)
            for item in (packet.get("closed_loop_boundary") or {}).get(
                "available_action_ids"
            )
            or []
        )
        if action_id and _normalize_claim_text(action_id) in text
    }


def _validate_prose_probabilities(
    values: list[str],
    *,
    packet: dict[str, Any],
) -> list[str]:
    percentage_matches = sorted(
        set(re.findall(r"\d+(?:\.\d+)?\s*%", " ".join(values)))
    )
    if not percentage_matches:
        return []
    probability = (packet.get("risk_summary") or {}).get("failure_probability")
    unknown: list[str] = []
    expected = None
    if isinstance(probability, (int, float)) and not isinstance(probability, bool):
        expected = float(probability) * 100
    for value in percentage_matches:
        rendered = value.replace(" ", "")
        if expected is None:
            unknown.append(rendered)
            continue
        observed = float(rendered.rstrip("%"))
        tolerance = 0.5 if "." not in rendered else 0.05
        if abs(observed - expected) > tolerance:
            unknown.append(rendered)
    if unknown:
        return [f"prose_probability_mismatch:{','.join(unknown)}"]
    return []


def _validate_prose_priorities(
    values: list[str],
    *,
    packet: dict[str, Any],
) -> list[str]:
    text = " ".join(values).casefold()
    labels = ("immediate", "high", "medium", "low")
    mentioned = sorted(
        label
        for label in labels
        if re.search(rf"(?<![a-z0-9_]){re.escape(label)}(?![a-z0-9_])", text)
    )
    if not mentioned:
        return []
    allowed = str((packet.get("review_priority") or {}).get("level") or "")
    unknown = [label for label in mentioned if label != allowed]
    if unknown:
        return [f"prose_priority_mismatch:{','.join(unknown)}"]
    return []


def _normalize_claim_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


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
def summary_schema() -> dict[str, Any]:
    schema_path = (
        Path(__file__).resolve().parents[4]
        / "contracts"
        / "schemas"
        / "agent-review-summary.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _summary_schema_validator() -> Draft202012Validator:
    return Draft202012Validator(summary_schema())


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

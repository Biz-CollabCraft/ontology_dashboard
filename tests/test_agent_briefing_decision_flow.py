import json
from pathlib import Path

from app.operations.agent_briefing_review import build_decision_flow, decision_facts
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_provider import (
    AGENT_REVIEW_SUMMARY_PROMPT_VERSION,
    AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
    build_agent_review_summary_prompt_payload,
    build_tool_selected_agent_review_summary_prompt_payload,
)
from app.operations.context_providers import _history_record

ROOT = Path(__file__).resolve().parents[1]


def packet(case="GS-002"):
    return json.loads((ROOT / f"tests/fixtures/agent_review_packets/{case}.json").read_text())


def approved_work_order_packet():
    p = packet("GS-002")
    inspection = _history_record({
        "inspection_result_id": "IR-REVIEW-001",
        "work_order_id": "WO-INSPECT-001",
        "asset_id": p["asset_id"],
        "event_id": p["snapshot_basis"]["event_id"],
        "status": "maintenance_recommended",
        "outcome": "maintenance_recommended",
        "recorded_at": "2026-07-31T23:40:00+09:00",
        "findings": ["커플링 정렬 점검에서 편심 확인"],
        "checklist": [{"item_id": "alignment", "status": "fail", "note": "커플링 편심 확인"}],
    }, source_prefix="closed-loop://inspection-result")
    work_order = _history_record({
        "work_order_id": "WO-REVIEW-001",
        "asset_id": p["asset_id"],
        "event_id": p["snapshot_basis"]["event_id"],
        "status": "approved",
        "label": "커플링 정렬 보정 작업요청",
        "recorded_at": "2026-07-31T23:45:00+09:00",
        "created_at": "2026-07-31T23:45:00+09:00",
        "updated_at": "2026-07-31T23:55:00+09:00",
        "approved_at": "2026-07-31T23:55:00+09:00",
    }, source_prefix="closed-loop://work-order")
    p["maintenance_history_summary"]["inspection_results"] = [inspection]
    p["maintenance_history_summary"]["work_orders"] = [work_order]
    p["maintenance_history_summary"]["open_work_order_exists"] = True
    p.setdefault("evidence_context", {}).setdefault("selected_basis", []).append({
        "candidate_id": "limitation:relation-gap:maintenance_readiness:test",
        "candidate_type": "limitation",
        "source_ref": "relation-gap:maintenance_readiness",
        "domain": "maintenance_readiness",
        "relation_path": ["relation_gap"],
        "fact_type": "relation_gap",
        "as_of": "2026-07-31T15:00:00Z",
        "required_for_boundary": True,
        "limitation_state": "missing",
    })
    p["source_refs"] = list(dict.fromkeys([*p["source_refs"], inspection["source_ref"], work_order["source_ref"], "context:maintenance_readiness", "relation-gap:maintenance_readiness"]))
    return p


def step_names(flow):
    return [step["step"] for step in flow["primary_chain"]]


def test_decision_flow_orders_approved_work_order_case_as_a_connected_chain():
    flow = build_decision_flow(approved_work_order_packet())

    assert flow["flow_version"] == "decision-flow-v1"
    assert flow["current_stage"] == "approved_work_order_pending_start"
    assert flow["stage_label"] == "승인된 작업요청의 착수 조건 판단"
    assert step_names(flow) == [
        "risk_factors_exceed_sop",
        "inspection_targets_identified",
        "inspection_result_recorded",
        "work_order_approved",
        "execution_not_confirmed",
        "readiness_gap",
        "production_decision",
    ]

    work_order = next(step for step in flow["primary_chain"] if step["step"] == "work_order_approved")
    assert work_order["facts"] == [{
        "label": "커플링 정렬 보정 작업요청",
        "status": "approved",
        "recorded_at": "2026-07-31T23:45:00+09:00",
        "approved_at": "2026-07-31T23:55:00+09:00",
        "source_ref": "closed-loop://work-order/WO-REVIEW-001",
    }]

    readiness = next(step for step in flow["primary_chain"] if step["step"] == "readiness_gap")
    assert [fact["label"] for fact in readiness["facts"]] == ["실제 재고 수량 미확인", "작업 가능 시간 미확인"]


def test_decision_flow_does_not_invent_approval_for_basic_gold_case():
    flow = build_decision_flow(packet("GS-002"))

    assert flow["current_stage"] == "risk_review_pending_inspection"
    assert "work_order_approved" not in step_names(flow)
    assert "execution_not_confirmed" not in step_names(flow)


def test_decision_flow_keeps_data_quality_hold_from_using_production_plan_values():
    p = packet("GS-007")
    facts = decision_facts(p)
    flow = build_decision_flow(p, facts)

    assert flow["current_stage"] == "data_quality_hold_pending_observation"
    assert step_names(flow) == ["production_impact_unconfirmed"]
    assert facts["operation_context"] == {
        "production_impact": None,
        "estimated_downtime_minutes": None,
        "estimated_lost_units": None,
        "status": "unconfirmed_due_to_data_quality",
    }


def test_prompt_payload_includes_same_decision_flow_on_both_context_paths():
    p = approved_work_order_packet()
    baseline = compose_deterministic_agent_review_summary(p)

    direct = build_agent_review_summary_prompt_payload(packet=p, baseline_summary=baseline)
    tool_selected = build_tool_selected_agent_review_summary_prompt_payload(packet=p, baseline_summary=baseline)

    assert direct["decision_flow"] == tool_selected["decision_flow"]
    assert direct["decision_flow"]["current_stage"] == "approved_work_order_pending_start"


def test_prompt_version_and_system_prompt_explain_decision_flow_contract():
    assert AGENT_REVIEW_SUMMARY_PROMPT_VERSION == "agent-review-summary-prompt-v3.5-expression-boundaries"
    assert "해당 입력과 문장에 실제로 있는 표현만 강조" in AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT
    assert "decision_flow는 코드가 만든 결정론적 관계 순서" in AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT
    assert "현재 상태 → 원인 관계 → 확인된 기록 → 남은 공백 → 다음 판단" in AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT

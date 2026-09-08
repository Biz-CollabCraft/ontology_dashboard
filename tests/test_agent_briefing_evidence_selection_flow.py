import json
from copy import deepcopy
from pathlib import Path

from app.operations.agent_briefing_review import build_decision_flow, decision_facts
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_provider import build_tool_selected_agent_review_summary_prompt_payload
from app.operations.context_providers import _history_record

ROOT = Path(__file__).resolve().parents[1]


def packet(case="GS-002"):
    return json.loads((ROOT / f"tests/fixtures/agent_review_packets/{case}.json").read_text())


def add_work_order(p, **overrides):
    raw = {
        "work_order_id": overrides.pop("work_order_id", "WO-REVIEW-001"),
        "asset_id": p["asset_id"],
        "event_id": p["snapshot_basis"]["event_id"],
        "status": "approved",
        "label": "커플링 정렬 보정 작업요청",
        "recorded_at": "2026-07-31T23:45:00+09:00",
        "created_at": "2026-07-31T23:45:00+09:00",
        "updated_at": "2026-07-31T23:55:00+09:00",
        "approved_at": "2026-07-31T23:55:00+09:00",
        **overrides,
    }
    record = _history_record(raw, source_prefix="closed-loop://work-order")
    p["maintenance_history_summary"]["work_orders"] = [record]
    p["source_refs"] = list(dict.fromkeys([*p["source_refs"], record["source_ref"]]))
    return record


def add_inspection_result(p):
    record = _history_record({
        "inspection_result_id": "IR-REVIEW-001",
        "work_order_id": "WO-INSPECT-001",
        "asset_id": p["asset_id"],
        "event_id": p["snapshot_basis"]["event_id"],
        "status": "maintenance_recommended",
        "outcome": "maintenance_recommended",
        "recorded_at": "2026-07-31T23:40:00+09:00",
        "findings": ["커플링 정렬 점검에서 편심 확인"],
    }, source_prefix="closed-loop://inspection-result")
    p["maintenance_history_summary"]["inspection_results"] = [record]
    p["source_refs"] = list(dict.fromkeys([*p["source_refs"], record["source_ref"]]))
    return record


def add_relation_gap(p, domain):
    context = p.setdefault("evidence_context", {})
    context.setdefault("selected_basis", []).append({
        "candidate_id": f"limitation:relation-gap:{domain}:test",
        "candidate_type": "limitation",
        "source_ref": f"relation-gap:{domain}",
        "domain": domain,
        "relation_path": ["relation_gap"],
        "fact_type": "relation_gap",
        "as_of": "2026-07-31T15:00:00Z",
        "value_summary": "required context is not connected",
        "freshness_state": "unknown",
        "required_for_boundary": True,
        "limitation_state": "missing",
    })
    p["source_refs"] = list(dict.fromkeys([*p["source_refs"], f"context:{domain}", f"relation-gap:{domain}"]))


def payload_for(p):
    return build_tool_selected_agent_review_summary_prompt_payload(
        packet=p, baseline_summary=compose_deterministic_agent_review_summary(p)
    )


def test_selection_flow_uses_only_same_asset_event_records_as_current_facts():
    p = packet("GS-002")
    add_inspection_result(p)
    add_work_order(p)

    facts = decision_facts(p)
    flow = build_decision_flow(p, facts)

    assert [item["record_id"] for item in facts["inspection_results"]] == ["IR-REVIEW-001"]
    assert [item["record_id"] for item in facts["work_orders"]] == ["WO-REVIEW-001"]
    assert "inspection_result_recorded" in [step["step"] for step in flow["primary_chain"]]
    assert "work_order_approved" in [step["step"] for step in flow["primary_chain"]]


def test_selection_flow_excludes_after_basis_approval_from_current_state_but_keeps_audit_metadata():
    p = packet("GS-002")
    add_work_order(p, approved_at="2026-08-01T00:05:00+09:00", updated_at="2026-08-01T00:05:00+09:00")

    payload = payload_for(p)
    facts = payload["decision_facts"]
    history = payload["summary_context"]["maintenance_history"]

    assert facts["work_orders"] == []
    assert facts["excluded_records"]
    assert history["work_orders"] == []
    assert history["reference_history"][0]["record_context"]["temporal_relation"] == "after_basis"
    assert "work_order_approved" not in [step["step"] for step in payload["decision_flow"]["primary_chain"]]


def test_selection_flow_excludes_other_asset_and_other_event_approval():
    for overrides, expected_scope in [
        ({"asset_id": "CNC-OTHER"}, "mismatch"),
        ({"event_id": "EVT-OTHER"}, "other_event"),
    ]:
        p = packet("GS-002")
        add_work_order(p, **overrides)
        payload = payload_for(p)
        excluded = payload["decision_facts"]["excluded_records"]

        assert payload["decision_facts"]["work_orders"] == []
        assert excluded
        assert expected_scope in str(excluded)
        assert "work_order_approved" not in [step["step"] for step in payload["decision_flow"]["primary_chain"]]


def test_selected_evidence_keeps_rejected_basis_out_of_prompt_and_readiness_gap_in_flow():
    p = packet("GS-002")
    add_inspection_result(p)
    add_work_order(p)
    add_relation_gap(p, "maintenance_readiness")
    p["evidence_context"]["rejected_basis"] = [{"source_ref": "rejected:probe", "value_summary": "REJECTED_PROBE"}]

    payload = payload_for(p)
    selected = payload["summary_context"]["selected_evidence"]
    flow = payload["decision_flow"]

    assert any(item["source_ref"] == "relation-gap:maintenance_readiness" for item in selected["selected_basis"])
    assert "REJECTED_PROBE" not in json.dumps(payload, ensure_ascii=False)
    readiness = next(step for step in flow["primary_chain"] if step["step"] == "readiness_gap")
    assert [fact["label"] for fact in readiness["facts"]] == ["실제 재고 수량 미확인", "작업 가능 시간 미확인"]


def test_selection_flow_is_deterministic_under_history_record_reordering():
    p = packet("GS-002")
    older = _history_record({
        "work_order_id": "WO-REVIEW-001",
        "asset_id": p["asset_id"],
        "event_id": p["snapshot_basis"]["event_id"],
        "status": "requested",
        "label": "커플링 정렬 보정 작업요청",
        "recorded_at": "2026-07-31T23:45:00+09:00",
        "created_at": "2026-07-31T23:45:00+09:00",
    }, source_prefix="closed-loop://work-order")
    newer = _history_record({
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

    flows = []
    for records in ([older, newer], [newer, older]):
        candidate = deepcopy(p)
        candidate["maintenance_history_summary"]["work_orders"] = records
        candidate["source_refs"] = list(dict.fromkeys([*candidate["source_refs"], older["source_ref"], newer["source_ref"]]))
        flows.append(payload_for(candidate)["decision_flow"])

    assert flows[0] == flows[1]
    assert flows[0]["current_stage"] == "approved_work_order_pending_start"

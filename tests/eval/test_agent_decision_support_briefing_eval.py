from __future__ import annotations

from pathlib import Path
from typing import Any

from app.dependencies import build_manufacturing_service
from app.operations.agent_context_tool_pipeline import run_read_only_tool_pipeline
from app.operations.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    validate_agent_review_summary_contract,
)


ROOT = Path(__file__).resolve().parents[2]

EVAL_CASES = (
    {
        "case_id": "decision-support-critical",
        "asset_id": "CNC-S04-L02-03",
        "status_grade": "critical",
        "priority": "immediate",
        "expected_first_tools": [
            "model_evidence.lookup",
            "maintenance_history.lookup",
            "operation_context.lookup",
        ],
        "requires_loss_context": True,
    },
    {
        "case_id": "decision-support-warning",
        "asset_id": "CNC-S04-L04-01",
        "status_grade": "warning",
        "priority": "high",
        "expected_first_tools": [
            "model_evidence.lookup",
            "maintenance_history.lookup",
            "inspection_location.lookup",
        ],
        "requires_loss_context": True,
    },
    {
        "case_id": "decision-support-data-quality-hold",
        "asset_id": "CNC-S04-L05-01",
        "status_grade": None,
        "priority": None,
        "expected_first_tools": ["data_quality.lookup"],
        "requires_loss_context": False,
    },
    {
        "case_id": "decision-support-normal",
        "asset_id": "CNC-S01-L01-01",
        "status_grade": "normal",
        "priority": "low",
        "expected_first_tools": [
            "model_evidence.lookup",
            "maintenance_history.lookup",
            "inspection_location.lookup",
        ],
        "requires_loss_context": False,
    },
)


def test_ai_decision_support_required_judgment_items_are_present(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "decision-support-items.db", root=ROOT)

    for case in EVAL_CASES:
        packet = service.agent_review_packet(case["asset_id"])
        summary = compose_deterministic_agent_review_summary(packet)

        assert validate_agent_review_summary_contract(summary, packet=packet) == []
        assert _risk_state_is_expressed(summary, packet=packet), case["case_id"]
        assert _inspection_focus_matches_packet(summary, packet=packet), case["case_id"]
        assert _evidence_gaps_are_preserved(summary, packet=packet), case["case_id"]
        assert _hold_or_limitations_are_expressed(summary, packet=packet), case["case_id"]

        process_quote = _role_quote(summary, "process_manager")
        assert "생산 영향" in process_quote
        assert "점검 승인 여부" in process_quote
        if case["requires_loss_context"]:
            assert "손실 가능성" in process_quote


def test_ai_decision_support_roles_keep_different_judgment_materials(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "decision-support-roles.db", root=ROOT)

    for case in EVAL_CASES:
        packet = service.agent_review_packet(case["asset_id"])
        summary = compose_deterministic_agent_review_summary(packet)
        field_quote = _role_quote(summary, "field_operator")
        manager_quote = _role_quote(summary, "process_manager")

        assert field_quote != manager_quote
        assert "확인합니다" in field_quote
        assert "기록해 정비/생산 관리자에게 전달합니다" in field_quote
        assert "생산 영향" not in field_quote
        assert "손실 가능성" not in field_quote
        assert "생산 영향" in manager_quote
        if case["status_grade"] is None:
            assert "확정하지 않습니다" in manager_quote
        else:
            assert "셀 작업 순서" in manager_quote


def test_ai_decision_support_priority_changes_first_context_by_situation(
    tmp_path: Path,
) -> None:
    service = build_manufacturing_service(tmp_path / "decision-support-priority.db", root=ROOT)

    seen_sequences: set[tuple[str, ...]] = set()
    for case in EVAL_CASES:
        packet = service.agent_review_packet(case["asset_id"])
        result = run_read_only_tool_pipeline(packet)

        assert result["mutation_allowed"] is False
        assert result["closed_loop_mutation_attempted"] is False
        assert result["called_tools"][: len(case["expected_first_tools"])] == case[
            "expected_first_tools"
        ], case["case_id"]
        assert (packet.get("review_priority") or {}).get("level") == case["priority"]
        seen_sequences.add(tuple(result["called_tools"]))

    assert len(seen_sequences) >= 3


def test_ai_decision_support_does_not_turn_limitations_into_operational_claims(
    tmp_path: Path,
) -> None:
    service = build_manufacturing_service(tmp_path / "decision-support-limits.db", root=ROOT)
    forbidden_fragments = {
        "실제 생산 실적 기준",
        "다운타임이 절감",
        "생산 손실이 예상",
        "자동 승인",
        "작업요청 생성",
        "정비 승인",
        "정비 완료",
    }

    for case in EVAL_CASES:
        packet = service.agent_review_packet(case["asset_id"])
        summary = compose_deterministic_agent_review_summary(packet)
        rendered = str(summary)

        if case["requires_loss_context"]:
            assert any(
                "실제 MES 실적이 연결되기 전까지" in item["note"]
                for item in summary.get("data_footnotes") or []
            )
        for fragment in forbidden_fragments:
            if fragment in packet["review_draft"]["boundary_note"]:
                continue
            assert fragment not in rendered, f"{case['case_id']} leaked {fragment}"

        if packet["risk_summary"]["status_grade"] is None:
            assert summary["confidence_label"] == "data_quality_hold"
            assert summary["inspection_focus"] == []
            assert packet["review_priority"] is None
            assert "확정하지 않습니다" in summary["summary"]


def _role_quote(summary: dict[str, Any], role: str) -> str:
    return next(item["quote"] for item in summary["role_summaries"] if item["role"] == role)


def _risk_state_is_expressed(summary: dict[str, Any], *, packet: dict[str, Any]) -> bool:
    risk = packet["risk_summary"]
    if risk["status_grade"] is None:
        return (
            summary["confidence_label"] == "data_quality_hold"
            and "위험 등급과 예측 위험도를 확정하지 않습니다" in summary["summary"]
        )
    probability_text = f"{float(risk['failure_probability']) * 100:.1f}%"
    return risk["status_grade"] in summary["summary"] and probability_text in summary["summary"]


def _inspection_focus_matches_packet(
    summary: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> bool:
    packet_targets = packet.get("inspection_targets") or []
    summary_targets = summary.get("inspection_focus") or []
    return len(packet_targets) == len(summary_targets) and all(
        target["component_id"] == summary_targets[index]["component_id"]
        and target["basis_refs"] == summary_targets[index]["basis_refs"]
        for index, target in enumerate(packet_targets)
    )


def _evidence_gaps_are_preserved(summary: dict[str, Any], *, packet: dict[str, Any]) -> bool:
    packet_gaps = {
        (gap["field"], gap["reason"], gap["owner_domain"])
        for gap in packet.get("evidence_gaps") or []
    }
    summary_gaps = {
        (gap["field"], gap["reason"], gap["owner_domain"])
        for gap in summary.get("evidence_gaps") or []
    }
    return packet_gaps == summary_gaps


def _hold_or_limitations_are_expressed(
    summary: dict[str, Any],
    *,
    packet: dict[str, Any],
) -> bool:
    if packet["risk_summary"]["status_grade"] is None:
        return "확정 판단보다 데이터 보강" in summary["summary"]
    operation_limits = packet.get("operation_context_summary", {}).get("limitations") or []
    footnotes = " ".join(item["note"] for item in summary.get("data_footnotes") or [])
    return not operation_limits or "실제 MES" in footnotes

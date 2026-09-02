from datetime import datetime, timezone
from types import SimpleNamespace

from app.operations.contracts import AgentQueryRequest
from app.operations.router import (
    _answer_from_packet,
    _merge_runtime_detail_supplemental,
    _runtime_demo_operation_context,
    _runtime_sop_context,
    _summary_text,
)


def _runtime_result():
    return SimpleNamespace(
        asset_id="CNC-S01-L04-03",
        asset_type="cnc",
        observed_at=datetime(2026, 9, 2, 7, 50, tzinfo=timezone.utc),
        status_grade="warning",
        predicted_failure_type="failure_risk",
        top_factors=[
            SimpleNamespace(feature="rotation_raw"),
            SimpleNamespace(feature="vibration_raw"),
        ],
    )


def test_runtime_demo_operation_context_is_explicit_and_actionable():
    result = _runtime_result()
    context = _runtime_demo_operation_context(result, "RESULT#CNC-S01-L04-03#1")

    assert context["source_type"] == "synthetic_capacity_model"
    assert context["production_plan"]["planned_units"] == 16200
    assert context["capacity_model"]["daily_capacity_units"] == 16200
    assert context["event_impact"]["line"] == "S01-L04"
    assert context["event_impact"]["estimated_lost_units"] > 0
    assert context["event_impact"]["basis"]["estimated_downtime_minutes"] == 120
    assert any("MES/ERP/APS" in item for item in context["limitations"])


def test_runtime_sop_retrieval_returns_grounded_source_for_cnc_result():
    result = _runtime_result()
    context = _runtime_demo_operation_context(result, "RESULT#CNC-S01-L04-03#1")

    retrieval, guidance = _runtime_sop_context(result, context)

    assert retrieval["provider"] == "local_sop_metadata_retriever"
    assert retrieval["top_k"] == 3
    assert retrieval["returned_count"] >= 1
    assert guidance
    assert guidance[0]["sop_id"] == "SOP-DEMO-CNC-ROTATING-ASSEMBLY-001"
    assert guidance[0]["source_ref"].endswith("#SOP-DEMO-CNC-ROTATING-ASSEMBLY-001")
    assert "factor_keys" in guidance[0]["matched_fields"]


def test_agent_query_audience_selects_distinct_role_summary():
    summary = {
        "summary": "경영진용 전체 운영 요약",
        "role_summaries": [
            {"role": "field_operator", "quote": "엔지니어 기술 근거 요약"},
            {"role": "process_manager", "quote": "관리자 Decision Packet 요약"},
        ],
    }

    assert _summary_text(summary, "engineering") == "엔지니어 기술 근거 요약"
    assert _summary_text(summary, "operations") == "관리자 Decision Packet 요약"
    assert _summary_text(summary, "executive") == "경영진용 전체 운영 요약"


def test_executive_agent_answer_adds_business_impact_context():
    packet = {
        "asset_id": "CNC-S01-L04-03",
        "asset_label": "CNC-S01-L04-03",
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.7},
        "review_priority": {"reasons": ["warning"]},
        "operation_context_summary": {
            "production_impact": "medium",
            "estimated_downtime_minutes": 120,
            "estimated_lost_units": 25,
        },
    }
    summary = {
        "summary": "현재 운영 판단이 필요한 주요 이슈입니다.",
        "role_summaries": [],
    }
    evidence = [{"content": "SOP 점검 근거"}]

    answer = _answer_from_packet("경영 보고 요약", packet, evidence, summary, "executive")

    assert "생산 영향 medium" in answer
    assert "예상 정지 120분" in answer
    assert "계획 영향 약 25개" in answer
    assert "SOP 점검 근거" in answer


def test_agent_query_contract_accepts_role_audience():
    request = AgentQueryRequest(
        project_id="manufacturing-demo-project",
        workspace_id="manufacturing-demo",
        question="이 이슈를 경영진 관점에서 요약해줘",
        audience="executive",
        event_id="RESULT#CNC-S01-L04-03#1",
    )

    assert request.audience == "executive"
    assert request.event_id == "RESULT#CNC-S01-L04-03#1"


def test_canonical_live_detail_keeps_evidence_and_adds_presentation_context():
    canonical = {
        "snapshot_basis": {"artifact_id": "RESULT#1"},
        "features": [{"feature": "rotation_raw"}],
        "inspection_targets": [],
        "review_priority": None,
        "evidence": {
            "artifact_id": "RESULT#1",
            "gaps": [
                {"field": "operation_context.production_impact", "reason": "missing"},
                {"field": "review_priority", "reason": "missing"},
                {"field": "equipment_history", "reason": "missing"},
            ],
        },
    }
    supplemental = {
        "operation_context": {"source_type": "synthetic_capacity_model"},
        "inspection_targets": [{"target_id": "inspection-target:1"}],
        "review_priority": {"level": "high"},
    }

    merged = _merge_runtime_detail_supplemental(canonical, supplemental)

    assert merged["snapshot_basis"] == canonical["snapshot_basis"]
    assert merged["features"] == canonical["features"]
    assert merged["operation_context"]["source_type"] == "synthetic_capacity_model"
    assert merged["inspection_targets"] == supplemental["inspection_targets"]
    assert merged["review_priority"] == supplemental["review_priority"]
    assert merged["evidence"]["gaps"] == [
        {"field": "equipment_history", "reason": "missing"}
    ]

from __future__ import annotations

from scripts.evaluate_agent_briefing_usefulness import score_summary


def _packet() -> dict:
    return {
        "asset_label": "4구역 · 4셀 · CNC 가공기 1",
        "risk_summary": {"status_grade": "warning", "failure_probability": 0.824583},
        "review_priority": {"level": "high"},
        "model_expression_context": {
            "top_factors": [
                {"label": "공구 마모"},
                {"label": "과부하 지표"},
            ]
        },
        "inspection_targets": [
            {"component_label": "공구/마모 계통", "location_label": "공구 매거진"},
            {"component_label": "동력 전달 계통", "location_label": "커플링"},
        ],
        "evidence_gaps": [{"field": "maintenance_context.open_work_order_exists"}],
    }


def test_usefulness_score_passes_grounded_actionable_briefing():
    summary = {
        "title": "CNC 가공기 점검 판단",
        "summary": (
            "warning 상태이고 고장 위험은 82.5%입니다. 공구 마모와 과부하 지표를 근거로 "
            "공구/마모 계통과 동력 전달 계통을 먼저 점검해야 합니다. 점검 결과 편심이 확인되어 "
            "작업요청은 승인 상태이지만, 착수 기록과 재고, 작업 가능 시간은 확정되지 않았습니다."
        ),
        "role_summaries": [
            {"role": "process_engineer", "quote": "커플링과 공구 매거진 확인 후 조치 범위를 검토합니다."},
            {"role": "maintenance_technician", "quote": "승인된 작업요청의 착수 조건과 재고를 확인합니다."},
            {"role": "process_manager", "quote": "생산 영향은 확정되지 않은 항목을 제외하고 판단합니다."},
        ],
    }

    result = score_summary(summary, packet=_packet(), expected_facts={"inspection": "maintenance_recommended", "work_order": "approved"})

    assert result["pass"] is True
    assert result["score"] == result["total"]


def test_usefulness_score_rejects_unsafe_or_opaque_briefing():
    summary = {
        "title": "자동 처리 완료",
        "summary": (
            "maintenance_recommended 상태이며 데모 스냅샷 기준입니다. 작업요청 승인되었습니다. "
            "재고 확보 완료이고 정비 완료 후 정상 운전 가능합니다."
        ),
        "role_summaries": [
            {"role": "process_engineer", "quote": "자동 승인 실행."},
            {"role": "maintenance_technician", "quote": "수리 완료."},
            {"role": "process_manager", "quote": "정상 가동 가능."},
        ],
    }

    result = score_summary(summary, packet=_packet(), expected_facts={"inspection": "maintenance_recommended", "work_order": "requested"})

    assert result["pass"] is False
    assert result["checks"]["status_accuracy"] is False
    assert result["checks"]["risky_claims_avoided"] is False
    assert result["checks"]["reader_language"] is False

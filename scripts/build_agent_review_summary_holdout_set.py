from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets"
TARGET_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets_holdout"


HOLDOUT_CASES: list[dict[str, Any]] = [
    {
        "id": "HGS-001",
        "base": "GS-002",
        "asset_id": "CNC-H01-L02-01",
        "asset_label": "Holdout 1구역 · 2셀 · CNC 가공기 1",
        "status": "warning",
        "probability": 0.731,
        "impact": "high",
        "downtime": 360,
        "lost_units": 124,
        "priority": "immediate",
        "must": ["warning", "73.1%", "공구/마모 계통", "동력 전달 계통", "생산 영향이 높은", "124건"],
        "manager": ["생산 영향이 높은", "124건", "점검 승인"],
        "forbid": ["critical", "25건", "승인 완료", "작업 지시"],
    },
    {
        "id": "HGS-002",
        "base": "GS-003",
        "asset_id": "CNC-H02-L03-02",
        "asset_label": "Holdout 2구역 · 3셀 · CNC 가공기 2",
        "status": "attention",
        "probability": 0.417,
        "impact": "low",
        "downtime": 35,
        "lost_units": 7,
        "priority": "medium",
        "must": ["attention", "41.7%", "열 방산 계통", "동력 전달 계통", "생산 영향이 낮은", "7건"],
        "manager": ["생산 영향이 낮은", "7건", "점검 승인"],
        "forbid": ["critical", "32건", "수리 완료", "작업 지시"],
    },
    {
        "id": "HGS-003",
        "base": "GS-004",
        "asset_id": "CNC-H03-L04-03",
        "asset_label": "Holdout 3구역 · 4셀 · CNC 가공기 3",
        "status": "critical",
        "probability": 0.934,
        "impact": "high",
        "downtime": 410,
        "lost_units": 88,
        "priority": "immediate",
        "must": ["critical", "93.4%", "동력 전달 계통", "생산 영향이 높은", "88건", "점검 요청"],
        "manager": ["생산 영향이 높은", "88건", "점검 승인"],
        "forbid": ["수리 완료", "승인 완료", "자동 실행", "51건"],
    },
    {
        "id": "HGS-004",
        "base": "GS-005",
        "asset_id": "CNC-H04-L01-01",
        "asset_label": "Holdout 4구역 · 1셀 · CNC 가공기 1",
        "status": "normal",
        "probability": 0.094,
        "impact": "none",
        "downtime": 20,
        "lost_units": 0,
        "priority": "low",
        "must": ["normal", "9.4%", "공구/마모 계통", "동력 전달 계통", "생산 영향이 없음", "0건"],
        "manager": ["생산 영향이 없음", "0건", "점검 승인"],
        "forbid": ["warning", "critical", "18건", "작업 지시"],
    },
    {
        "id": "HGS-005",
        "base": "GS-006",
        "asset_id": "CNC-H05-L05-02",
        "asset_label": "Holdout 5구역 · 5셀 · CNC 가공기 2",
        "status": "warning",
        "probability": 0.588,
        "impact": "medium",
        "downtime": 75,
        "lost_units": 16,
        "priority": "high",
        "must": ["warning", "58.8%", "공구/마모 계통", "동력 전달 계통", "생산 영향이 중간", "16건"],
        "manager": ["생산 영향이 중간", "16건", "점검 승인"],
        "forbid": ["critical", "13건", "수리 완료", "승인 완료"],
    },
    {
        "id": "HGS-006",
        "base": "GS-001",
        "asset_id": "CNC-H06-L02-03",
        "asset_label": "Holdout 6구역 · 2셀 · CNC 가공기 3",
        "status": "warning",
        "probability": 0.642,
        "impact": "medium",
        "downtime": 90,
        "lost_units": 19,
        "priority": "high",
        "must": ["warning", "64.2%", "동력 전달 계통", "열 방산 계통", "생산 영향이 중간", "19건"],
        "manager": ["생산 영향이 중간", "19건", "점검 승인"],
        "forbid": ["normal", "0건", "수리 완료", "작업 지시"],
    },
    {
        "id": "HGS-007",
        "base": "GS-007",
        "asset_id": "CNC-H07-L05-01",
        "asset_label": "Holdout 7구역 · 5셀 · CNC 가공기 1",
        "status": None,
        "probability": None,
        "impact": "low",
        "downtime": 55,
        "lost_units": None,
        "priority": None,
        "must": ["데이터 품질 보류", "위험 등급", "예측 위험도", "확정하지 않습니다", "근거 공백"],
        "manager": ["추정 물량 손실", "유사 이력은 아직", "점검 승인"],
        "forbid": ["normal", "warning", "critical", "수리 완료", "작업 지시", "고장 확정"],
    },
    {
        "id": "HGS-008",
        "base": "GS-008",
        "asset_id": "CNC-H08-L04-02",
        "asset_label": "Holdout 8구역 · 4셀 · CNC 가공기 2",
        "status": "warning",
        "probability": 0.869,
        "impact": "medium",
        "downtime": 210,
        "lost_units": 46,
        "priority": "high",
        "must": ["warning", "86.9%", "공구/마모 계통", "동력 전달 계통", "생산 영향이 중간", "46건"],
        "manager": ["생산 영향이 중간", "46건", "점검 승인"],
        "forbid": ["critical", "25건", "수리 완료", "승인 완료"],
    },
]


def main() -> None:
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    manifest_cases = []
    gold_cases = {}
    for case in HOLDOUT_CASES:
        packet = _build_packet(case)
        path = TARGET_ROOT / f"{case['id']}.json"
        path.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_cases.append(
            {
                "scenario_id": case["id"],
                "asset_id": case["asset_id"],
                "fixture_path": f"tests/fixtures/agent_review_packets_holdout/{case['id']}.json",
                "description": "Holdout paraphrase case with changed event id, asset, impact, and lost-unit values.",
                "covers": ["process_manager_holdout", "paraphrased_fixture_surface", "closed_loop_boundary_readonly"],
            }
        )
        gold_cases[case["id"]] = {
            "must_mention": case["must"],
            "visible_limitations": ["데이터 품질 보류", "근거 공백"] if case["id"] == "HGS-007" else [],
            "role_points": {
                "field_operator": _field_operator_points(case["base"]),
                "process_manager": case["manager"],
            },
            "must_not_claim": case["forbid"],
        }

    manifest = {
        "eval_set_id": "agent-review-packet-holdout-v1",
        "purpose": "process_manager_overfit_check",
        "description": "Eight holdout/paraphrase fixtures for PM production-impact, lost-unit, approval, and data-quality boundary checks.",
        "owner_domain": "product_evidence",
        "packet_schema_version": "agent-review-packet-v1.0",
        "summary_schema_version": "agent-review-summary-v1.0",
        "cases": manifest_cases,
    }
    answers = {
        "gold_answer_set_id": "agent-review-summary-holdout-gold-answers-v1",
        "purpose": "Holdout reference answers for process-manager overfit checks.",
        "limits": [
            "Generated from existing packet shapes with changed identifiers, values, and paraphrased surfaces.",
            "This remains fixture-based evidence, not operational production proof.",
        ],
        "global_must_not_claim": ["수리 완료", "승인 완료", "작업 지시", "자동 실행", "교체 완료", "고장 확정"],
        "cases": gold_cases,
    }
    (TARGET_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (TARGET_ROOT / "gold_answers.json").write_text(
        json.dumps(answers, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_packet(case: dict[str, Any]) -> dict[str, Any]:
    packet = copy.deepcopy(
        json.loads((SOURCE_ROOT / f"{case['base']}.json").read_text(encoding="utf-8"))
    )
    packet["asset_id"] = case["asset_id"]
    packet["asset_label"] = case["asset_label"]
    packet["snapshot_basis"]["event_id"] = f"EVT-{case['id']}"
    packet["snapshot_basis"]["asset_id"] = case["asset_id"]
    packet["risk_summary"]["status_grade"] = case["status"]
    packet["risk_summary"]["failure_probability"] = case["probability"]
    if packet.get("model_expression_context"):
        packet["model_expression_context"]["failure_probability"] = case["probability"]
    packet["operation_context_summary"]["production_impact"] = case["impact"]
    packet["operation_context_summary"]["estimated_downtime_minutes"] = case["downtime"]
    packet["operation_context_summary"]["estimated_lost_units"] = case["lost_units"]
    packet["review_priority"] = _priority(case)
    packet["review_draft"]["title"] = f"{case['asset_label']} 담당자 검토 초안"
    packet["review_draft"]["summary"] = _summary(case, packet)
    packet["review_draft"]["history_summary"] = _history(case)
    return packet


def _priority(case: dict[str, Any]) -> dict[str, Any] | None:
    if case["priority"] is None:
        return None
    return {
        "level": case["priority"],
        "reasons": [
            f"risk.status_grade={case['status']}",
            f"operation_context.production_impact={case['impact']}",
            "holdout.paraphrase_surface=true",
        ],
        "source_fields": [
            "risk.status_grade",
            "operation_context.production_impact",
        ],
    }


def _summary(case: dict[str, Any], packet: dict[str, Any]) -> str:
    if case["status"] is None:
        return (
            f"{case['asset_id']}는 계측 근거가 부족해 데이터 품질 보류 상태입니다. "
            "위험 등급과 예측 위험도를 확정하지 않습니다. 근거 공백을 먼저 보강해야 합니다."
        )
    components = ", ".join(
        item["component_label"]
        for item in packet.get("inspection_targets") or []
        if item.get("component_label")
    )
    return (
        f"{case['asset_id']}는 현재 {case['status']} 상태이며 예측 위험도는 "
        f"{case['probability'] * 100:.1f}%입니다. {components} 중심으로 "
        "교대조 기록, 현장 위치, 관측 근거를 다시 대조해야 합니다."
    )


def _history(case: dict[str, Any]) -> list[str]:
    if case["status"] is None:
        return [
            "최근 정비 이력: 보류 케이스용 샘플 이력 · 2026-07-26T00:00:00+09:00 · 6일 전",
            "열린 작업요청: Closed-loop 이력 연결 전이라 확정하지 않음",
            "최근 30일 유사 이벤트: 전용 이력 계약 미연결",
        ]
    return [
        "최근 정비 이력: holdout 샘플 이력 · 2026-07-19T00:00:00+09:00 · 13일 전",
        "열린 작업요청: Closed-loop 이력 연결 전이라 확정하지 않음",
        "최근 30일 유사 이벤트: holdout paraphrase sample · 1건",
    ]


def _field_operator_points(base: str) -> list[str]:
    source_answers = json.loads((SOURCE_ROOT / "gold_answers.json").read_text(encoding="utf-8"))
    return source_answers["cases"][base]["role_points"]["field_operator"]


if __name__ == "__main__":
    main()

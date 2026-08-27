"""Read-only agent review packet composition for MVP asset workflows."""

from __future__ import annotations

from typing import Any


FORBIDDEN_AGENT_ACTIONS = [
    "create_work_order",
    "approve_work_order",
    "start_maintenance_action",
    "complete_maintenance_action",
    "create_maintenance_event",
    "request_replay",
    "auto_approve",
]


def compose_agent_review_packet(
    *,
    project_id: str,
    view_model: dict[str, Any],
    sop_retrieval: dict[str, Any],
) -> dict[str, Any]:
    retrieval_results = sop_retrieval.get("results") or []
    procedures_by_id = {
        str((item.get("procedure") or {}).get("sop_id") or ""): item
        for item in retrieval_results
    }
    sop_guidance = []
    source_refs = []
    human_questions = []
    limitations = [
        "Agent Review Packet is read-only and does not mutate Recommendation, WorkOrder, MaintenanceAction, MaintenanceEvent, or Replay state.",
        "SOP grounding supports inspection and replacement timing review drafts; it is not Product Evidence or a repair instruction.",
    ]

    evidence_ref = str((view_model.get("evidence") or {}).get("evidence_payload_reference") or "")
    if evidence_ref:
        source_refs.append(evidence_ref)

    for target in view_model.get("inspection_targets") or []:
        guidance = target.get("inspection_guidance") or {}
        sop_id = str(guidance.get("sop_id") or "")
        if not guidance or not sop_id:
            continue
        retrieval_item = procedures_by_id.get(sop_id) or {}
        procedure = retrieval_item.get("procedure") or {}
        replacement = guidance.get("replacement_review_guidance") or {}
        questions = [str(item) for item in replacement.get("human_review_questions") or []]
        human_questions.extend(questions)
        if guidance.get("source_ref"):
            source_refs.append(str(guidance["source_ref"]))
        if target.get("source_ref"):
            source_refs.append(str(target["source_ref"]))
        if guidance.get("disclaimer"):
            limitations.append(str(guidance["disclaimer"]))
        sop_guidance.append(
            {
                "target_id": str(target.get("target_id") or ""),
                "component_id": str(target.get("component_id") or ""),
                "component_label": str(target.get("component_label") or ""),
                "sop_id": sop_id,
                "source_type": str(guidance.get("source_type") or ""),
                "maturity": str(procedure.get("maturity") or "fixture"),
                "checklist_draft": [str(item) for item in guidance.get("checklist_draft") or []],
                "replacement_review_guidance": replacement,
                "sensor_judgment": procedure.get("sensor_judgment"),
                "retrieval_score": retrieval_item.get("retrieval_score", 0),
                "matched_fields": [
                    str(item) for item in retrieval_item.get("matched_fields") or []
                ],
                "disclaimer": str(guidance.get("disclaimer") or ""),
                "source_ref": str(guidance.get("source_ref") or ""),
            }
        )

    closed_loop = view_model.get("closed_loop") or {}
    available_actions = closed_loop.get("available_actions") or []
    review_draft = _compose_review_draft(
        asset=view_model.get("asset") or {},
        risk=view_model.get("risk") or {},
        review_priority=view_model.get("review_priority"),
        sop_guidance=sop_guidance,
        human_questions=list(dict.fromkeys(human_questions)),
        evidence_gaps=(view_model.get("evidence") or {}).get("gaps") or [],
    )
    return {
        "schema_version": "agent-review-packet-v1.0",
        "project_id": project_id,
        "asset_id": str((view_model.get("asset") or {}).get("asset_id") or ""),
        "generated_at": str((view_model.get("asset") or {}).get("observed_at") or ""),
        "risk_summary": {
            "status_grade": (view_model.get("risk") or {}).get("status_grade"),
            "failure_probability": (view_model.get("risk") or {}).get("current"),
            "prediction_horizon_hours": (view_model.get("risk") or {}).get(
                "prediction_horizon_hours"
            ),
        },
        "review_priority": view_model.get("review_priority"),
        "review_draft": review_draft,
        "sop_retrieval": {
            "provider": str(sop_retrieval.get("provider") or ""),
            "query": sop_retrieval.get("query") or {},
            "top_k": int(sop_retrieval.get("top_k") or 0),
            "returned_count": int(sop_retrieval.get("returned_count") or 0),
            "mutation_allowed": False,
        },
        "sop_guidance": sop_guidance,
        "human_questions": list(dict.fromkeys(human_questions)),
        "evidence_gaps": (view_model.get("evidence") or {}).get("gaps") or [],
        "source_refs": list(dict.fromkeys(source_refs)),
        "closed_loop_boundary": {
            "mutation_allowed": False,
            "available_action_ids": [
                str(item.get("action_id")) for item in available_actions if item.get("action_id")
            ],
            "forbidden_actions": FORBIDDEN_AGENT_ACTIONS,
            "note": "This packet may reference available actions for context, but it cannot execute or approve them.",
        },
        "limitations": list(dict.fromkeys(limitations)),
    }


def _compose_review_draft(
    *,
    asset: dict[str, Any],
    risk: dict[str, Any],
    review_priority: dict[str, Any] | None,
    sop_guidance: list[dict[str, Any]],
    human_questions: list[str],
    evidence_gaps: list[dict[str, Any]],
) -> dict[str, Any]:
    asset_id = str(asset.get("asset_id") or "")
    asset_name = str(asset.get("display_name") or asset_id)
    status_grade = str(risk.get("status_grade") or "unknown")
    probability = risk.get("current")
    probability_label = f"{float(probability) * 100:.1f}%" if isinstance(probability, (int, float)) else "미제공"
    primary_guidance = sop_guidance[0] if sop_guidance else {}
    component_label = str(primary_guidance.get("component_label") or "의심 부품")
    checklist = [str(item) for item in primary_guidance.get("checklist_draft") or []][:4]
    if evidence_gaps:
        checklist.append("근거 공백 항목을 먼저 확인하고 확정 판단에서 제외합니다.")
    questions = human_questions[:4]
    if not questions:
        questions = ["현장 담당자가 점검 가능 시간, 부품 상태, 안전 조건을 확인했습니까?"]
    priority_level = str((review_priority or {}).get("level") or "medium")
    recommended_next_step = (
        "담당자가 SOP 기준 점검 질문을 확인하고, 필요한 경우 관리자 승인 절차로 이관합니다."
    )
    return {
        "title": f"{asset_name} 담당자 검토 초안",
        "summary": (
            f"{asset_id}는 현재 {status_grade} 상태이며 예측 위험도는 {probability_label}입니다. "
            f"{component_label} 중심으로 SOP 근거와 관측값을 대조해야 합니다."
        ),
        "priority_label": priority_level,
        "recommended_next_step": recommended_next_step,
        "checklist": checklist,
        "questions": questions,
        "evidence_gap_count": len(evidence_gaps),
        "boundary_note": "이 초안은 담당자 검토를 돕기 위한 read-only 문서이며 작업요청 생성, 정비 승인, 자동 승인을 수행하지 않습니다.",
    }

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
    procedure_groundings: list[dict[str, Any]],
) -> dict[str, Any]:
    procedures_by_id = {str(item.get("sop_id") or ""): item for item in procedure_groundings}
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
        procedure = procedures_by_id.get(sop_id) or {}
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
                "disclaimer": str(guidance.get("disclaimer") or ""),
                "source_ref": str(guidance.get("source_ref") or ""),
            }
        )

    closed_loop = view_model.get("closed_loop") or {}
    available_actions = closed_loop.get("available_actions") or []
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

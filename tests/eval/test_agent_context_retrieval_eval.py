from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.dependencies import build_manufacturing_service


ROOT = Path(__file__).resolve().parents[2]
QUESTION_PATH = ROOT / "tests" / "eval" / "agent_context_questions.jsonl"


def _load_questions() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in QUESTION_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_agent_context_question_set_controls_eval_variables() -> None:
    questions = _load_questions()

    assert len(questions) >= 3
    assert len({question["case_id"] for question in questions}) == len(questions)
    for question in questions:
        assert question["question"]
        assert set(question["expected"]) == {
            "component_id",
            "factor_refs",
            "location_label",
            "sop_ids",
            "boundary",
        }


def test_kg_level0_packet_and_ontology_context_answer_same_facets(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-context-eval.db", root=ROOT)

    for question in _load_questions():
        packet = service.agent_review_packet(question["asset_id"])
        expected = question["expected"]

        packet_answer = _answer_from_packet(packet)
        ontology_answer = _answer_from_ontology_context(packet)

        assert _matches_expected(packet_answer, expected), question["case_id"]
        assert _matches_expected(ontology_answer, expected), question["case_id"]
        assert packet_answer["boundary"] == ontology_answer["boundary"]


def test_kg_level0_trace_remains_read_only(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-context-readonly.db", root=ROOT)

    for question in _load_questions():
        packet = service.agent_review_packet(question["asset_id"])
        assert packet["ontology_context"]["mutation_allowed"] is False
        assert packet["closed_loop_boundary"]["mutation_allowed"] is False
        rendered = json.dumps(packet["ontology_context"], ensure_ascii=False)
        assert "approve_work_order" not in rendered
        assert "auto_approve" not in rendered


def _answer_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    target = (packet.get("inspection_targets") or [{}])[0]
    guidance = (packet.get("sop_guidance") or [{}])[0]
    return {
        "component_id": target.get("component_id"),
        "factor_refs": [
            ref for ref in target.get("basis_refs") or [] if str(ref).startswith("factor.")
        ],
        "location_label": target.get("location_label"),
        "sop_ids": [guidance["sop_id"]] if guidance.get("sop_id") else [],
        "boundary": _boundary(packet),
    }


def _answer_from_ontology_context(packet: dict[str, Any]) -> dict[str, Any]:
    traversal = (packet.get("ontology_context") or {}).get("traversals") or []
    first = traversal[0] if traversal else {}
    return {
        "component_id": first.get("component_id"),
        "factor_refs": first.get("factor_refs") or [],
        "location_label": first.get("location_label"),
        "sop_ids": first.get("sop_ids") or [],
        "boundary": _boundary(packet),
    }


def _matches_expected(answer: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        answer["component_id"] == expected["component_id"]
        and answer["factor_refs"] == expected["factor_refs"]
        and answer["location_label"] == expected["location_label"]
        and answer["sop_ids"] == expected["sop_ids"]
        and answer["boundary"] == expected["boundary"]
    )


def _boundary(packet: dict[str, Any]) -> str:
    if packet["review_draft"]["priority_label"] == "미확정":
        return "data_quality_hold_no_invention"
    if packet["closed_loop_boundary"]["mutation_allowed"] is False:
        return "no_closed_loop_mutation"
    return "unsafe_mutation_boundary"

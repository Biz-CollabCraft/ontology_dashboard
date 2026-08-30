from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.dependencies import build_manufacturing_service
from app.mvp.agent_review_summary_workflow import AgentReviewSummaryWorkflow


ROOT = Path(__file__).resolve().parents[2]
QUESTION_PATH = ROOT / "tests" / "eval" / "agent_context_questions.jsonl"
RAG_GATE_PATH = ROOT / "tests" / "eval" / "rag_decision_gate.json"
LANGGRAPH_GATE_PATH = ROOT / "tests" / "eval" / "langgraph_decision_gate.json"


def _load_questions() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in QUESTION_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_rag_gate() -> dict[str, Any]:
    return json.loads(RAG_GATE_PATH.read_text(encoding="utf-8"))


def _load_langgraph_gate() -> dict[str, Any]:
    return json.loads(LANGGRAPH_GATE_PATH.read_text(encoding="utf-8"))


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
            "spare_part_ids",
            "similar_event_ids",
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


def test_rag_decision_gate_defers_runtime_rag_for_structured_sop(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-context-rag-gate.db", root=ROOT)
    gate = _load_rag_gate()

    assert gate["current_decision"] == "defer_runtime_rag"
    assert gate["current_sop_source"] == {
        "format": "structured_fixture_metadata",
        "retriever": "local_sop_metadata_retriever",
        "paragraph_level_citations_required": False,
        "multiple_overlapping_versions": False,
        "unstructured_documents_present": False,
    }
    assert "llamaindex_runtime_retrieval" in gate["deferred_runtime_components"]

    for question in _load_questions():
        packet = service.agent_review_packet(question["asset_id"])
        assert packet["sop_retrieval"]["provider"] == "local_sop_metadata_retriever"
        assert "vector" not in packet["sop_retrieval"]["provider"]
        assert packet["sop_retrieval"]["mutation_allowed"] is False

    assert set(gate["adopt_rag_when_any"]) == {
        "site_sops_arrive_as_pdf_or_free_form_documents",
        "multiple_sop_versions_overlap_for_same_component_or_failure_mode",
        "paragraph_level_citations_are_required_for_user_facing_guidance",
        "structured_metadata_cannot_answer_agent_context_eval_questions",
    }


def test_langgraph_decision_gate_keeps_simple_workflow_default(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-context-langgraph-gate.db", root=ROOT)
    gate = _load_langgraph_gate()
    workflow_result = AgentReviewSummaryWorkflow(service).run(limit=1, max_attempts=1)

    assert gate["current_decision"] == "keep_simple_workflow_default"
    assert gate["current_engine"] == "simple"
    assert workflow_result["workflow"]["engine"] == gate["current_engine"]
    assert gate["first_experiment_shape"]["public_boundary"] == "AgentReviewSummaryWorkflow"
    assert gate["first_experiment_shape"]["default"] == "simple"
    assert gate["first_experiment_shape"]["experimental"] == "langgraph"
    assert "AI_WORKFLOW_ENGINE" == gate["first_experiment_shape"]["flag"]


def test_langgraph_gate_keeps_closed_loop_state_out_of_graph_contract() -> None:
    gate = _load_langgraph_gate()

    assert len(gate["minimum_trigger_conditions"]) >= 3
    assert "domain_context" in gate["first_experiment_shape"]["allowed_state"]
    assert "agent_review_packet" in gate["first_experiment_shape"]["allowed_state"]
    assert "executable_closed_loop_command" in gate["first_experiment_shape"]["forbidden_state"]
    assert "mutable_work_order_state" in gate["first_experiment_shape"]["forbidden_state"]
    assert "approval_action_tool" in gate["first_experiment_shape"]["forbidden_state"]


def _answer_from_packet(packet: dict[str, Any]) -> dict[str, Any]:
    target = (packet.get("inspection_targets") or [{}])[0]
    guidance = (packet.get("sop_guidance") or [{}])[0]
    traversal = _matching_ontology_traversal(packet, target.get("component_id"))
    return {
        "component_id": target.get("component_id"),
        "factor_refs": [
            ref for ref in target.get("basis_refs") or [] if str(ref).startswith("factor.")
        ],
        "location_label": target.get("location_label"),
        "sop_ids": [guidance["sop_id"]] if guidance.get("sop_id") else [],
        "spare_part_ids": [
            part["part_id"]
            for part in traversal.get("spare_parts") or []
            if part.get("part_id")
        ],
        "similar_event_ids": [
            event["similar_event_id"]
            for event in traversal.get("similar_events") or []
            if event.get("similar_event_id")
        ],
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
        "spare_part_ids": [
            part["part_id"]
            for part in first.get("spare_parts") or []
            if part.get("part_id")
        ],
        "similar_event_ids": [
            event["similar_event_id"]
            for event in first.get("similar_events") or []
            if event.get("similar_event_id")
        ],
        "boundary": _boundary(packet),
    }


def _matches_expected(answer: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        answer["component_id"] == expected["component_id"]
        and answer["factor_refs"] == expected["factor_refs"]
        and answer["location_label"] == expected["location_label"]
        and answer["sop_ids"] == expected["sop_ids"]
        and answer["spare_part_ids"] == expected["spare_part_ids"]
        and answer["similar_event_ids"] == expected["similar_event_ids"]
        and answer["boundary"] == expected["boundary"]
    )


def _matching_ontology_traversal(
    packet: dict[str, Any],
    component_id: Any,
) -> dict[str, Any]:
    for traversal in (packet.get("ontology_context") or {}).get("traversals") or []:
        if traversal.get("component_id") == component_id:
            return traversal
    return {}


def _boundary(packet: dict[str, Any]) -> str:
    if packet["review_draft"]["priority_label"] == "미확정":
        return "data_quality_hold_no_invention"
    if packet["closed_loop_boundary"]["mutation_allowed"] is False:
        return "no_closed_loop_mutation"
    return "unsafe_mutation_boundary"

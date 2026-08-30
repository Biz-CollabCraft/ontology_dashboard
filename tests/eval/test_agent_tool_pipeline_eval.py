from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.dependencies import build_manufacturing_service
from app.mvp.agent_context_tool_pipeline import (
    FORBIDDEN_TOOL_NAMES,
    run_langgraph_tool_pipeline,
    run_read_only_tool_pipeline,
    validate_tool_trajectory,
)


ROOT = Path(__file__).resolve().parents[2]
TOOL_TRAJECTORY_GOLD_PATH = ROOT / "tests" / "eval" / "agent_tool_trajectory_gold.jsonl"


def _load_tool_trajectory_gold() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in TOOL_TRAJECTORY_GOLD_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_tool_trajectory_gold_set_has_distinct_situational_tool_plans() -> None:
    cases = _load_tool_trajectory_gold()

    assert len(cases) >= 3
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert len({tuple(case["expected_tools"]) for case in cases}) >= 2
    for case in cases:
        assert case["asset_id"]
        assert case["expected_tools"]
        assert case["rationale"]
        assert set(case["forbidden_tools"]).intersection(FORBIDDEN_TOOL_NAMES)


def test_read_only_tool_pipeline_matches_expected_trajectory(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-tool-pipeline.db", root=ROOT)

    for case in _load_tool_trajectory_gold():
        packet = service.agent_review_packet(case["asset_id"])
        result = run_read_only_tool_pipeline(packet)

        assert result["engine"] == "simple"
        assert result["mutation_allowed"] is False
        assert result["closed_loop_mutation_attempted"] is False
        assert result["called_tools"] == case["expected_tools"], case["case_id"]
        assert not set(result["called_tools"]).intersection(case["forbidden_tools"])
        assert result["validation_errors"] == []


def test_tool_pipeline_outputs_stay_inside_packet_source_scope(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-tool-scope.db", root=ROOT)
    packet = service.agent_review_packet("CNC-S04-L02-03")
    result = run_read_only_tool_pipeline(packet)
    source_scope = set(packet["source_refs"])

    assert result["source_ref_scope"] == sorted(source_scope)
    for call in result["tool_calls"]:
        assert call["read_only"] is True
        assert call["mutation_allowed"] is False
        assert set(call["source_refs"]).issubset(source_scope)
        assert call["input_snapshot_hash"] == result["packet_hash"]
        assert call["output_hash"]
    assert validate_tool_trajectory(result) == []


def test_tool_pipeline_data_quality_hold_avoids_context_fanout(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-tool-data-quality.db", root=ROOT)
    packet = service.agent_review_packet("CNC-S04-L05-01")
    result = run_read_only_tool_pipeline(packet)

    assert result["called_tools"] == ["data_quality.lookup"]
    assert "inspection_location.lookup" not in result["called_tools"]
    assert "sop_guidance.lookup" not in result["called_tools"]
    assert "spare_part.lookup" not in result["called_tools"]
    assert "similar_event.lookup" not in result["called_tools"]
    assert result["validation_errors"] == []


def test_experimental_langgraph_pipeline_preserves_tool_trajectory(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-tool-langgraph.db", root=ROOT)
    packet = service.agent_review_packet("CNC-S04-L02-03")

    simple = run_read_only_tool_pipeline(packet)
    langgraph = run_langgraph_tool_pipeline(packet)

    if langgraph["engine"] == "langgraph":
        assert langgraph["langgraph_available"] is True
        assert langgraph["pipeline_version"].endswith("langgraph-v0.1")
    else:
        assert langgraph["requested_engine"] == "langgraph"
        assert langgraph["langgraph_available"] is False
        assert langgraph["fallback_reason"]
    assert langgraph["called_tools"] == simple["called_tools"]
    assert langgraph["mutation_allowed"] is False
    assert langgraph["closed_loop_mutation_attempted"] is False
    assert langgraph["validation_errors"] == []

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.mvp.agent_review_summary import validate_agent_review_summary


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_SCHEMA = json.loads(
    (ROOT / "contracts" / "schemas" / "agent-review-summary.schema.json").read_text(
        encoding="utf-8"
    )
)
PACKET = json.loads(
    (ROOT / "tests" / "fixtures" / "agent_review_packets" / "GS-002.json").read_text(
        encoding="utf-8"
    )
)


def _valid_summary() -> dict:
    target = PACKET["inspection_targets"][0]
    return {
        "schema_version": "agent-review-summary-v1.0",
        "packet_schema_version": PACKET["schema_version"],
        "asset_id": PACKET["asset_id"],
        "generated_at": PACKET["generated_at"],
        "mode": "llm",
        "title": "AI 검토 요약",
        "summary": "공구/마모 계통 중심으로 SOP 근거, 위치 reference, 관측값을 대조해야 합니다.",
        "history_summary": PACKET["review_draft"]["history_summary"],
        "inspection_focus": [
            {
                "component_id": target["component_id"],
                "component_label": target["component_label"],
                "location_label": target["location_label"],
                "basis_refs": target["basis_refs"],
                "source_refs": [target["source_ref"]],
            }
        ],
        "evidence_gaps": PACKET["evidence_gaps"],
        "source_refs": [PACKET["source_refs"][0]],
        "boundary_note": "읽기 전용 검토 요약이며 정비 상태를 변경하지 않습니다.",
        "confidence_label": "grounded",
        "limitations": PACKET["limitations"],
    }


def test_agent_review_summary_schema_accepts_read_only_grounded_summary() -> None:
    summary = _valid_summary()

    assert list(Draft202012Validator(SUMMARY_SCHEMA).iter_errors(summary)) == []
    assert validate_agent_review_summary(summary, packet=PACKET) == []


def test_agent_review_summary_schema_rejects_mutation_field() -> None:
    summary = {**_valid_summary(), "create_work_order": {"action_id": "WO-1"}}

    errors = list(Draft202012Validator(SUMMARY_SCHEMA).iter_errors(summary))
    assert errors
    assert any("Additional properties" in error.message for error in errors)
    assert "forbidden_fields:action_id,create_work_order" in validate_agent_review_summary(
        summary,
        packet=PACKET,
    )


def test_agent_review_summary_validator_rejects_unknown_source_ref() -> None:
    summary = {**_valid_summary(), "source_refs": ["unknown://source"]}

    assert validate_agent_review_summary(summary, packet=PACKET) == [
        "source_refs_unknown:unknown://source"
    ]


def test_agent_review_summary_validator_rejects_nested_unknown_source_ref() -> None:
    summary = _valid_summary()
    summary["inspection_focus"] = [
        {**summary["inspection_focus"][0], "source_refs": ["unknown://nested"]}
    ]

    assert validate_agent_review_summary(summary, packet=PACKET) == [
        "source_refs_unknown:unknown://nested"
    ]


def test_agent_review_summary_validator_rejects_missing_source_ref() -> None:
    summary = {**_valid_summary(), "source_refs": []}

    schema_errors = list(Draft202012Validator(SUMMARY_SCHEMA).iter_errors(summary))
    assert schema_errors
    assert validate_agent_review_summary(summary, packet=PACKET) == ["source_refs_missing"]


def test_agent_review_summary_validator_rejects_forbidden_claims() -> None:
    summary = {
        **_valid_summary(),
        "summary": "SOP가 자동 정비 승인 기준이며 정비로 downtime 절감 효과가 입증됐습니다.",
    }

    errors = validate_agent_review_summary(summary, packet=PACKET)
    assert "forbidden_claims:SOP가 자동 정비 승인,정비로 downtime 절감" in errors


def test_agent_review_summary_validator_rejects_packet_mismatch() -> None:
    summary = {**_valid_summary(), "asset_id": "CNC-OTHER"}

    assert validate_agent_review_summary(summary, packet=PACKET) == ["asset_id_mismatch"]

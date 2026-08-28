from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.mvp.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    validate_agent_review_summary,
    validate_agent_review_summary_contract,
    validated_agent_review_summary,
)


ROOT = Path(__file__).resolve().parents[1]
SUMMARY_SCHEMA = json.loads(
    (ROOT / "contracts" / "schemas" / "agent-review-summary.schema.json").read_text(
        encoding="utf-8"
    )
)
PACKET_SCHEMA = json.loads(
    (ROOT / "contracts" / "schemas" / "agent-review-packet.schema.json").read_text(
        encoding="utf-8"
    )
)
PACKET = json.loads(
    (ROOT / "tests" / "fixtures" / "agent_review_packets" / "GS-002.json").read_text(
        encoding="utf-8"
    )
)
GOLD_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets"


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


def test_deterministic_agent_review_summary_validates_all_gold_packets() -> None:
    validator = Draft202012Validator(SUMMARY_SCHEMA)

    for scenario in ("GS-002", "GS-004", "GS-007"):
        packet = json.loads((GOLD_ROOT / f"{scenario}.json").read_text(encoding="utf-8"))
        summary = compose_deterministic_agent_review_summary(packet)

        assert list(validator.iter_errors(summary)) == []
        assert validate_agent_review_summary_contract(summary, packet=packet) == []
        assert summary["mode"] == "deterministic_fallback"
        assert summary["source_refs"] == packet["source_refs"]


def test_deterministic_agent_review_summary_explains_factor_bundle_focus() -> None:
    packet = json.loads((GOLD_ROOT / "GS-004.json").read_text(encoding="utf-8"))

    summary = compose_deterministic_agent_review_summary(packet)

    assert summary["confidence_label"] == "partial"
    assert len(summary["inspection_focus"]) == 1
    focus = summary["inspection_focus"][0]
    assert focus["component_id"] == "drive_power"
    assert focus["location_label"] == "주축 모터, 커플링, 동력 전달 하우징"
    assert focus["basis_refs"][:3] == [
        "factor.1.mechanical_power_w",
        "factor.2.overstrain_index",
        "factor.3.torque_nm",
    ]
    assert packet["inspection_targets"][0]["location_source_ref"] in packet["source_refs"]
    assert packet["inspection_targets"][0]["location_source_ref"] in focus["source_refs"]


def test_deterministic_agent_review_summary_fails_closed_on_data_quality_hold() -> None:
    packet = json.loads((GOLD_ROOT / "GS-007.json").read_text(encoding="utf-8"))

    summary = compose_deterministic_agent_review_summary(packet)

    assert summary["confidence_label"] == "data_quality_hold"
    assert summary["inspection_focus"] == []
    assert "확정하지 않습니다" in summary["summary"]
    assert "정비" not in summary["summary"]


def test_validated_agent_review_summary_discards_invalid_candidate() -> None:
    bad_candidate = {
        **_valid_summary(),
        "summary": "SOP가 자동 정비 승인 기준이며 정비로 downtime 절감 효과가 입증됐습니다.",
    }

    summary, errors = validated_agent_review_summary(
        packet=PACKET,
        candidate=bad_candidate,
    )

    assert errors == []
    assert summary["mode"] == "deterministic_fallback"
    assert summary["summary"] != bad_candidate["summary"]


def test_validated_agent_review_summary_discards_ungrounded_hold_candidate() -> None:
    packet = json.loads((GOLD_ROOT / "GS-007.json").read_text(encoding="utf-8"))
    bad_candidate = compose_deterministic_agent_review_summary(packet)
    bad_candidate.update(
        {
            "mode": "llm",
            "generated_at": "2099-01-01T00:00:00+09:00",
            "confidence_label": "grounded",
            "summary": "주축 베어링 마모가 확인되어 즉시 점검 후 교체가 필요합니다. 위험도 92%, 우선순위 immediate.",
            "evidence_gaps": [],
            "inspection_focus": [
                {
                    "component_id": "spindle_bearing",
                    "component_label": "주축 베어링",
                    "location_label": "가짜 위치",
                    "basis_refs": ["factor.1.invented_metric", "sop://made-up"],
                    "source_refs": packet["source_refs"],
                }
            ],
        }
    )

    errors = validate_agent_review_summary_contract(bad_candidate, packet=packet)
    assert "generated_at_mismatch" in errors
    assert "confidence_label_mismatch" in errors
    assert "inspection_focus_unavailable" in errors
    assert any(error.startswith("evidence_gaps_missing:") for error in errors)

    summary, fallback_errors = validated_agent_review_summary(
        packet=packet,
        candidate=bad_candidate,
    )
    assert fallback_errors == []
    assert summary["mode"] == "deterministic_fallback"
    assert summary["confidence_label"] == "data_quality_hold"
    assert summary["inspection_focus"] == []


def test_agent_review_summary_validator_rejects_unknown_component_and_basis_refs() -> None:
    summary = _valid_summary()
    summary["inspection_focus"] = [
        {
            **summary["inspection_focus"][0],
            "component_id": "unknown_component",
            "basis_refs": ["factor.1.invented_metric"],
        }
    ]

    errors = validate_agent_review_summary_contract(summary, packet=PACKET)

    assert "inspection_focus[0].component_id_unknown:unknown_component" in errors


def test_agent_review_summary_validator_rejects_basis_ref_outside_matching_target() -> None:
    summary = _valid_summary()
    summary["inspection_focus"] = [
        {
            **summary["inspection_focus"][0],
            "basis_refs": ["factor.99.invented_metric"],
        }
    ]

    errors = validate_agent_review_summary_contract(summary, packet=PACKET)

    assert "inspection_focus[0].basis_refs_unknown:factor.99.invented_metric" in errors


def test_agent_review_summary_validator_rejects_missing_packet_evidence_gap() -> None:
    summary = {**_valid_summary(), "evidence_gaps": PACKET["evidence_gaps"][:-1]}

    errors = validate_agent_review_summary_contract(summary, packet=PACKET)

    assert any(error.startswith("evidence_gaps_missing:") for error in errors)


def test_validated_agent_review_summary_discards_schema_invalid_candidate() -> None:
    bad_candidate = _valid_summary()
    del bad_candidate["title"]

    summary, errors = validated_agent_review_summary(
        packet=PACKET,
        candidate=bad_candidate,
    )

    assert errors == []
    assert summary["mode"] == "deterministic_fallback"
    assert summary["title"]


def test_validated_agent_review_summary_accepts_valid_candidate() -> None:
    candidate = _valid_summary()

    summary, errors = validated_agent_review_summary(packet=PACKET, candidate=candidate)

    assert errors == []
    assert summary == candidate


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


def test_agent_review_packet_schema_rejects_empty_source_refs() -> None:
    packet = json.loads((GOLD_ROOT / "GS-007.json").read_text(encoding="utf-8"))
    packet["source_refs"] = []

    errors = list(Draft202012Validator(PACKET_SCHEMA).iter_errors(packet))

    assert errors

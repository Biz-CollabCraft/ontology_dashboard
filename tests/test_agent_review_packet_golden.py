from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.dependencies import build_manufacturing_service


ROOT = Path(__file__).resolve().parents[1]
GOLD_ROOT = ROOT / "tests" / "fixtures" / "agent_review_packets"
PACKET_SCHEMA = json.loads(
    (ROOT / "contracts" / "schemas" / "agent-review-packet.schema.json").read_text(
        encoding="utf-8"
    )
)


def _load_gold(scenario: str) -> dict:
    return json.loads((GOLD_ROOT / f"{scenario}.json").read_text(encoding="utf-8"))


def test_agent_review_packet_gold_fixtures_match_schema() -> None:
    validator = Draft202012Validator(PACKET_SCHEMA)

    for scenario in ("GS-002", "GS-004", "GS-007"):
        payload = _load_gold(scenario)
        assert list(validator.iter_errors(payload)) == []
        assert payload["closed_loop_boundary"]["mutation_allowed"] is False
        assert payload["sop_retrieval"]["mutation_allowed"] is False
        assert "auto_approve" in payload["closed_loop_boundary"]["forbidden_actions"]
        assert payload["source_refs"]
        assert "human_questions" not in payload


def test_gs002_gold_carries_tooling_sop_location_and_history_review() -> None:
    packet = _load_gold("GS-002")

    assert packet["asset_id"] == "CNC-S04-L04-01"
    assert packet["inspection_targets"][0]["component_id"] == "tooling"
    assert packet["inspection_targets"][0]["location_label"] == "공구 매거진 및 스핀들 공구 체결부"
    assert packet["sop_guidance"][0]["sop_id"] == "SOP-DEMO-CNC-ROTATING-ASSEMBLY-001"
    assert packet["sop_guidance"][0]["sensor_judgment"]["inspection_result_mapping"] == {
        "records_operational_fact": True,
        "does_not_create_maintenance_event": True,
        "manual_recommendation_requires_manager_acceptance": True,
    }
    assert "최근 동일 부품 또는 동일 계통에 대한 점검/교체 이력 유무 조회" in packet[
        "history_review_items"
    ]


def test_gs004_gold_preserves_three_factor_refs_for_one_inspection_target() -> None:
    packet = _load_gold("GS-004")

    assert packet["asset_id"] == "CNC-S04-L02-03"
    assert packet["sop_guidance"] == []
    assert len(packet["inspection_targets"]) == 1
    target = packet["inspection_targets"][0]
    assert target["component_id"] == "drive_power"
    assert target["location_label"] == "주축 모터, 커플링, 동력 전달 하우징"
    assert target["basis_refs"][:3] == [
        "factor.1.mechanical_power_w",
        "factor.2.overstrain_index",
        "factor.3.torque_nm",
    ]
    assert len([ref for ref in target["basis_refs"] if ref.startswith("factor.")]) == 3
    assert "sensor_evidence.sensors.torque_nm" in target["basis_refs"]
    assert packet["sop_retrieval"]["query"]["component_ids"] == ["drive_power"]
    assert packet["sop_retrieval"]["query"]["factor_keys"] == [
        "mechanical_power_w",
        "overstrain_index",
        "torque_nm",
    ]


def test_gs007_gold_fails_closed_for_data_quality_hold() -> None:
    packet = _load_gold("GS-007")

    assert packet["asset_id"] == "CNC-S04-L05-01"
    assert packet["risk_summary"]["status_grade"] is None
    assert packet["risk_summary"]["failure_probability"] is None
    assert packet["review_priority"] is None
    assert packet["inspection_targets"] == []
    assert packet["sop_guidance"] == []
    assert packet["review_draft"]["evidence_gap_count"] >= 1
    rendered = json.dumps(packet, ensure_ascii=False)
    assert "정비로 downtime 절감" not in rendered
    assert "실제 고장 예방 입증" not in rendered
    assert "SOP가 자동 정비 승인" not in rendered


def test_current_service_packets_keep_gold_contract_shape(tmp_path: Path) -> None:
    service = build_manufacturing_service(tmp_path / "agent-review-gold.db", root=ROOT)
    cases = {
        "GS-002": "CNC-S04-L04-01",
        "GS-004": "CNC-S04-L02-03",
        "GS-007": "CNC-S04-L05-01",
    }

    for scenario, asset_id in cases.items():
        current = service.agent_review_packet(asset_id, "manufacturing-demo-project")
        gold = _load_gold(scenario)
        assert current["schema_version"] == gold["schema_version"]
        assert current["asset_id"] == gold["asset_id"]
        assert current["risk_summary"] == gold["risk_summary"]
        assert current["inspection_targets"] == gold["inspection_targets"]
        assert current["sop_retrieval"] == gold["sop_retrieval"]
        assert current["closed_loop_boundary"] == gold["closed_loop_boundary"]

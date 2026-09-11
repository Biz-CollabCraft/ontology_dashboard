from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_materialization import summary_key_payload
from app.operations.agent_review_summary_provider import build_tool_selected_agent_review_summary_prompt_payload

ROOT = Path(__file__).resolve().parents[1]
GOLD_CASES = [f"GS-{index:03d}" for index in range(1, 9)]


RAW_SCREEN_LEAK_PATTERNS = [
    r"\bmaintenance_recommended\b",
    r"\bmonitor_only\b",
    r"\bdata_quality_hold\b",
    r"\bN·m·min\b",
    r"\bN·m\b",
]


def _load_packet(case: str) -> dict[str, Any]:
    return json.loads((ROOT / f"tests/fixtures/agent_review_packets/{case}.json").read_text())


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _with_probe_context(packet: dict[str, Any]) -> dict[str, Any]:
    candidate = json.loads(json.dumps(packet, ensure_ascii=False))
    context = candidate.setdefault("evidence_context", {})
    context.setdefault("selected_basis", []).append(
        {
            "candidate_id": "input-to-screen:selected:probe",
            "candidate_type": "operation_context",
            "source_ref": "input-to-screen:selected:probe",
            "domain": "input_to_screen_stability",
            "relation_path": ["asset", "event", "screen"],
            "fact_type": "screen_delivery_probe",
            "as_of": candidate["snapshot_basis"]["observed_at"],
            "value_summary": "선택된 근거가 화면 브리핑 입력까지 전달된다",
            "freshness_state": "current",
            "required_for_boundary": True,
        }
    )
    context.setdefault("rejected_basis", []).append(
        {"source_ref": "input-to-screen:rejected:probe", "value_summary": "REJECTED_SCREEN_PROBE"}
    )
    candidate["source_refs"] = list(
        dict.fromkeys([*candidate.get("source_refs", []), "input-to-screen:selected:probe"])
    )
    return candidate


def _prompt_payload(packet: dict[str, Any]) -> dict[str, Any]:
    return build_tool_selected_agent_review_summary_prompt_payload(
        packet=packet,
        baseline_summary=compose_deterministic_agent_review_summary(packet),
    )


def _flow_refs_stay_in_packet_scope(payload: dict[str, Any]) -> bool:
    source_refs = set(payload["summary_context"]["source_refs"])
    for step in payload["decision_flow"]["primary_chain"]:
        for fact in step.get("facts") or []:
            source_ref = fact.get("source_ref")
            if source_ref and source_ref not in source_refs:
                return False
    return True


def _screen_text(summary: dict[str, Any]) -> str:
    parts = [str(summary.get("title") or ""), str(summary.get("summary") or "")]
    for role_summary in summary.get("role_summaries") or []:
        parts.append(str(role_summary.get("quote") or ""))
    return "\n".join(parts)


def _input_to_screen_checks(case: str) -> dict[str, bool]:
    original = _load_packet(case)
    reloaded = _load_packet(case)
    packet = _with_probe_context(original)
    payload = _prompt_payload(packet)
    summary = compose_deterministic_agent_review_summary(packet)
    key_payload = summary_key_payload(
        packet=packet,
        project_id=packet.get("project_id") or "manufacturing-demo-project",
        history_window="24h",
        provider=None,
    )
    encoded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    screen_text = _screen_text(summary)

    return {
        "입력_해시_재현성": _stable_hash(original) == _stable_hash(reloaded),
        "기준시각_키_유지": (
            key_payload["asset_id"] == packet["asset_id"]
            and key_payload["event_id"] == packet["snapshot_basis"]["event_id"]
            and key_payload["decision_as_of"] == packet["snapshot_basis"]["observed_at"]
        ),
        "선택근거만_전달": (
            "input-to-screen:selected:probe" in encoded_payload
            and "REJECTED_SCREEN_PROBE" not in encoded_payload
            and _flow_refs_stay_in_packet_scope(payload)
        ),
        "ViewModel_summary_context_전달": (
            payload["summary_context"]["asset_id"] == packet["asset_id"]
            and payload["summary_context"]["asset_label"] == packet["asset_label"]
            and payload["summary_context"]["generated_at"] == packet["generated_at"]
            and set(payload["allowed_output_fields"]) == {"title", "summary", "role_summaries"}
        ),
        "화면표현_준비계약": (
            summary["asset_id"] == packet["asset_id"]
            and summary["generated_at"] == packet["generated_at"]
            and all(role.get("quote") for role in summary.get("role_summaries") or [])
            and not any(re.search(pattern, screen_text) for pattern in RAW_SCREEN_LEAK_PATTERNS)
        ),
    }


def test_input_to_screen_delivery_stability_contracts_for_gold_fixture_set():
    results = {case: _input_to_screen_checks(case) for case in GOLD_CASES}
    passed = sum(1 for checks in results.values() for value in checks.values() if value)
    total = sum(len(checks) for checks in results.values())

    assert total == 40
    assert passed == total, results

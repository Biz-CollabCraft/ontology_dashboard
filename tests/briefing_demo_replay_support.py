"""Read-only replay of frozen inputs and historical candidates; no model or DB calls."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from app.operations.agent_briefing_review import decision_facts, briefing_issues
from app.operations.agent_review_summary import validate_agent_review_summary_contract, compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_provider import build_tool_selected_agent_review_summary_prompt_payload, _editable_prose_review_issues
from app.operations.asset_detail_view_model import compose_asset_detail_view_model

ROOT = Path(__file__).resolve().parents[1]

def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def load_cases():
    return json.loads((ROOT / "tests/fixtures/final_briefing_demo/cases.json").read_text())

def read_case(case_id):
    return next(c for c in load_cases() if c["case_id"] == case_id)

def replay_delivery(case):
    packet = deepcopy(case["packet"])
    payload = build_tool_selected_agent_review_summary_prompt_payload(packet=packet, baseline_summary=compose_deterministic_agent_review_summary(packet))
    facts = decision_facts(packet)
    basis = packet["snapshot_basis"]
    factors = [{**f, "rank": i + 1} for i, f in enumerate(packet.get("model_expression_context", {}).get("top_factors", []))]
    # This is an explicit projection of frozen packet facts, not a new prediction.
    artifact = {"artifact_id": basis["artifact_id"], "asset_id": packet["asset_id"], "asset_type": "cnc",
        "observed_at": basis["observed_at"], **packet["risk_summary"],
        "threshold": packet.get("model_expression_context", {}).get("threshold"),
        "top_factors": factors, "ranked_factor_evidence": factors,
        "evidence_payload": {"sensor_evidence": {"sensors": {f["feature"]: {"value": f.get("value"), "display_name": f.get("display_name", f["feature"]), "unit": f.get("unit", "")} for f in factors}}},
        "provenance": {"model_version": basis.get("model_version"), "dataset_version": basis.get("dataset_version"), "source_sha256": basis.get("source_sha256"), "evidence_payload_reference": basis["evidence_payload_reference"]}}
    if facts["data_quality_hold"]:
        artifact["status_grade"] = "data_quality_hold"
    vm = compose_asset_detail_view_model(asset={"asset_id": packet["asset_id"], "asset_type": "cnc", "display_name": packet["asset_label"]},
        result_artifact=artifact, event_id=basis["event_id"], evidence_context=packet.get("evidence_context"))
    checks = {"input_hash": digest(packet) == case["packet_sha256"],
        "asset_event_time": all(vm["snapshot_basis"].get(k) == basis.get(k) for k in ("asset_id", "event_id", "observed_at")),
        "selected_evidence_only": "rejected_basis" not in json.dumps(payload, ensure_ascii=False),
        "screen_context": payload["summary_context"]["asset_id"] == vm["asset"]["asset_id"]}
    if not all(checks.values()):
        raise ValueError("replay_delivery_contract_failed")
    selected = packet.get("evidence_context", {}).get("selected_basis", [])
    return {"case_id": case["case_id"], "label": case["label"], "packet": packet, "view_model": vm,
        "facts": facts, "checks": checks, "input_sha256": digest(packet),
        "evidence_count": len(selected), "source_count": len(packet.get("source_refs", [])),
        "excluded_record_count": len(facts.get("excluded_records", [])),
        "scope": "frozen_input_replay", "view_model_origin": "frozen_packet_replay_projection",
        "response": {"summary": None, "trace": {"provider": "historical-candidate-replay", "fallback": False, "reason": None, "validation_errors": [], "materialization": {"status": "pending"}}}}

def validate_replay(case, variant="recorded"):
    delivery = replay_delivery(case)
    packet = delivery["packet"]
    candidate = deepcopy(case["candidate"])
    if variant == "rejected":
        candidate["summary"] = "AI가 자동 승인과 정비 완료를 실행했습니다. 재고 확보가 완료되어 정상 운전 가능합니다."
    errors = validate_agent_review_summary_contract(candidate, packet=packet)
    errors += briefing_issues(candidate, decision_facts(packet))
    errors += _editable_prose_review_issues(candidate)
    passed = not errors
    return {"summary": candidate if passed else None,
        "trace": {"provider": "historical-candidate-replay", "fallback": not passed,
            "reason": None if passed else "candidate_rejected", "validation_errors": errors,
            "materialization": {"status": "ready" if passed else "fallback", "summary_key": digest([packet, candidate])}},
        "replay": {"case_id": case["case_id"], "input_sha256": digest(packet), "candidate_sha256": digest(candidate),
            "historical_run_index": case["historical_run_index"], "model": case["model"],
            "recorded_prompt_version": case["recorded_prompt_version"], "live_generation": False,
            "checks": {"identity_and_grounding": not validate_agent_review_summary_contract(candidate, packet=packet),
                "record_scope": not briefing_issues(candidate, decision_facts(packet)), "reader_language": not _editable_prose_review_issues(candidate)}}}

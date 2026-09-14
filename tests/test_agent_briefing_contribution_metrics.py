from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.operations.agent_briefing_review import decision_facts
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_materialization import summary_key_payload
from app.operations.agent_review_summary_provider import (
    build_tool_selected_agent_review_summary_prompt_payload,
)
from app.operations.agent_review_summary_workflow import AgentReviewSummaryWorkflow
from app.operations.context_providers import _history_record

ROOT = Path(__file__).resolve().parents[1]
GOLD_CASES = [f"GS-{index:03d}" for index in range(1, 9)]


def _packet(case: str) -> dict[str, Any]:
    return json.loads((ROOT / f"tests/fixtures/agent_review_packets/{case}.json").read_text())


def _prompt_payload(packet: dict[str, Any]) -> dict[str, Any]:
    return build_tool_selected_agent_review_summary_prompt_payload(
        packet=packet,
        baseline_summary=compose_deterministic_agent_review_summary(packet),
    )


def _all_flow_refs_are_in_source_scope(payload: dict[str, Any]) -> bool:
    source_refs = set(payload["summary_context"]["source_refs"])
    for step in payload["decision_flow"]["primary_chain"]:
        for fact in step.get("facts") or []:
            source_ref = fact.get("source_ref")
            if source_ref and source_ref not in source_refs:
                return False
    return True


def _record_refs_are_in_source_scope(payload: dict[str, Any]) -> bool:
    source_refs = set(payload["summary_context"]["source_refs"])
    facts = payload["decision_facts"]
    current_records = [
        *(facts.get("inspection_results") or []),
        *(facts.get("work_orders") or []),
    ]
    return all(record.get("source_ref") in source_refs for record in current_records)


def _add_rejected_probe(packet: dict[str, Any]) -> None:
    context = packet.setdefault("evidence_context", {})
    context.setdefault("rejected_basis", []).append(
        {"source_ref": "rejected:probe", "value_summary": "REJECTED_PROBE"}
    )


def _add_selected_probe(packet: dict[str, Any]) -> None:
    context = packet.setdefault("evidence_context", {})
    context.setdefault("selected_basis", []).append(
        {
            "candidate_id": "selected:briefing:metric",
            "candidate_type": "operation_context",
            "source_ref": "metric-selected:briefing",
            "domain": "presentation_metric",
            "relation_path": ["asset", "event", "decision"],
            "fact_type": "selection_metric_probe",
            "as_of": packet["snapshot_basis"]["observed_at"],
            "value_summary": "선택된 근거만 브리핑 입력으로 전달된다",
            "freshness_state": "current",
            "required_for_boundary": True,
        }
    )
    packet["source_refs"] = list(
        dict.fromkeys([*packet.get("source_refs", []), "metric-selected:briefing"])
    )


def _add_scope_probe_records(packet: dict[str, Any]) -> None:
    basis_event_id = packet["snapshot_basis"].get("event_id")
    same_asset = packet["asset_id"]
    after_basis_order = _history_record(
        {
            "work_order_id": "WO-AFTER-BASIS",
            "asset_id": same_asset,
            "event_id": basis_event_id,
            "status": "approved",
            "label": "기준 시각 이후 승인 기록",
            "recorded_at": "2026-08-01T00:05:00+09:00",
            "created_at": "2026-08-01T00:05:00+09:00",
            "updated_at": "2026-08-01T00:05:00+09:00",
            "approved_at": "2026-08-01T00:05:00+09:00",
        },
        source_prefix="closed-loop://work-order",
    )
    other_asset_order = _history_record(
        {
            "work_order_id": "WO-OTHER-ASSET",
            "asset_id": "CNC-OTHER",
            "event_id": basis_event_id,
            "status": "approved",
            "label": "다른 설비 승인 기록",
            "recorded_at": "2026-07-31T23:45:00+09:00",
            "created_at": "2026-07-31T23:45:00+09:00",
            "approved_at": "2026-07-31T23:55:00+09:00",
        },
        source_prefix="closed-loop://work-order",
    )
    history = packet.setdefault("maintenance_history_summary", {})
    history["work_orders"] = [*(history.get("work_orders") or []), after_basis_order, other_asset_order]
    packet["source_refs"] = list(
        dict.fromkeys(
            [
                *packet.get("source_refs", []),
                after_basis_order["source_ref"],
                other_asset_order["source_ref"],
            ]
        )
    )


def _contribution_1_checks(case: str) -> dict[str, bool]:
    packet = _packet(case)
    _add_selected_probe(packet)
    _add_rejected_probe(packet)
    _add_scope_probe_records(packet)

    payload = _prompt_payload(packet)
    key_payload = summary_key_payload(
        packet=packet,
        project_id=packet.get("project_id") or "manufacturing-demo-project",
        history_window="24h",
        provider=None,
    )
    facts = decision_facts(packet)
    encoded_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    return {
        "근거_선별_scope": (
            _record_refs_are_in_source_scope(payload)
            and _all_flow_refs_are_in_source_scope(payload)
            and "REJECTED_PROBE" not in encoded_payload
            and bool(facts.get("excluded_records"))
        ),
        "시간_정합성": (
            key_payload["decision_as_of"] == packet["snapshot_basis"]["observed_at"]
            and key_payload["asset_id"] == packet["asset_id"]
            and key_payload["event_id"] == packet["snapshot_basis"]["event_id"]
        ),
        "관계_흐름_전달": (
            payload["decision_flow"].get("flow_version") == "decision-flow-v1"
            and isinstance(payload["decision_flow"].get("primary_chain"), list)
            and len(payload["decision_flow"].get("primary_chain") or []) >= 2
            and bool(payload["decision_flow"].get("role_focus", {}).get("process_manager"))
        ),
        "화면_ViewModel_전달계약": (
            payload["summary_context"]["asset_id"] == packet["asset_id"]
            and payload["summary_context"]["selected_evidence"]["selected_basis"][-1]["source_ref"]
            == "metric-selected:briefing"
            and set(payload["allowed_output_fields"])
            == {"title", "summary", "role_summaries"}
        ),
    }


def test_contribution_1_evidence_package_time_consistency_and_screen_delivery_contracts():
    results = {case: _contribution_1_checks(case) for case in GOLD_CASES}
    passed = sum(1 for checks in results.values() for passed in checks.values() if passed)
    total = sum(len(checks) for checks in results.values())

    assert total == 32
    assert passed == total, results


class _FakeMaterializationService:
    def __init__(self, outcomes: list[dict[str, Any] | Exception]):
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def materialize_agent_review_summaries(self, project_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"project_id": project_id, **kwargs})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return deepcopy(outcome)


def _materialization_result(**overrides: Any) -> dict[str, Any]:
    result = {
        "scanned_count": 1,
        "materialized_count": 1,
        "created_count": 1,
        "reused_count": 0,
        "pending_count": 0,
        "items": [{"asset_id": "CNC-S04-L04-01", "status": "ready"}],
    }
    result.update(overrides)
    return result


def _stage(result: dict[str, Any], name: str) -> dict[str, Any]:
    return next(stage for stage in result["stages"] if stage["stage"] == name)


def _workflow_metric_scenarios() -> dict[str, dict[str, bool]]:
    scenarios: dict[str, dict[str, bool]] = {}

    service = _FakeMaterializationService([_materialization_result(scanned_count=3, materialized_count=3)])
    result = AgentReviewSummaryWorkflow(service).run(limit=3)
    scenarios["watcher_default"] = {
        "watcher_mode": result["operating_mode"]["mode"] == "watch",
        "read_only_boundary": result["read_only"] is True and result["mutation_allowed"] is False,
        "consumer_ready": _stage(result, "consumer_ready")["status"] == "completed",
    }

    service = _FakeMaterializationService([_materialization_result()])
    result = AgentReviewSummaryWorkflow(service).run(
        trigger="explicit_refresh", generation_policy="hybrid", explicit_refresh=True
    )
    scenarios["explicit_refresh"] = {
        "single_trigger_mode": result["operating_mode"]["mode"] == "single_trigger",
        "refresh_forwarded": service.calls[0].get("explicit_refresh") is True,
        "generation_policy_forwarded": service.calls[0].get("generation_policy") == "hybrid",
    }

    service = _FakeMaterializationService([_materialization_result(pending_count=1)])
    result = AgentReviewSummaryWorkflow(service).run()
    scenarios["pending_consumer"] = {
        "pending_stage": _stage(result, "consumer_ready")["status"] == "pending",
        "materialized_before_read": _stage(result, "summary_materialization")["status"] == "completed",
        "contract_named": bool(_stage(result, "consumer_ready").get("consumer_contract")),
    }

    service = _FakeMaterializationService([_materialization_result(created_count=0, reused_count=1)])
    result = AgentReviewSummaryWorkflow(service).run()
    scenarios["reuse_existing_summary"] = {
        "reuse_count": _stage(result, "summary_materialization")["reused_count"] == 1,
        "no_duplicate_create": _stage(result, "summary_materialization")["created_count"] == 0,
        "duplicate_policy": result["operating_mode"]["summary_duplicate_policy"] == "reuse_existing_summary",
    }

    service = _FakeMaterializationService([RuntimeError("temporary scan failure"), _materialization_result()])
    result = AgentReviewSummaryWorkflow(service).run(max_attempts=2)
    scenarios["retry_then_success"] = {
        "two_attempts": result["workflow"]["attempt_count"] == 2,
        "records_failed_then_success": [a["status"] for a in result["workflow"]["attempts"]] == ["failed", "succeeded"],
        "terminal_completed": result["workflow"]["terminal_status"] == "completed",
    }

    service = _FakeMaterializationService([RuntimeError("scan failure"), RuntimeError("scan failure")])
    result = AgentReviewSummaryWorkflow(service).run(max_attempts=2)
    scenarios["retry_exhausted"] = {
        "terminal_failed": result["workflow"]["terminal_status"] == "failed",
        "packet_build_blocked": _stage(result, "packet_build")["status"] == "skipped",
        "consumer_blocked": _stage(result, "consumer_ready")["status"] == "blocked",
    }

    service = _FakeMaterializationService([_materialization_result(items=[{"status": "failed"}])])
    result = AgentReviewSummaryWorkflow(service).run()
    scenarios["partial_failure"] = {
        "terminal_partial": result["workflow"]["terminal_status"] == "partial",
        "materialization_partial": _stage(result, "summary_materialization")["status"] == "partial",
        "consumer_partial": _stage(result, "consumer_ready")["status"] == "partial",
    }

    service = _FakeMaterializationService([_materialization_result()])
    result = AgentReviewSummaryWorkflow(service).run(
        history_window="6h", source="runtime", operating_mode={"target_scope": "asset", "mode": "single_trigger"}
    )
    scenarios["operating_scope"] = {
        "source_forwarded": service.calls[0]["source"] == "runtime",
        "history_forwarded": service.calls[0]["history_window"] == "6h",
        "scope_recorded": result["operating_mode"]["target_scope"] == "asset",
    }

    return scenarios


def test_contribution_2_ai_briefing_workflow_generation_lookup_retry_and_boundary_contracts():
    results = _workflow_metric_scenarios()
    passed = sum(1 for checks in results.values() for passed in checks.values() if passed)
    total = sum(len(checks) for checks in results.values())

    assert total == 24
    assert passed == total, results

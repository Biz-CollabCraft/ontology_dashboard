from __future__ import annotations

import copy
import json
from pathlib import Path

from app.common.llm_contract import ProviderUnavailable
from app.infra.db.operations_audit_repository import AuditRepository
from app.infra.llm.provider import OpenAICompatibleProvider
from app.operations.agent_review_summary import (
    compose_deterministic_agent_review_summary,
    validate_agent_review_summary_contract,
    validated_agent_review_summary,
)
from app.operations.agent_review_summary_generation_policy import (
    decide_generation,
    packet_is_current,
)
from app.operations.agent_review_summary_materialization import (
    AgentReviewSummaryMaterializer,
)
from app.operations.agent_review_summary_provider import (
    AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
    build_agent_review_summary_prompt_payload,
)


ROOT = Path(__file__).resolve().parents[1]
PACKET_PATH = ROOT / "tests/fixtures/agent_review_packets/GS-004.json"
INJECTION_PATH = ROOT / "tests/fixtures/security/briefing_evidence_injection.json"


def packet() -> dict:
    return json.loads(PACKET_PATH.read_text(encoding="utf-8"))


def injection_fixture() -> dict:
    return json.loads(INJECTION_PATH.read_text(encoding="utf-8"))


def packet_with_injection() -> tuple[dict, dict]:
    current = packet()
    attack = injection_fixture()
    current["evidence_context"] = {
        "selection_policy_version": "security-injection-fixture-v1",
        "decision_as_of": current["snapshot_basis"]["observed_at"],
        "temporal_status": "aligned",
        "selected_candidate_count": 1,
        "full_candidate_count": 1,
        "selected_basis": [
            {
                "candidate_id": "EVIDENCE-INJECTION-001",
                "candidate_type": "fact",
                "source_ref": current["source_refs"][0],
                "source_snapshot_id": current["snapshot_basis"]["artifact_id"],
                "source_version": "security-fixture-v1",
                "domain": "operations",
                "relation_path": [],
                "relation_paths": [],
                "display_fields": ["operator_note"],
                "fact_type": "operator_note",
                "as_of": current["snapshot_basis"]["observed_at"],
                "value_summary": attack["evidence_text"],
                "freshness_state": "fresh",
                "required_for_boundary": False,
                "limitation_state": None,
            }
        ],
        "limitations": [],
    }
    return current, attack


def test_s1_malformed_model_output_is_rejected_without_action_contract_change() -> None:
    current = packet()
    before = copy.deepcopy(current["closed_loop_boundary"])
    candidate = {
        **compose_deterministic_agent_review_summary(current),
        "mode": "llm",
        "actions": [{"action_id": "approve_inspection_work_order"}],
    }

    errors = validate_agent_review_summary_contract(candidate, packet=current)
    fallback, fallback_errors = validated_agent_review_summary(
        packet=current,
        candidate=candidate,
    )

    assert any(error.startswith("schema:") for error in errors)
    assert "forbidden_fields:action_id,actions" in errors
    assert fallback["mode"] == "deterministic_fallback"
    assert fallback_errors == []
    assert current["closed_loop_boundary"] == before


def test_s2_stale_evidence_is_fail_closed_before_generation() -> None:
    current = packet()
    current["evidence_context"] = {
        "temporal_status": "stale",
        "selected_basis": [],
        "rejected_basis": [],
    }

    assert packet_is_current(current) is False
    decision = decide_generation(
        policy="always",
        current_fingerprint="security-stale-fixture",
        input_valid=False,
    )

    assert decision["generation_action"] == "DEFER"
    assert decision["reuse_eligibility"] == "INELIGIBLE"
    assert decision["decision_reason"] == "invalid_or_expired_packet_blocked"


def test_s3_evidence_injection_stays_user_data_not_system_instruction(
    monkeypatch,
) -> None:
    current, attack = packet_with_injection()
    baseline = compose_deterministic_agent_review_summary(current)
    prompt_payload = build_agent_review_summary_prompt_payload(
        packet=current,
        baseline_summary=baseline,
    )
    evidence_text = attack["evidence_text"]

    captured: dict = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json() -> dict:
            return {
                "choices": [{"message": {"content": "{}"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 1,
                    "total_tokens": 11,
                },
            }

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "security-fixture-model")
    provider = OpenAICompatibleProvider()

    def fake_post(request_body: dict):
        captured["request_body"] = request_body
        return Response()

    monkeypatch.setattr(provider, "_post_chat_completion", fake_post)
    provider.generate_json_with_metadata(
        AGENT_REVIEW_SUMMARY_SYSTEM_PROMPT,
        prompt_payload,
    )

    messages = captured["request_body"]["messages"]
    assert messages[0]["role"] == "system"
    assert evidence_text not in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert evidence_text in messages[1]["content"]

    malicious = {
        **baseline,
        "mode": "llm",
        "summary": attack["malicious_summary"],
    }
    errors = validate_agent_review_summary_contract(malicious, packet=current)
    assert (
        f"unsupported_action_token:{attack['unsupported_action_id']}"
        in errors
    )


def test_s4_unsupported_action_suggestion_cannot_create_authority() -> None:
    current, attack = packet_with_injection()
    before = copy.deepcopy(current["closed_loop_boundary"])
    candidate = {
        **compose_deterministic_agent_review_summary(current),
        "mode": "llm",
        "summary": (
            "현재 backend action 계약과 무관하게 "
            f"{attack['unsupported_action_id']} 를 실행하세요."
        ),
    }

    errors = validate_agent_review_summary_contract(candidate, packet=current)
    fallback, fallback_errors = validated_agent_review_summary(
        packet=current,
        candidate=candidate,
    )

    assert (
        f"unsupported_action_token:{attack['unsupported_action_id']}"
        in errors
    )
    assert fallback["mode"] == "deterministic_fallback"
    assert fallback_errors == []
    assert current["closed_loop_boundary"] == before
    assert attack["unsupported_action_id"] not in before["available_action_ids"]


def test_s5_provider_unavailable_uses_deterministic_fallback(tmp_path) -> None:
    current = packet()

    class UnavailableProvider:
        name = "security-unavailable-provider"

        def generate(self, _packet):
            raise ProviderUnavailable("fixture provider unavailable")

    materializer = AgentReviewSummaryMaterializer(
        AuditRepository(tmp_path / "security-boundary.db"),
        UnavailableProvider(),
    )
    summary, trace = materializer.materialize(
        packet=current,
        organization_id="org-ontology-demo",
        project_id=current["project_id"],
        workspace_id="manufacturing-demo",
        history_window="24h",
    )

    assert summary["mode"] == "deterministic_fallback"
    assert trace["fallback"] is True
    assert trace["reason"] == "ProviderUnavailable"
    assert trace["provider"] == "security-unavailable-provider"

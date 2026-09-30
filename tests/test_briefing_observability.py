from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dependencies import build_manufacturing_service
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.briefing_observability import (
    BRIEFING_OPERATIONAL_TRACE_SCHEMA_VERSION,
    BRIEFING_TRACE_STAGES,
    evidence_selection_metrics,
)


ROOT = Path(__file__).resolve().parents[1]
ASSET_ID = "CNC-S04-L04-01"


class MeasuredProvider:
    name = "observability-test-provider"

    def __init__(self) -> None:
        self.calls = 0

    def generate_with_metadata(self, packet):
        self.calls += 1
        return (
            {
                **compose_deterministic_agent_review_summary(packet),
                "mode": "llm",
            },
            {
                "content_review_attempts": [
                    {"attempt": 1, "issues": [], "usage": None}
                ],
                "usage": {
                    "prompt_tokens": 101,
                    "completion_tokens": 23,
                    "total_tokens": 124,
                },
                "provider_latency_ms": 12.5,
            },
        )


@pytest.fixture
def service(tmp_path):
    result = build_manufacturing_service(tmp_path / "briefing-observability.db", root=ROOT)
    result.agent_review_summary_provider = MeasuredProvider()
    return result


def test_generation_trace_reconstructs_briefing_lifecycle_without_raw_payload(service):
    summary, trace = service.agent_review_summary(ASSET_ID)
    observable = trace["observability"]
    packet = service.agent_review_packet(ASSET_ID)
    expected_selection = evidence_selection_metrics(packet)

    assert summary["mode"] == "llm"
    assert observable["schema_version"] == BRIEFING_OPERATIONAL_TRACE_SCHEMA_VERSION
    assert observable["trace_id"].startswith("briefing:")
    assert observable["asset_id"] == ASSET_ID
    assert observable["event_id"] == packet["snapshot_basis"]["event_id"]
    assert observable["evidence_snapshot_id"] == packet["snapshot_basis"]["artifact_id"]
    assert observable["evidence_fingerprint"]
    assert observable["selection_strategy"] == "deterministic"
    assert observable["selection_policy_version"] == expected_selection["selection_policy_version"]
    assert observable["evidence_candidate_count"] == expected_selection["evidence_candidate_count"]
    assert observable["selected_evidence_count"] == expected_selection["selected_evidence_count"]
    assert observable["mandatory_evidence_count"] == expected_selection["mandatory_evidence_count"]
    assert (
        observable["mandatory_evidence_preserved_count"]
        == expected_selection["mandatory_evidence_preserved_count"]
    )
    assert observable["cache_reuse_decision"] == "generate"
    assert observable["provider"] == "observability-test-provider"
    assert observable["prompt_input_tokens"] == 101
    assert observable["output_tokens"] == 23
    assert observable["total_tokens"] == 124
    assert observable["usage_measurement"] == "provider_reported"
    assert observable["provider_latency_ms"] == 12.5
    assert observable["validation_result"] == "passed"
    assert observable["fallback_used"] is False
    assert observable["retry_count"] == 0
    assert observable["final_artifact_id"] == trace["materialization"]["summary_id"]
    assert observable["workflow_run_id"] == trace["workflow_run"]["workflow_run_id"]
    stored_run = service.repository.get_agent_review_workflow_run(
        observable["workflow_run_id"]
    )
    assert stored_run is not None
    assert stored_run["trace"]["observability"]["trace_id"] == observable["trace_id"]
    assert (
        stored_run["trace"]["observability"]["final_artifact_id"]
        == observable["final_artifact_id"]
    )
    assert set(observable["stages"]) == set(BRIEFING_TRACE_STAGES)
    assert observable["stages"]["event_evidence_load"]["measurement_status"] == "measured"
    assert observable["stages"]["evidence_selection"]["measurement_status"] == "measured"
    assert (
        observable["stages"]["snapshot_fingerprint_validation"]["measurement_status"]
        == "measured"
    )
    assert observable["stages"]["generation_decision"]["measurement_status"] == "measured"
    assert observable["stages"]["provider_call"]["measurement_status"] == "measured"
    assert observable["stages"]["output_validation"]["measurement_status"] == "measured"
    assert observable["stages"]["persistence"]["measurement_status"] == "measured"
    assert observable["stages"]["read_reuse_serving"]["measurement_status"] == "measured"
    assert observable["total_latency_ms"] is not None

    serialized = json.dumps(observable, ensure_ascii=False)
    assert "system_prompt" not in serialized
    assert "api_key" not in serialized
    assert "summary_context" not in serialized


def test_repeated_read_gets_new_trace_id_and_never_calls_provider(service):
    _, generated_trace = service.agent_review_summary(ASSET_ID)
    provider = service.agent_review_summary_provider
    assert provider.calls == 1

    summary, read_trace = service.cached_agent_review_summary(ASSET_ID)
    observable = read_trace["observability"]

    assert summary is not None
    assert provider.calls == 1
    assert observable["trace_id"] != generated_trace["observability"]["trace_id"]
    assert observable["cache_reuse_decision"] == "reuse"
    assert observable["serving_kind"] == "stored_reuse"
    assert observable["generation_policy"] == "read_only_lookup"
    assert observable["provider_latency_ms"] is None
    assert observable["stages"]["provider_call"] == {
        "duration_ms": 0.0,
        "measurement_status": "not_executed_reuse",
    }
    assert observable["final_artifact_id"] == generated_trace["materialization"]["summary_id"]


def test_provider_failure_and_validation_failure_are_distinct(tmp_path):
    provider_failure = build_manufacturing_service(
        tmp_path / "provider-failure.db", root=ROOT
    )

    class TimeoutProvider:
        name = "timeout-provider"

        def generate(self, packet):
            raise TimeoutError("fixture timeout")

    provider_failure.agent_review_summary_provider = TimeoutProvider()
    _, provider_trace = provider_failure.agent_review_summary(ASSET_ID)
    provider_observable = provider_trace["observability"]
    assert provider_observable["fallback_used"] is True
    assert provider_observable["fallback_reason"] == "TimeoutError"
    assert provider_observable["failure_category"] == "provider_failure"

    validation_failure = build_manufacturing_service(
        tmp_path / "validation-failure.db", root=ROOT
    )

    class InvalidProvider:
        name = "invalid-provider"

        def generate(self, packet):
            return {"mode": "llm"}

    validation_failure.agent_review_summary_provider = InvalidProvider()
    _, validation_trace = validation_failure.agent_review_summary(ASSET_ID)
    validation_observable = validation_trace["observability"]
    assert validation_observable["fallback_used"] is True
    assert validation_observable["fallback_reason"] == "summary_validation_failed"
    assert validation_observable["failure_category"] == "validation_failure"
    assert validation_observable["validation_result"] == "candidate_failed_fallback_valid"

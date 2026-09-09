from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

import pytest

from app.dependencies import build_manufacturing_service
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_generation_policy import decide_generation, cached_record_is_valid, packet_is_current
from app.operations.agent_review_summary_materialization import summary_key, summary_key_payload
from scripts.evaluate_agent_review_generation_policy import evaluate
from scripts.watch_agent_review_summaries import run_once

ROOT = Path(__file__).resolve().parents[1]


class Provider:
    name = "policy-test"
    calls = 0

    def generate(self, packet):
        self.calls += 1
        return {**compose_deterministic_agent_review_summary(packet), "mode": "llm"}


@pytest.fixture
def service(tmp_path):
    result = build_manufacturing_service(tmp_path / "policy.db", root=ROOT)
    result.agent_review_summary_provider = Provider()
    return result


def watch(service, policy="always", refresh=False):
    return run_once(
        database="test", service=service, project_id="manufacturing-demo-project",
        history_window="24h", limit=1, max_attempts=1, watch=False,
        interval_seconds=60, max_iterations=None, stale_policy="summary_key",
        source="fixture", require_live_provider=False,
        generation_policy=policy, explicit_refresh=refresh,
    )


def test_watcher_click_pending_refresh_and_exact_reuse(service):
    pending = watch(service, "click")
    assert pending["pending_count"] == 1
    assert pending["created_count"] == 0
    assert pending["stages"][-1]["status"] == "pending"
    assert service.agent_review_summary_provider.calls == 0
    first = watch(service, "click", True)
    assert first["items"][0]["generation_policy"]["generation_trigger"] == "USER_REFRESH"
    assert first["created_count"] == 1
    reused = watch(service, "hybrid")
    assert reused["reused_count"] == 1
    assert reused["items"][0]["generation_policy"]["generation_decision"] == "REUSE"
    watch(service, "click", True)
    assert service.agent_review_summary_provider.calls == 2


def test_watcher_hybrid_concurrency_uses_existing_guard(service):
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: watch(service, "hybrid"), range(2)))
    assert all(r["workflow"]["terminal_status"] == "completed" for r in results)
    assert service.agent_review_summary_provider.calls == 1

    assert sum(r["created_count"] for r in results) == 1


def test_live_candidate_branch_calls_policy_before_generation(service, monkeypatch):
    packet = service.agent_review_packet("CNC-S04-L04-01")
    monkeypatch.setattr(service, "_agent_review_summary_candidates", lambda **_: [
        {"asset_id": packet["asset_id"], "source_kind": "live_result"}
    ])
    monkeypatch.setattr(service, "_runtime_agent_review_packet_for_candidate", lambda *args, **kwargs: packet)
    assert watch(service, "click")["pending_count"] == 1
    assert service.agent_review_summary_provider.calls == 0
    assert watch(service, "hybrid")["created_count"] == 1
    assert service.agent_review_summary_provider.calls == 1


def test_fallback_retry_trace_and_click_does_not_retry(service):
    class TransientProvider(Provider):
        def generate(self, packet):
            if self.calls == 0:
                self.calls += 1
                raise TimeoutError("fixture outage")
            return super().generate(packet)

    service.agent_review_summary_provider = TransientProvider()
    assert watch(service, "hybrid")["items"][0]["status"] == "fallback"
    assert watch(service, "click")["reused_count"] == 1
    assert service.agent_review_summary_provider.calls == 1
    recovered = watch(service, "hybrid")
    assert recovered["items"][0]["generation_policy"]["generation_trigger"] == "RETRY"
    assert recovered["items"][0]["status"] == "ready"
    assert service.agent_review_summary_provider.calls == 2


def test_changed_snapshot_never_rebinds_and_get_never_generates(service, monkeypatch):
    first = watch(service, "hybrid")
    original = service.agent_review_packet

    def changed(*args, **kwargs):
        packet = deepcopy(original(*args, **kwargs))
        packet["snapshot_basis"]["source_sha256"] = "changed-snapshot"
        return packet

    monkeypatch.setattr(service, "agent_review_packet", changed)
    asset = first["items"][0]["asset_id"]
    summary, _ = service.cached_agent_review_summary(asset)
    assert summary is None
    assert service.agent_review_summary_provider.calls == 1
    pending = watch(service, "click")
    assert pending["pending_count"] == 1
    fresh = watch(service, "hybrid")
    assert fresh["items"][0]["summary_key"] != first["items"][0]["summary_key"]
    assert service.agent_review_summary_provider.calls == 2


def test_context_changes_during_generation_block_storage(service, monkeypatch):
    original = service.agent_review_packet
    changed = False

    def load(*args, **kwargs):
        packet = deepcopy(original(*args, **kwargs))
        if changed:
            packet["review_priority"] = "changed-during-generation"
        return packet

    class ChangingProvider(Provider):
        def generate(self, packet):
            nonlocal changed
            changed = True
            return super().generate(packet)

    monkeypatch.setattr(service, "agent_review_packet", load)
    service.agent_review_summary_provider = ChangingProvider()
    result = watch(service, "hybrid")
    assert result["workflow"]["terminal_status"] == "failed"
    changed = False
    candidate = service._agent_review_summary_candidates(
        project_id="manufacturing-demo-project", organization_id="org-ontology-demo",
        workspace_id="manufacturing-demo", limit=1, source="fixture",
    )[0]
    assert service.cached_agent_review_summary(candidate["asset_id"])[0] is None


@pytest.mark.parametrize("field", ["organization_id", "project_id", "workspace_id", "asset_id", "event_id", "history_window", "dataset_version", "context_sha256", "prompt_version", "summary_schema_version", "model_version"])
def test_scope_and_versions_cannot_reuse_old_identity(service, field):
    packet = service.agent_review_packet("CNC-S04-L04-01")
    identity = summary_key_payload(packet=packet, project_id="manufacturing-demo-project", history_window="24h", provider=None)
    old = summary_key(identity)
    identity[field] = "different"
    current = summary_key(identity)
    assert current != old
    decision = decide_generation(policy="hybrid", current_fingerprint=current, previous_fingerprint=old)
    assert decision["generation_decision"] == "PREGENERATE"


def test_policy_rejects_unknown_and_refresh_overrides_cache():
    with pytest.raises(ValueError):
        decide_generation(policy="unknown", current_fingerprint="key")
    for policy in ("click", "always", "hybrid"):
        trace = decide_generation(policy=policy, current_fingerprint="key", reuse_eligibility="EXACT_VALIDATED", explicit_refresh=True)
        assert trace["generation_decision"] == "ON_DEMAND"
        assert trace["generation_trigger"] == "USER_REFRESH"
        assert trace["generation_action"] == "GENERATE"
        assert trace["reuse_eligibility"] == "EXACT_VALIDATED"


def test_hybrid_minor_change_forces_generation_after_max_deferral():
    deferred = decide_generation(
        policy="hybrid",
        current_fingerprint="changed-key",
        previous_fingerprint="previous-key",
        material_change=False,
    )
    assert deferred["generation_trigger"] == "MINOR_CHANGE"
    assert deferred["generation_action"] == "DEFER"

    expired = decide_generation(
        policy="hybrid",
        current_fingerprint="changed-key",
        previous_fingerprint="previous-key",
        material_change=False,
        minor_change_deferral_expired=True,
    )
    assert expired["generation_trigger"] == "MINOR_CHANGE_MAX_WAIT"
    assert expired["generation_decision"] == "PREGENERATE"
    assert expired["generation_action"] == "GENERATE"


def test_temporal_80_snapshot_evaluation_preserves_critical_queries_with_bounded_deferral():
    report = evaluate()
    assert report["fixture_snapshots"] == 80
    hybrid = report["policies"]["hybrid"]
    assert hybrid["critical_generation_requested"] == hybrid["critical_count"] == 40
    assert hybrid["false_reuse_count"] == 0
    assert 0 < hybrid["simulated_background_reduction_vs_always"] < 1
    assert hybrid["simulated_critical_query_hits"] == report["policies"]["always"]["simulated_critical_query_hits"]
    assert hybrid["simulated_query_hits"] < report["policies"]["always"]["simulated_query_hits"]
    assert report["policies"]["click"]["simulated_background_generations"] == 0
    assert report["runtime_briefing_availability"] == "not_measured"
    assert report["provider_call_savings"] == "not_measured"
    assert 0 < hybrid["simulated_availability"] < 1
    assert hybrid["simulated_failures"] > 0
    assert hybrid["simulated_retries"] > 0
    assert hybrid["simulated_stale_completions_discarded"] > 0
    assert hybrid["splits"]["development"]["snapshot_count"] == 40
    assert hybrid["splits"]["fixed_holdout"]["snapshot_count"] == 40
    assert set(report["splits"]["development"]).isdisjoint(report["splits"]["fixed_holdout"])
    for index in range(8):
        runs = [report["policies"][p]["runs"][index] for p in ("click", "always", "hybrid")]
        # Every policy receives the same change/query/refresh timeline.
        assert all([q["time"] for q in r["queries"]] == [q["time"] for q in runs[0]["queries"]] for r in runs)
        assert all([d["time"] for d in r["decisions"] if d["source"] == "refresh"] == [182] for r in runs)
        assert all(r["queries"][0]["simulated_hit"] is False for r in runs)
        assert all([e for e in r["events"] if e["event"] == "change"] == [e for e in runs[0]["events"] if e["event"] == "change"] for r in runs)
    fast = hybrid["runs"][0]
    slow = hybrid["runs"][-1]
    assert next(q for q in fast["queries"] if q["time"] == 12)["simulated_hit"]
    assert not next(q for q in slow["queries"] if q["time"] == 12)["simulated_hit"]
    assert any(e["event"] == "stale_completion_discarded" for e in slow["events"])
    for run in hybrid["runs"]:
        for query in run["queries"]:
            if query["simulated_hit"]:
                assert any(e["event"] == "completed" and e["fingerprint"] == query["fingerprint"] and e["time"] <= query["time"] for e in run["events"])


@pytest.mark.parametrize("mutation", ["numeric_prose", "version", "binding", "context_hash"])
def test_corrupted_exact_cache_is_not_reusable_or_returned(service, monkeypatch, mutation):
    first = watch(service, "hybrid")
    item = first["items"][0]
    original = service.repository.get_agent_review_summary

    def corrupt(key):
        record = deepcopy(original(key))
        if record is None:
            return None
        if mutation == "numeric_prose":
            record["summary"]["summary"] = "예측 위험도는 99.123%입니다."
        elif mutation == "version":
            record["prompt_version"] = "wrong-version"
        elif mutation == "binding":
            record["snapshot_basis"]["source_sha256"] = "other-snapshot"
        else:
            record["trace"]["context_sha256"] = "other-context"
        return record

    monkeypatch.setattr(service.repository, "get_agent_review_summary", corrupt)
    summary, trace = service.cached_agent_review_summary(item["asset_id"])
    assert summary is None
    assert trace["reuse_eligibility"] == "INELIGIBLE"
    result = watch(service, "click")
    assert result["reused_count"] == 0
    assert result["items"][0]["generation_policy"]["generation_action"] == "DEFER"
    assert result["items"][0]["generation_policy"]["reuse_eligibility"] == "INELIGIBLE"
    assert service.agent_review_summary_provider.calls == 1
    regenerated = watch(service, "hybrid")
    assert regenerated["items"][0]["generation_policy"]["generation_action"] == "GENERATE"
    assert service.agent_review_summary_provider.calls == 2


def test_expired_current_context_invalidates_even_exact_record(service):
    from datetime import datetime, timezone
    first = watch(service, "hybrid")["items"][0]
    packet = service.agent_review_packet(first["asset_id"])
    record = service.repository.get_agent_review_summary(first["summary_key"])
    identity = summary_key_payload(packet=packet, project_id="manufacturing-demo-project", history_window="24h", provider=service.agent_review_summary_provider)
    assert cached_record_is_valid(record, packet=packet, key_payload=identity, materialization_key=record["summary_key"])
    # Unknown expiry metadata is fail-closed under the current closed schema.
    packet["operation_context_summary"]["expires_at"] = "2030-01-01T00:00:00Z"
    assert packet_is_current(packet, now=datetime(2029, 1, 1, tzinfo=timezone.utc), require_schema=False)
    assert not packet_is_current(packet, now=datetime(2031, 1, 1, tzinfo=timezone.utc), require_schema=False)
    identity = summary_key_payload(packet=packet, project_id="manufacturing-demo-project", history_window="24h", provider=service.agent_review_summary_provider)
    record["summary_key"] = summary_key(identity)
    record["trace"]["context_sha256"] = identity["context_sha256"]
    assert not cached_record_is_valid(record, packet=packet, key_payload=identity, materialization_key=record["summary_key"], now=datetime(2031, 1, 1, tzinfo=timezone.utc))

    packet["operation_context_summary"].pop("expires_at")
    packet["evidence_context"]["temporal_status"] = "stale"
    identity = summary_key_payload(packet=packet, project_id="manufacturing-demo-project", history_window="24h", provider=service.agent_review_summary_provider)
    record["summary_key"] = summary_key(identity)
    record["trace"]["context_sha256"] = identity["context_sha256"]
    assert not cached_record_is_valid(record, packet=packet, key_payload=identity, materialization_key=record["summary_key"])


def test_numeric_context_change_cannot_keep_old_prose(service):
    first = watch(service, "hybrid")["items"][0]
    packet = service.agent_review_packet(first["asset_id"])
    packet["risk_summary"]["failure_probability"] = 0.99123
    summary, trace = service.cached_agent_review_summary_for_packet(packet=packet)
    assert summary is None
    assert trace["reuse_eligibility"] == "INELIGIBLE"


@pytest.fixture
def runtime_candidate(service):
    candidate = {
        "source_kind": "post_maintenance_feedback",
        "asset_id": "CNC-S04-L04-01",
        "event_id": "RESULT#POLICY-RUNTIME-001",
        "dataset_version_id": "dsv-policy-runtime-001",
        "source_sha256": "policy-runtime-test-source",
    }

    class RuntimeDetail:
        def latest_result_artifact_references(self, **query):
            return [dict(candidate)]

        def latest_detail_view(self, **query):
            view = service.asset_detail_view_model(candidate["asset_id"])
            view["snapshot_basis"] = {
                **view["snapshot_basis"],
                "event_id": candidate["event_id"],
                "dataset_version": candidate["dataset_version_id"],
                "source_sha256": candidate["source_sha256"],
            }
            return view

    service.runtime_asset_detail_service = RuntimeDetail()
    return candidate


def test_runtime_generation_http_get_then_watcher_reuses_exact_packet(
    service, runtime_candidate, tmp_path, monkeypatch,
):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.dependencies import get_service, get_identity_service
    from identity_test_support import build_identity_service
    from app.operations.agent_review_summary_workflow import AgentReviewSummaryWorkflow

    first = AgentReviewSummaryWorkflow(service).run(source="post-maintenance", limit=1, generation_policy="hybrid")
    assert first["created_count"] == 1
    assert service.agent_review_summary_provider.calls == 1
    packet = service.runtime_agent_review_packet(
        runtime_candidate["asset_id"], dataset_version_id=runtime_candidate["dataset_version_id"], event_id=runtime_candidate["event_id"],
    )
    before = deepcopy(packet)
    assert packet["sop_retrieval"]["provider"] == "runtime_product_result"
    assert packet_is_current(packet)
    assert packet == before  # Validation never relabels provenance or rewrites input.

    identity = build_identity_service(tmp_path / "runtime-identity.db", app_env="test", seed_demo=True)
    monkeypatch.setitem(app.dependency_overrides, get_service, lambda: service)
    monkeypatch.setitem(app.dependency_overrides, get_identity_service, lambda: identity)
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "manager@ontology.local", "password": "Manager!2026"})
        assert login.status_code == 200
        response = client.get(
            f"/api/objects/{runtime_candidate['asset_id']}/agent-review-summary",
            params={"event_id": runtime_candidate["event_id"], "dataset_version_id": runtime_candidate["dataset_version_id"]},
        )
    assert response.status_code == 200, response.text
    assert response.json()["summary"] is not None
    assert response.json()["trace"]["reuse_eligibility"] == "EXACT_VALIDATED"
    assert response.json()["trace"]["materialization"]["summary_key"] == first["items"][0]["summary_key"]
    assert service.agent_review_summary_provider.calls == 1
    second = AgentReviewSummaryWorkflow(service).run(source="post-maintenance", limit=1, generation_policy="hybrid")
    assert second["created_count"] == 0
    assert second["reused_count"] == 1
    assert second["items"][0]["summary_key"] == first["items"][0]["summary_key"]
    assert service.agent_review_summary_provider.calls == 1


@pytest.mark.parametrize("field,value", [
    ("query.asset_id", "different-asset"),
    ("query.event_id", "different-event"),
    ("query.dataset_version_id", "different-dataset"),
    ("query.event_id", None),
    ("query.dataset_version_id", ""),
    ("query.extra", "unknown"),
    ("query", {"asset_id": "CNC-S04-L04-01"}),
    ("provider", "unknown_runtime"),
    ("top_k", True),
    ("top_k", 1),
    ("returned_count", 1),
    ("mutation_allowed", True),
])
def test_malformed_runtime_packet_never_reuses_cache(service, runtime_candidate, field, value):
    first = service.materialize_agent_review_summaries(source="post-maintenance", limit=1, generation_policy="hybrid")
    packet = service.runtime_agent_review_packet(
        runtime_candidate["asset_id"], dataset_version_id=runtime_candidate["dataset_version_id"], event_id=runtime_candidate["event_id"],
    )
    assert packet_is_current(packet)
    if field.startswith("query."):
        packet["sop_retrieval"]["query"][field.split(".")[1]] = value
    else:
        packet["sop_retrieval"][field] = value
    assert not packet_is_current(packet)
    # Retrieval metadata is outside the existing prose key: validation must
    # reject malformed metadata even when immutable identity still matches.
    key = summary_key(summary_key_payload(packet=packet, project_id="manufacturing-demo-project", history_window="24h", provider=service.agent_review_summary_provider))
    assert key == first["items"][0]["summary_key"]
    summary, trace = service.cached_agent_review_summary_for_packet(packet=packet)
    assert summary is None
    assert trace["reuse_eligibility"] == "INELIGIBLE"
    assert service.agent_review_summary_provider.calls == 1

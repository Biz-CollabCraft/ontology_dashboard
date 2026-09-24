"""Diagnostic API boundary probe. SQLite fixture, in-process HTTP, provider double."""
from copy import deepcopy
import json
from tests.test_operations import (
    database_path, service, identity, client, FakeAgentReviewSummaryProvider,
)
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_materialization import summary_key, summary_key_payload


def test_same_event_changed_context_api_provenance(client, service, monkeypatch):
    provider = FakeAgentReviewSummaryProvider(
        lambda p: {**compose_deterministic_agent_review_summary(p), "mode": "llm"}
    )
    service.agent_review_summary_provider = provider
    asset = "CNC-S04-L04-01"
    stored, generated_trace = service.agent_review_summary(asset)
    original_loader = service.agent_review_packet
    original_packet = original_loader(asset)
    changed_packet = deepcopy(original_packet)
    changed_packet["snapshot_basis"]["source_sha256"] = "oracle-changed-same-event"
    monkeypatch.setattr(service, "agent_review_packet", lambda *a, **kw: deepcopy(changed_packet))
    expected_key = summary_key(summary_key_payload(
        packet=changed_packet, organization_id="org-ontology-demo",
        project_id="manufacturing-demo-project", workspace_id="manufacturing-demo",
        history_window="24h", provider=provider,
    ))
    calls_before = provider.calls
    response = client.get(f"/api/objects/{asset}/agent-review-summary")
    body = response.json()
    trace = body["trace"]
    observed_key = trace["materialization"]["summary_key"]
    evidence = {
        "diagnostic": "SQLite/in-process API; controlled packet context mutation",
        "http_status": response.status_code,
        "same_event": original_packet["snapshot_basis"]["event_id"] == changed_packet["snapshot_basis"]["event_id"],
        "request_event_id": changed_packet["snapshot_basis"]["event_id"],
        "expected_source_sha256": changed_packet["snapshot_basis"]["source_sha256"],
        "expected_summary_key": expected_key,
        "returned_summary_key": observed_key,
        "original_summary_key": generated_trace["materialization"]["summary_key"],
        "reuse_eligibility": trace.get("reuse_eligibility"),
        "latest_stored": trace.get("latest_stored"),
        "provider_calls_during_get": provider.calls - calls_before,
        "returned_original_summary": body["summary"] == stored,
        "strict_exact_invariant": "pass" if expected_key == observed_key else "fail",
        "rebound_to_new_key": observed_key == expected_key,
    }
    print("ORACLE_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
    assert response.status_code == 200
    assert provider.calls == calls_before
    assert expected_key != observed_key
    assert observed_key == generated_trace["materialization"]["summary_key"]
    assert trace["reuse_eligibility"] == "LATEST_STORED"
    assert trace["latest_stored"] is True
    assert body["summary"] == stored

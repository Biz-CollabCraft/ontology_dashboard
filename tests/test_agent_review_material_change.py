from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.operations.agent_review_summary_generation_policy import (
    MAX_MINOR_CHANGE_DEFERRAL_SECONDS,
    material_change_required,
    packet_is_current,
)
from app.operations.agent_review_summary_materialization import summary_key_payload
from tests.test_agent_review_generation_policy import service, watch

ROOT = Path(__file__).resolve().parents[1]
def changed(packet, delta):
    p = deepcopy(packet)
    old = p["risk_summary"]["failure_probability"]
    p["risk_summary"]["failure_probability"] = old + delta
    p["model_expression_context"]["failure_probability"] = old + delta
    p["review_draft"]["summary"] = p["review_draft"]["summary"].replace(f"{old*100:.1f}%", f"{(old+delta)*100:.1f}%")
    p["snapshot_basis"]["source_sha256"] = "synthetic-numeric-change"
    return p

def identity(p):
    return summary_key_payload(packet=p, project_id=p["project_id"], history_window="24h", provider=None)

def decision(old, new):
    return material_change_required(new, old, current_identity=identity(new), previous_identity=identity(old))

def packet():
    return json.loads((ROOT / "tests/fixtures/agent_review_packets/GS-002.json").read_text())

def test_small_change_is_scheduling_only_and_cumulative_change_generates():
    p = packet()
    small = changed(p, .001)
    assert packet_is_current(small)
    assert not decision(p, small)
    assert decision(p, changed(p, .006))
    assert decision(p, p)  # Unknown changed binding with identical numbers is conservative.

@pytest.mark.parametrize("kind", ["threshold", "scope", "grade", "loss", "malformed", "stale", "observation", "model", "source_only"])
def test_critical_and_invalid_changes_override_minor_delta(kind):
    p = packet()
    if kind == "threshold":
        p["model_expression_context"]["threshold"] = p["risk_summary"]["failure_probability"] + .0005
    new = changed(p, .001)
    if kind == "scope": new["project_id"] = "other"
    if kind == "grade": new["risk_summary"]["status_grade"] = "critical"
    if kind == "loss": new["operation_context_summary"]["estimated_lost_units"] = 999
    if kind == "malformed": new["unknown"] = True
    if kind == "stale": new["model_expression_context"]["freshness_status"] = "stale"
    if kind == "observation": new["snapshot_basis"]["observed_at"] = "2026-09-07T00:00:00Z"
    if kind == "model": new["model_expression_context"]["model_version"] = "changed"
    if kind == "source_only":
        new = deepcopy(p)
        new["snapshot_basis"]["source_sha256"] = "unexplained"
    assert decision(p, new)

def test_minor_change_defers_without_returning_old_prose_then_refreshes(service, monkeypatch):
    first = watch(service, "hybrid")
    original = service.agent_review_packet
    monkeypatch.setattr(service, "agent_review_packet", lambda *a, **k: changed(original(*a, **k), .001))
    pending = watch(service, "hybrid")
    assert pending["pending_count"] == 1
    assert pending["items"][0]["generation_policy"]["reuse_eligibility"] == "INELIGIBLE"
    assert service.agent_review_summary_provider.calls == 1
    assert service.cached_agent_review_summary(first["items"][0]["asset_id"])[0] is None
    assert watch(service, "hybrid", True)["created_count"] == 1
    assert service.agent_review_summary_provider.calls == 2


def test_minor_change_max_wait_forces_background_regeneration(service, monkeypatch):
    watch(service, "hybrid")
    original = service.agent_review_packet
    monkeypatch.setattr(service, "agent_review_packet", lambda *a, **k: changed(original(*a, **k), .001))

    pending = watch(service, "hybrid")
    assert pending["pending_count"] == 1
    assert service.agent_review_summary_provider.calls == 1
    scope = next(iter(service._briefing_minor_change_deferred_since))
    service._briefing_minor_change_deferred_since[scope] -= MAX_MINOR_CHANGE_DEFERRAL_SECONDS + 1

    refreshed = watch(service, "hybrid")
    assert refreshed["created_count"] == 1
    assert refreshed["items"][0]["generation_policy"]["generation_trigger"] == "MINOR_CHANGE_MAX_WAIT"
    assert service.agent_review_summary_provider.calls == 2
    assert scope not in service._briefing_minor_change_deferred_since

def test_all_temporal_packets_are_schema_valid():
    from scripts.evaluate_agent_review_generation_policy import temporal_snapshots
    assert all(packet_is_current(p) for _,_,_,p in temporal_snapshots())

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event
import json
import logging
from pathlib import Path

from app.operations.agent_review_summary_generation_policy import background_generation_required, decide_generation
from app.operations.agent_review_summary_materialization import AgentReviewSummaryMaterializer
from tests.test_agent_review_generation_policy import service, watch, Provider

ROOT = Path(__file__).resolve().parents[1]


def packet():
    return json.loads((ROOT / 'tests/fixtures/agent_review_packets/GS-001.json').read_text())


def test_demand_gate_does_not_weaken_exact_binding_or_explicit_refresh():
    p = packet()
    assert not background_generation_required(p)
    deferred = decide_generation(policy='demand', current_fingerprint='new', background_required=False)
    assert deferred['generation_action'] == 'DEFER'
    assert deferred['reuse_eligibility'] == 'INELIGIBLE'
    assert decide_generation(policy='demand', current_fingerprint='new', background_required=False, explicit_refresh=True)['generation_action'] == 'GENERATE'
    assert decide_generation(policy='demand', current_fingerprint='new', input_valid=False, explicit_refresh=True)['generation_action'] == 'DEFER'
    for field in ('maintenance_history_summary', 'operation_context_summary'):
        changed = deepcopy(p); changed[field]['probe'] = 'changed'
        assert background_generation_required(changed, p)
    changed = deepcopy(p); changed['risk_summary']['failure_probability'] += .006
    assert background_generation_required(changed, p)
    changed = deepcopy(p); changed['risk_summary']['status_grade'] = 'warning'
    assert background_generation_required(changed)


def test_demand_service_defers_ordinary_packet_and_logs_request(service, monkeypatch, caplog):
    p = packet()
    monkeypatch.setattr(service, 'agent_review_packet', lambda *a, **kw: p)
    with caplog.at_level(logging.INFO, logger='app.operations.briefing'):
        result = watch(service, 'demand')
        assert result['pending_count'] == 1 and service.agent_review_summary_provider.calls == 0
        assert service.cached_agent_review_summary_for_packet(packet=p)[0] is None
        result = watch(service, 'demand', True)
        assert result['created_count'] == 1 and service.agent_review_summary_provider.calls == 1
        watch(service, 'demand')
        assert service.agent_review_summary_provider.calls == 1
    assert 'ordinary_risk_waits_for_explicit_request' in caplog.text
    assert '"event": "lookup"' in caplog.text
    assert '"provider_invocations": 1' in caplog.text
    assert p['review_draft']['summary'] not in caplog.text


def test_pending_background_jobs_keep_newest_observation(service, monkeypatch):
    # Hold the scope lock so both requests are unstarted. The later-arriving
    # older observation must not replace the newer pending request.
    from app.operations import service as module
    p = packet(); older = deepcopy(p)
    older['snapshot_basis']['observed_at'] = '2026-07-01T00:00:00Z'
    scope = (id(service), 'org-ontology-demo', p['project_id'], 'manufacturing-demo', p['asset_id'], '24h')
    lock = module._agent_review_summary_lock('scope:' + json.dumps(scope))
    registered = Event(); both = Event(); count = 0
    original_lock = module._agent_review_summary_lock
    def observed_lock(key):
        nonlocal count
        if key.startswith('scope:'):
            count += 1
            (registered if count == 1 else both).set()
        return original_lock(key)
    monkeypatch.setattr(module, '_agent_review_summary_lock', observed_lock)
    def run(p):
        return service._materialize_agent_review_packet(packet=p, project_id=p['project_id'], organization_id='org-ontology-demo', workspace_id='manufacturing-demo', history_window='24h', trigger='polling_watcher', engine='simple')
    lock.acquire()
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            newest = pool.submit(run, p); assert registered.wait(3)
            stale = pool.submit(run, older); assert both.wait(3)
        finally:
            lock.release()
        ready = newest.result(timeout=5); skipped = stale.result(timeout=5)
    assert service.agent_review_summary_provider.calls == 1
    assert ready[0] is not None and skipped[0] is None
    assert skipped[1]['generation_policy']['decision_reason'] == 'superseded_before_generation'


def test_provider_repair_metadata_is_measured_without_inventing_tokens(service):
    class MeasuredProvider(Provider):
        def generate_with_metadata(self, p):
            return self.generate(p), {'content_review_attempts': [{}, {}], 'usage': {'total_tokens': 123}}
    materializer = AgentReviewSummaryMaterializer(service.repository, MeasuredProvider())
    summary, trace = materializer._generate_summary(packet())
    assert not trace['fallback']
    assert trace['generation_metrics']['provider_invocations'] == 1
    assert trace['generation_metrics']['repair_count'] == 1
    assert trace['generation_metrics']['usage'] == {'total_tokens': 123}
    assert trace['generation_metrics']['duration_ms'] >= 0

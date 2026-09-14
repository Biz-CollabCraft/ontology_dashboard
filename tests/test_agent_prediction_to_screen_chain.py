import json
import pytest
from briefing_chain_support import IntegrationChain, digest

@pytest.fixture
def chain(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_ENV','test');monkeypatch.setenv('ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK','1')
    monkeypatch.delenv('CNC_MODEL_ARTIFACT_URI',raising=False);monkeypatch.delenv('MODEL_ARTIFACT_URI',raising=False)
    h=IntegrationChain(tmp_path/'chain.sqlite')
    try:yield h
    finally:h.close()

def test_prediction_packet_provider_workflow_persistence_and_real_read_api(chain):
    before=chain.activity()
    for c in chain.cases:
        assert chain.read(c['asset_id']).status_code==202
    assert not chain.transport.calls
    workflow=chain.run()
    assert workflow['created_count']==8
    assert workflow['workflow']['terminal_status']=='completed'
    assert len(chain.predictions)==8
    assert len(chain.transport.calls)==8
    summaries=chain.rows('agent_review_summaries');runs=chain.rows('agent_review_workflow_runs')
    assert len(summaries)==8
    for c in chain.cases:
        d=chain.delivery(c['case_id']);p=chain.packets[c['event_id']]
        assert all(d['checks'].values())
        response=chain.read(c['asset_id']);assert response.status_code==200
        wire=response.json();m=wire['trace']['materialization']
        row=next(r for r in summaries if r['summary_id']==m['summary_id'])
        run=next(r for r in runs if r['workflow_run_id']==row['workflow_run_id'])
        assert row['event_id']==run['event_id']==p['snapshot_basis']['event_id']==d['view_model']['snapshot_basis']['event_id']
        assert row['asset_id']==run['asset_id']==c['asset_id']
        assert row['summary_key']==m['summary_key']==run['summary_key']
        assert json.loads(row['summary_json'])==wire['summary']
        assert json.loads(row['snapshot_basis_json'])==p['snapshot_basis']
        assert set(wire['summary']['source_refs']).issubset(p['source_refs'])
        prompt=next(v for v in chain.transport.calls if v['summary_context']['asset_id']==c['asset_id'])
        assert 'decision_flow' in prompt and 'decision_facts' in prompt
        assert 'rejected_basis' not in json.dumps(prompt)
        assert set(prompt['decision_facts']['citation_catalog'].values()).issubset(p['source_refs'])
    assert chain.activity()==before
    assert len(chain.transport.calls)==8 # reads never generate
    same=chain.run();assert same['reused_count']==8
    assert len(chain.transport.calls)==8
    assert {r['summary_id'] for r in chain.rows('agent_review_summaries')}=={r['summary_id'] for r in summaries}

def test_invalid_provider_response_crosses_real_repair_and_workflow_failure_boundary(chain):
    before=chain.activity();chain.transport.reject=True
    workflow=chain.run()
    assert len(chain.transport.calls)==16 # real provider tries a repair, then rejects
    assert all('review_feedback' in p for p in chain.transport.calls[1::2])
    assert all(r['status']=='fallback' for r in chain.rows('agent_review_summaries'))
    assert workflow['workflow']['terminal_status']=='partial'
    assert workflow['stages'][-1]['status']=='partial'
    for c in chain.cases:
        result=chain.read(c['asset_id']).json()
        assert result['trace']['fallback'] is True
        assert result['summary']['mode']!='llm'
    assert chain.activity()==before
    chain.transport.reject=False
    recovery=chain.run()
    assert recovery['created_count']==8
    assert all(chain.read(c['asset_id']).json()['summary']['mode']=='llm' for c in chain.cases)

def test_changed_prediction_input_invalidates_stored_prose(chain):
    chain.run();case=chain.cases[1];asset=case['asset_id'];event=case['event_id']
    before=chain.read(asset).json();original_key=before['trace']['materialization']['summary_key']
    original=chain.delivery(case['case_id'])
    fixture=chain.service.fixtures[event]
    fixture['observation']['torque_nm']+=12
    fixture['observation']['timestamp']='2026-08-01T00:10:00+09:00'
    stale=chain.read(asset)
    assert stale.status_code==202
    assert stale.json()['summary'] is None
    workflow=chain.run();assert workflow['created_count']==1
    new=chain.read(asset).json()
    assert new['trace']['materialization']['summary_key']!=original_key
    fresh=chain.delivery(case['case_id'])
    assert fresh['view_model']['snapshot_basis']['observed_at']==fixture['observation']['timestamp']
    assert fresh['view_model']['risk']['current']!=original['view_model']['risk']['current']

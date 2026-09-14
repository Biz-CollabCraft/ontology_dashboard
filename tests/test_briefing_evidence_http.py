"""Real authenticated packet route, isolated SQLite, no LLM calls."""
from copy import deepcopy
from pathlib import Path
import pytest

from fastapi.testclient import TestClient
from app.dependencies import build_manufacturing_service, get_service, get_identity_service
from app.main import app
from app.operations.agent_review_summary_materialization import summary_key, summary_key_payload
from identity_test_support import build_identity_service

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("with_event", [False, True])
def test_packet_rejects_old_briefing_when_history_changes_at_same_observation(tmp_path, monkeypatch, with_event):
    monkeypatch.setenv('ONTOLOGY_DASHBOARD_ALLOW_HEURISTIC_MODEL_FALLBACK','1')
    service = build_manufacturing_service(tmp_path/'service.db',root=ROOT)
    identity = build_identity_service(tmp_path/'identity.db',app_env='test',seed_demo=True)
    monkeypatch.setitem(app.dependency_overrides,get_service,lambda:service)
    monkeypatch.setitem(app.dependency_overrides,get_identity_service,lambda:identity)
    # Selected-event routing normally reads the external runtime repository.
    # Supply the isolated fixture source while retaining the real HTTP route,
    # packet composer, key calculation, and authentication.
    if with_event:
        monkeypatch.setattr(service, 'runtime_agent_review_packet',
            lambda asset, project, **kwargs: service.agent_review_packet(
                asset, project, history_window=kwargs['history_window']))
    asset='CNC-S04-L04-01'
    with TestClient(app) as client:
        assert client.post('/api/auth/login',json={'email':'manager@ontology.local','password':'Manager!2026'}).status_code == 200
        url=f'/api/objects/{asset}/agent-review-packet'
        response=client.get(url)
        assert response.status_code == 200, response.text
        packet=response.json()
        params = {'event_id':packet['snapshot_basis']['event_id']} if with_event else {}
        key=summary_key(summary_key_payload(packet=packet,project_id='manufacturing-demo-project',history_window='24h',provider=service.agent_review_summary_provider))
        assert client.get(url,params={**params,'expected_summary_key':key}).status_code == 200
        original=service.agent_review_packet
        def changed(*args,**kwargs):
            value=deepcopy(original(*args,**kwargs))
            value['maintenance_history_summary']['work_orders'].append({'record_id':'new-work-order','status':'requested','source_ref':'work-order:new'})
            return value
        monkeypatch.setattr(service,'agent_review_packet',changed)
        stale=client.get(url,params={**params,'expected_summary_key':key})
        assert stale.status_code == 409, stale.text
        assert stale.json()['detail']['code'] == 'briefing_evidence_changed'
        current=client.get(url)
        assert current.status_code == 200
        assert current.json()['snapshot_basis'] == packet['snapshot_basis']

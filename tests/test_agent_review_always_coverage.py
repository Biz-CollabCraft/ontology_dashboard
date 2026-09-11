import pytest

from tests.test_agent_review_generation_policy import service, runtime_candidate


def test_always_bounded_live_scan_reaches_later_assets_and_reuses(service, monkeypatch):
    candidates = service._fixture_agent_review_summary_candidates(project_id='manufacturing-demo-project', limit=None)[:3]
    assert len(candidates) == 3
    candidates = [{**c, 'source_kind': 'live_result'} for c in candidates]
    offsets = []
    class Runtime:
        def latest_result_artifact_references(self, **query):
            offset = query.get('offset', 0)
            offsets.append(offset)
            return candidates[offset:offset + query['limit']]
    service.runtime_asset_detail_service = Runtime()
    monkeypatch.setattr(service, '_runtime_agent_review_packet_for_candidate',
                        lambda c, **kw: service.agent_review_packet(c['asset_id']))
    results = [service.materialize_agent_review_summaries(source='live', limit=2) for _ in range(3)]
    assert [r['created_count'] for r in results] == [2, 1, 0]
    assert service.agent_review_summary_provider.calls == 3
    assert results[-1]['reused_count'] == 2
    assert offsets == [0, 2, 0]


def test_scan_offset_reaches_repository_without_changing_scope():
    from app.infra.db.asset_detail_read_adapter import PostgreSQLAssetDetailReadAdapter
    from app.operations.asset_detail_view_model import AssetDetailViewModelService
    captured = {}
    class Repository:
        def resolve_version(self, **query):
            return {'id': 'version-1'}
        def latest_result_rows(self, **query):
            captured.update(query)
            return 'result_artifact', 0, []
    adapter = PostgreSQLAssetDetailReadAdapter(Repository(), validate_artifact=lambda p: None)
    view = AssetDetailViewModelService(adapter)
    view.latest_result_artifact_references(organization_id='org',project_id='project',workspace_id='workspace',limit=10,offset=20)
    assert {k: captured[k] for k in ('organization_id','project_id','workspace_id','dataset_version_id','offset','limit')} == {
        'organization_id':'org','project_id':'project','workspace_id':'workspace','dataset_version_id':'version-1','offset':20,'limit':10}


@pytest.mark.parametrize("email,password", [("manager@ontology.local", "Manager!2026"), ("engineer@ontology.local", "Engineer!2026"), ("technician@ontology.local", "Technician!2026")])
def test_initial_http_generation_reuses_watcher_result_but_explicit_regeneration_runs(service, runtime_candidate, tmp_path, monkeypatch, email, password):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.dependencies import get_service, get_identity_service
    from identity_test_support import build_identity_service
    identity = build_identity_service(tmp_path/'identity.db',app_env='test',seed_demo=True)
    monkeypatch.setitem(app.dependency_overrides,get_service,lambda:service)
    monkeypatch.setitem(app.dependency_overrides,get_identity_service,lambda:identity)
    asset = 'CNC-S04-L04-01'
    from urllib.parse import urlencode
    path = f'/api/objects/{asset}/agent-review-summary?' + urlencode({
        'event_id':runtime_candidate['event_id'], 'dataset_version_id':runtime_candidate['dataset_version_id']})
    with TestClient(app) as client:
        assert client.post('/api/auth/login',json={'email':email,'password':password}).status_code == 200
        assert client.get(path).json()['summary'] is None
        # Another watcher creates the exact summary after this tab's GET.
        service.materialize_agent_review_summaries(source='live',limit=1)
        assert service.agent_review_summary_provider.calls == 1
        headers={'X-CSRF-Token':client.cookies.get('ontology_csrf')}
        created=client.post(path+'&trigger=manual_materialization',headers=headers,json={})
        assert created.status_code == 200, created.text
        assert created.json()['trace']['materialization']['reused'] is True, created.json()['trace']
        assert service.agent_review_summary_provider.calls == 1
        refreshed=client.post(path+'&trigger=ui_manual_regeneration',headers=headers,json={})
        assert refreshed.status_code == 200, refreshed.text
        assert service.agent_review_summary_provider.calls == 2


def test_scan_wraps_after_dataset_shrinks_and_scope_cursors_are_independent(service):
    rows = [{'asset_id':str(i)} for i in range(4)]
    class Runtime:
        def latest_result_artifact_references(self, **q):
            return rows[q['offset']:q['offset']+q['limit']]
    service.runtime_asset_detail_service=Runtime()
    def page(project):
        return service._runtime_agent_review_summary_candidates(organization_id='org',project_id=project,workspace_id='ws',limit=2)
    assert page('one') == rows[:2]
    assert page('two') == rows[:2]
    service._agent_review_summary_candidates(organization_id='org',project_id='manufacturing-demo-project',workspace_id='ws',limit=1,source='fixture')
    assert len(service._briefing_scan_offsets)==2
    rows[:]=rows[:1]
    assert page('one') == rows
    assert page('two') == rows

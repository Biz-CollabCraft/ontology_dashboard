import pytest
from tests.test_agent_review_generation_policy import service
from app.operations.agent_review_summary_workflow import AgentReviewSummaryWorkflow

@pytest.mark.parametrize('fail_on', [1, 2])
def test_workflow_retries_failed_page_before_advancing(service, monkeypatch, fail_on):
    candidates = service._fixture_agent_review_summary_candidates(project_id='manufacturing-demo-project', limit=None)[:3]
    candidates = [{**c, 'source_kind': 'live_result'} for c in candidates]
    offsets = []
    class Runtime:
        def latest_result_artifact_references(self, **query):
            offsets.append(query['offset'])
            return candidates[query['offset']:query['offset'] + query['limit']]
    service.runtime_asset_detail_service = Runtime()
    builds = 0
    def packet(candidate, **kw):
        nonlocal builds
        builds += 1
        # Each successful generation also reloads its packet before persistence.
        if builds == (1 if fail_on == 1 else 3):
            raise RuntimeError('transient packet read failure')
        return service.agent_review_packet(candidate['asset_id'])
    monkeypatch.setattr(service, '_runtime_agent_review_packet_for_candidate', packet)
    result = AgentReviewSummaryWorkflow(service).run(source='live', limit=2, max_attempts=2)
    assert result['workflow']['terminal_status'] == 'completed'
    assert result['workflow']['attempt_count'] == 2
    assert offsets == [0, 0]
    assert {r['asset_id'] for r in result['items']} == {c['asset_id'] for c in candidates[:2]}
    assert service.agent_review_summary_provider.calls == 2
    next_page = service.materialize_agent_review_summaries(source='live', limit=2)
    assert offsets == [0, 0, 2]
    assert next_page['items'][0]['asset_id'] == candidates[2]['asset_id']
    assert service.agent_review_summary_provider.calls == 3

import json
import pytest
from app.operations import filesystem_briefing as briefing


def test_archived_event_keeps_own_dataset_and_complete_tick(tmp_path, monkeypatch):
    run=tmp_path/'runs'/'old-run'
    (run/'source').mkdir(parents=True)
    (run/'canonical').mkdir()
    (run/'canonical'/'asset_master.csv').write_text('asset_id\nA\nB\n')
    rows=[dict(asset_id=a, observation_id='obs-'+a, observed_at='2026-09-08T00:00:00Z') for a in ('A','B')]
    (run/'source'/'sensor_records.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    monkeypatch.setattr(briefing, '_archive_roots', lambda:[tmp_path])
    from app.diagnosis import contracts
    monkeypatch.setattr(contracts, 'selected_complete_file_tick', lambda:(tmp_path/'runs/new/source/sensor_records.jsonl', '', [], []))
    rid,ticks=briefing._bound_ticks('A','FILE#old-run#obs-A','old-run')
    assert rid=='old-run' and len(ticks[0][1])==2
    with pytest.raises(KeyError): briefing._bound_ticks('A','FILE#old-run#obs-A','new-run')
    with pytest.raises(KeyError): briefing._bound_ticks('B','FILE#old-run#obs-A','old-run')
    with pytest.raises(KeyError): briefing._bound_ticks('A','FILE#../old-run#obs-A',None)


def test_limit_response_is_recoverable():
    import asyncio
    from app.main import rate_limit_error_handler
    from app.common.exceptions import RateLimitExceeded
    response=asyncio.run(rate_limit_error_handler(None,RateLimitExceeded(bucket='test',retry_after=23)))
    assert response.status_code==429
    assert response.headers['retry-after']=='23'


@pytest.mark.parametrize('selected', [True, False])
def test_public_window_resolver_preserves_scenario_or_live_selection(monkeypatch, selected):
    from app.diagnosis import contracts, demo_scenarios
    from app.diagnosis import runtime_router
    scenario = ('selected', 'at', [], [])
    live = ('live', 'at', [], [])
    monkeypatch.setattr(demo_scenarios, 'selected_window', lambda: scenario if selected else None)
    monkeypatch.setattr(contracts, 'latest_complete_file_tick', lambda: live)
    assert contracts.selected_complete_file_tick() == (scenario if selected else live)
    assert runtime_router._latest_complete_file_tick() == (scenario if selected else live)


def test_missing_live_window_keeps_http_error_at_router_only(monkeypatch):
    from app.diagnosis import contracts, demo_scenarios, runtime_router
    from fastapi import HTTPException
    monkeypatch.setattr(demo_scenarios, 'selected_window', lambda: None)
    def missing():
        raise contracts.CompleteFileTickNotFound('missing window')
    monkeypatch.setattr(contracts, 'latest_complete_file_tick', missing)
    with pytest.raises(contracts.CompleteFileTickNotFound):
        contracts.selected_complete_file_tick()
    with pytest.raises(HTTPException) as caught:
        runtime_router._latest_complete_file_tick()
    assert caught.value.status_code == 503

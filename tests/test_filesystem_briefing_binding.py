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
    from app.diagnosis import runtime_router
    monkeypatch.setattr(runtime_router, '_latest_complete_file_tick', lambda:(tmp_path/'runs/new/source/sensor_records.jsonl', '', [], []))
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

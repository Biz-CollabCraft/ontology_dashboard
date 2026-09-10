import json
import pytest
from app.diagnosis import demo_scenarios as scenarios

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(scenarios, 'ROOT', tmp_path)
    scenarios.load_window.cache_clear()
    catalog={}
    for mode in ('normal','emergency'):
        window={'stream':str(tmp_path/mode/'sensor_records.jsonl'),'observed_at':'2026-09-08T00:00:00Z','ticks':[['2026-09-08T00:00:00Z',{str(i):{'asset_id':str(i)} for i in range(100)}]]}
        (tmp_path/(mode+'-window.json')).write_text(json.dumps(window))
        catalog[mode]={'window':'private-path','observed_at':window['observed_at']}
    (tmp_path/'catalog.json').write_text(json.dumps(catalog))
    yield tmp_path
    scenarios.load_window.cache_clear()

def test_switch_and_restore(isolated):
    assert scenarios.selected_window() is None
    assert scenarios.select_scenario('normal','tester')['mode']=='normal'
    assert len(scenarios.selected_window()[2])==100
    assert scenarios.select_scenario('emergency','tester')['mode']=='emergency'
    assert scenarios.select_scenario('live','tester')['mode']=='live'
    assert scenarios.selected_window() is None

def test_reject_unknown_and_hide_paths(isolated):
    with pytest.raises(ValueError): scenarios.select_scenario('../unknown','tester')
    assert scenarios.scenario_status()['mode']=='live'
    assert 'window' not in scenarios.scenario_status()['options']['normal']

def test_incomplete_data_does_not_change_selection(isolated):
    (isolated/'normal-window.json').write_text(json.dumps({'ticks':[]}))
    with pytest.raises(ValueError): scenarios.select_scenario('normal','tester')
    assert scenarios.scenario_status()['mode']=='live'

@pytest.mark.parametrize('mode', ['normal', 'emergency', 'live'])
def test_generated_tick_refreshes_without_partial_frames(isolated, mode):
    run = isolated/'generated'/mode/'runs'/'test'
    (run/'source').mkdir(parents=True)
    (run/'canonical').mkdir()
    (run/'canonical'/'asset_master.csv').write_text('asset_id\nA\nB\n')
    stream = run/'source'/'sensor_records.jsonl'
    rows = [{'asset_id': asset, 'observed_at': '2026-09-09T00:00:00Z'} for asset in ('A','B')]
    rows.append({'asset_id':'A','observed_at':'2026-09-09T00:10:00Z'})
    stream.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (isolated/'live-state.json').write_text(json.dumps({mode:{'stream':str(stream)}}))
    scenarios.select_scenario(mode, 'tester')
    assert scenarios.selected_window()[1] == '2026-09-09T00:00:00Z'
    with stream.open('a') as handle:
        handle.write(json.dumps({'asset_id':'B','observed_at':'2026-09-09T00:10:00Z'})+'\n')
    assert scenarios.selected_window()[1] == '2026-09-09T00:10:00Z'

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from fastapi import HTTPException
from jsonschema import Draft202012Validator
from app.operations.filesystem_briefing import filesystem_briefing_packet
from app.operations.agent_briefing_review import decision_facts
from app.operations.agent_review_summary_materialization import summary_key, summary_key_payload

EVENT = 'FILE#run#obs'
ASSET = 'CMP-S01-L04-01'

@pytest.fixture
def setup(monkeypatch):
    from app.diagnosis import runtime_router
    row = {'asset_id':ASSET, 'asset_type':'compressor', 'observation_id':'obs', 'measurements':{'pressure_raw':100,'vibration_raw':28}}
    monkeypatch.setattr(runtime_router, '_latest_complete_file_tick', lambda:(Path('/tmp/runs/run/source/sensor_records.jsonl'),'2026-09-09T10:00:00+00:00',[row],[]))
    identity = {'project_id':'manufacturing-demo-project','workspace_id':'manufacturing-demo','event_id':EVENT,'asset_id':ASSET,'equipment_id':ASSET}
    coordination = {**identity,'work_order_id':'wo','status':'pending','request':{'downtime_minutes':30,'work_summary':'체결부 정비','affected_items':'공기 공급'},'response':None}
    lineage = {'event_id':EVENT,
        'work_orders':[{**identity,'work_order_id':'wo','work_type':'inspection','status':'approved','created_at':'2026-09-09T10:01:00+00:00'}],
        'inspection_results':[{**identity,'work_order_id':'wo','inspection_result_id':'ir','outcome':'maintenance_recommended','findings':['체결부 진동 이상'],'recorded_at':'2026-09-09T10:02:00+00:00'}],
        'activities':[{**identity,'activity_id':'activity','work_order_id':'wo','aggregate_type':'inspection_coordination','payload':coordination,'created_at':'2026-09-09T10:03:00+00:00'}]}
    reader=SimpleNamespace(event_lineage=lambda **kw:deepcopy(lineage))
    service=SimpleNamespace(maintenance_lineage_query=reader)
    def packet():
        return filesystem_briefing_packet(asset_id=ASSET,event_id=EVENT,dataset_version_id='run',project_id='manufacturing-demo-project',history_window='24h',service=service)
    return lineage,reader,packet


def test_file_packet_contains_current_inspection_coordination_and_contract(setup):
    _,_,make=setup
    p=make(); facts=decision_facts(p)
    assert facts['inspection_results'][0]['findings']==['체결부 진동 이상']
    assert facts['work_orders'][0]['production_coordination']['status']=='pending'
    assert '30분' in facts['work_orders'][0]['summary']
    assert p['snapshot_basis']['observed_at']=='2026-09-09T10:00:00+00:00'
    assert p['maintenance_history_summary']['workflow_as_of']=='2026-09-09T10:03:00+00:00'
    schema=json.loads((Path(__file__).parents[1]/'contracts/schemas/agent-review-packet.schema.json').read_text())
    Draft202012Validator(schema).validate(p)


def test_record_change_invalidates_summary_key_without_sensor_change(setup):
    lineage,_,make=setup
    def key(p): return summary_key(summary_key_payload(packet=p,project_id='manufacturing-demo-project',history_window='24h',provider=None))
    before=make()
    lineage['activities'][0]['payload']['status']='confirmed'
    lineage['activities'][0]['payload']['response']={'scheduled_window':'14시'}
    after=make()
    assert before['snapshot_basis']==after['snapshot_basis']
    assert key(before)!=key(after)


@pytest.mark.parametrize('field,value',[('asset_id','OTHER'),('event_id','OTHER'),('project_id','OTHER')])
def test_mismatched_owner_records_fail_closed(setup,field,value):
    lineage,_,make=setup
    lineage['work_orders'][0][field]=value
    with pytest.raises(HTTPException) as exc: make()
    assert exc.value.status_code==503


def test_history_outage_is_not_an_empty_history(setup):
    _,reader,make=setup
    def fail(**kwargs): raise OSError('database unavailable')
    reader.event_lineage=fail
    with pytest.raises(HTTPException) as exc: make()
    assert exc.value.detail['code']=='briefing_history_unavailable'


def test_pending_approval_is_not_treated_as_approved_or_started(setup):
    from app.operations.agent_briefing_review import build_decision_flow, briefing_issues
    _,_,make=setup
    p=make(); facts=decision_facts(p)
    assert build_decision_flow(p)['current_stage']=='inspection_completed_pending_production_approval'
    quotes=[{'role':role,'quote':'정비 권고입니다. 승인 시각은 10시입니다.'} for role in ('maintenance_technician','process_manager')]
    issues=briefing_issues({'role_summaries':quotes},facts)
    assert any('승인 시각' in issue for issue in issues)
    assert any('30분' in issue for issue in issues)

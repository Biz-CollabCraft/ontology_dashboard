from copy import deepcopy
import json
import pytest
from app.operations.briefing_economics import reference_economics, BASIS

def packet(asset='CNC-S03-L04-03'):
    return {'project_id':'manufacturing-demo-project', 'asset_id':asset,
            'snapshot_basis':{'event_id':'E','observed_at':'2026-09-10T00:00:00Z'}}

def test_matches_ui_reference():
    e=reference_economics(packet())
    m=e['metrics']
    assert m['hourly_production_cost']['value']==126900
    assert m['stop_production_cost']['value']==63450
    assert m['opportunity_exposure']['value']==31725
    assert m['conditional_maintenance_labor']['value']==2920
    assert m['conditional_replacement_parts']['value']==12453
    assert m['stop_minutes']['basis']=='default_assumption'
    assert e['source_sha256'] in e['source_ref']

def test_compressor_and_no_unknown_asset():
    assert reference_economics(packet('CMP-S01-L01-01'))['metrics']['hourly_production_cost']['value']==507600
    assert reference_economics(packet('OTHER'))['status']=='not_applicable'

@pytest.mark.parametrize('value',[0,10,-1,float('nan')])
def test_request_time_preserved(monkeypatch,value):
    import app.operations.agent_briefing_review as review
    monkeypatch.setattr(review,'decision_facts',lambda p:{'production_coordination':[{'production_coordination':{'request':{'downtime_minutes':value}}}]})
    e=reference_economics(packet())
    if value>=0:
        assert e['metrics']['stop_minutes']['value']==value
        assert e['metrics']['stop_minutes']['basis']=='recorded_request'
    else: assert e['status']=='unavailable'

def test_missing_and_version_hash(tmp_path):
    assert reference_economics(packet(),tmp_path/'missing')['status']=='unavailable'
    basis=json.loads(BASIS.read_text())
    path=tmp_path/'basis.json'; path.write_text(json.dumps(basis))
    first=reference_economics(packet(),path)
    basis['parameters'][0]['value']=10
    path.write_text(json.dumps(basis))
    assert reference_economics(packet(),path)['source_sha256']!=first['source_sha256']

def test_sop_applicability():
    from app.operations.filesystem_briefing import _file_sops
    view={}
    result=_file_sops(view,{'asset_type':'cnc','predicted_failure_type':'tool_wear_failure',
                          'top_factors':[{'feature':'tool_wear_min'}]})
    assert result['returned_count']>0 and view['inspection_targets']
    assert _file_sops({}, {'asset_type':'compressor','top_factors':[]})['returned_count']==0

def test_numeric_review():
    from app.operations.agent_briefing_review import decision_facts,briefing_issues
    p=packet(); p['reference_economics']=reference_economics(p)
    facts=decision_facts(p)
    assert any('hourly_production_cost' in s for s in briefing_issues({'role_summaries':[]},facts))
    candidate={'role_summaries':[{'role':'process_manager','quote':'가정 기반 시간당 생산원가 126,900원, 30분 정지 환산액 63,450원입니다.'}]}
    assert not briefing_issues(candidate,facts)

def test_materialization_hash_includes_costs():
    from app.operations.agent_review_summary_materialization import _summary_context_sha256
    p=packet(); before=_summary_context_sha256(p)
    p['reference_economics']=reference_economics(p)
    assert before!=_summary_context_sha256(p)
    before=_summary_context_sha256(p)
    p['reference_economics']['metrics']['stop_minutes']['value']=10
    assert before!=_summary_context_sha256(p)

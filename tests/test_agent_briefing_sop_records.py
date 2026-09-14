"""SOP and recorded workflow facts must reach the actual prose provider."""
from copy import deepcopy
import json
from pathlib import Path
import pytest

from app.operations.agent_briefing_context import record_context
from app.operations.agent_review_packet import _closed_loop_record
from app.operations.context_providers import _history_record
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary, validate_agent_review_summary_contract
from app.operations.agent_review_summary_provider import (
    AgentReviewSummaryProvider, build_agent_review_summary_prompt_payload,
    build_tool_selected_agent_review_summary_prompt_payload,
)
from app.operations.agent_review_summary_materialization import summary_key_payload

ROOT=Path(__file__).resolve().parents[1]

def packet(case="GS-002"):
    return json.loads((ROOT/f"tests/fixtures/agent_review_packets/{case}.json").read_text())

def owner(**changes):
    return {"inspection_result_id":"IR-BR-1", "work_order_id":"WO-BR-1",
            "asset_id":"CNC-S04-L04-01", "event_id":"EVT-GS-002",
            "outcome":"maintenance_recommended", "recorded_at":"2026-07-31T23:50:00+09:00",
            "findings":["커플링 편심 확인"],
            "checklist":[{"item_id":"alignment","status":"fail","note":"편심","secret":"DROP"}],
            "measurements":[{"name":"torque_nm","value":0,"unit":"N·m","secret":"DROP"}],
            "secret":"DROP", **changes}

@pytest.mark.parametrize("project",[_closed_loop_record,_history_record])
def test_owner_projection_keeps_findings_and_measurements_without_unknown_fields(project):
    original=owner(); saved=deepcopy(original)
    record=project(original,source_prefix="closed-loop://inspection-result")
    assert record['findings']==['커플링 편심 확인']
    assert record['measurements']==[{'name':'torque_nm','value':0,'unit':'N·m'}]
    assert record['checklist'][0]['status']=='fail'
    assert record['outcome']=='maintenance_recommended'
    assert 'DROP' not in str(record)
    assert original==saved

@pytest.mark.parametrize("builder",[build_agent_review_summary_prompt_payload,build_tool_selected_agent_review_summary_prompt_payload])
def test_both_payload_paths_deliver_sop_thresholds_measurements_and_record_status(builder):
    p=packet(); sop=p['sop_guidance'][0]
    sop['sop_version']='test-sop-v1'
    sop['sensor_judgment']['secret']='DROP'
    p['maintenance_history_summary']['inspection_results']=[_history_record(owner(),source_prefix='closed-loop://inspection-result')]
    p['maintenance_history_summary']['work_orders']=[_history_record(owner(status='approved',approved_at='2026-07-31T23:55:00+09:00'),source_prefix='closed-loop://work-order')]
    saved=deepcopy(p)
    ctx=builder(packet=p,baseline_summary=compose_deterministic_agent_review_summary(p))['summary_context']
    assert ctx['sop_guidance'][0]['sensor_judgment']['criteria']==sop['sensor_judgment']['criteria']
    assert ctx['sop_guidance'][0]['sop_version']=='test-sop-v1'
    assert ctx['risk_summary']['prediction_horizon_hours']==p['risk_summary']['prediction_horizon_hours']
    assert ctx['model_factors'][0]['value']==p['model_expression_context']['top_factors'][0]['value']
    history=ctx['maintenance_history']
    assert history['inspection_results'][0]['findings']==['커플링 편심 확인']
    assert history['inspection_results'][0]['measurements'][0]['value']==0
    assert history['work_orders'][0]['status']=='approved'
    assert history['work_orders'][0]['owner_record_provenance']['approved_at']=='2026-07-31T23:55:00+09:00'
    assert history['work_orders'][0]['record_context']['temporal_relation']=='at_or_before_basis'
    assert 'DROP' not in str(ctx)
    assert p==saved

@pytest.mark.parametrize('timestamp,expected',[
    ('2026-08-01T00:05:00+09:00','after_basis'),
    ('2026-08-01T00:00:00+09:00','at_or_before_basis'),
    ('2026-08-01T00:00:00','unknown'),('invalid','unknown'),
])
def test_record_state_uses_latest_owner_timestamp_not_old_creation(timestamp,expected):
    p=packet()
    record=_history_record(owner(status='approved',approved_at=timestamp,created_at='2026-07-30T00:00:00+09:00'),source_prefix='closed-loop://work-order')
    assert record_context(record,packet=p)['record_context']['temporal_relation']==expected

def test_other_asset_and_prior_event_are_not_current_event_evidence():
    p=packet()
    bad=_history_record(owner(asset_id='OTHER',event_id='OLD'),source_prefix='closed-loop://inspection-result')
    context=record_context(bad,packet=p)['record_context']
    assert context['asset_scope']=='mismatch' and context['event_relation']=='other_event'

def test_hold_can_still_report_existing_owner_records_without_restoring_risk_factors():
    p=packet('GS-007')
    p['maintenance_history_summary']['inspection_results']=[_history_record(owner(asset_id=p['asset_id'],event_id=p['snapshot_basis']['event_id']),source_prefix='closed-loop://inspection-result')]
    result=build_tool_selected_agent_review_summary_prompt_payload(packet=p,baseline_summary=compose_deterministic_agent_review_summary(p))
    assert result['context_selection']['called_tools']==['data_quality.lookup','maintenance_history.lookup']
    assert result['summary_context']['maintenance_history']['inspection_results']
    assert result['summary_context']['model_factors']==[]
    assert result['summary_context']['sop_guidance']==[]

def test_actual_provider_can_describe_recorded_approval_and_completion():
    p=packet()
    p['maintenance_history_summary']['work_orders']=[_history_record(owner(status='approved'),source_prefix='closed-loop://work-order')]
    p['maintenance_history_summary']['maintenance_actions']=[_history_record(owner(status='completed',maintenance_action_id='MA-BR-1'),source_prefix='closed-loop://maintenance-action')]
    class Capture:
        name='capture'
        def generate_json(self,system,payload,**kwargs):
            self.payload=payload; self.system=system
            baseline=compose_deterministic_agent_review_summary(p)
            result={k:baseline[k] for k in ('title','summary','role_summaries')}
            result['role_summaries'][1]['quote']='기록 시각 7월 31일 23:50 기준 작업요청 WO-BR-1의 상태는 승인입니다. 작업 MA-BR-1의 기록 상태는 완료입니다. 후속 일정을 검토하세요.'
            result['role_summaries'][2]['quote']='작업요청은 승인 상태입니다. 정지 120분 가정 시 예상 손실 25개로 생산 영향은 중간 수준입니다. 후속 일정을 검토하세요.'
            return result
    capture=Capture(); result=AgentReviewSummaryProvider(capture).generate(p)
    assert capture.payload['summary_context']['maintenance_history']['work_orders'][0]['status']=='approved'
    assert '기록 상태는 완료' in result['role_summaries'][1]['quote']
    assert not validate_agent_review_summary_contract(result,packet=p)
    assert 'must not claim work has been approved' not in capture.system

def test_new_inspection_facts_and_sop_rules_change_cache_identity():
    p=packet()
    def key(p):return summary_key_payload(packet=p,project_id='manufacturing-demo-project',history_window='24h',provider=None)
    initial=key(p)
    p['maintenance_history_summary']['inspection_results']=[_history_record(owner(),source_prefix='closed-loop://inspection-result')]
    assert key(p)!=initial
    previous=key(p)
    p['sop_guidance'][0]['sensor_judgment']['criteria'][0]['threshold']['value']=999
    assert key(p)!=previous


def test_current_service_sop_metadata_and_owner_fields_match_extended_read_schema(tmp_path):
    from app.dependencies import build_manufacturing_service
    from jsonschema import Draft202012Validator
    service=build_manufacturing_service(tmp_path/'sop-records.db',root=ROOT)
    p=service.agent_review_packet('CNC-S04-L04-01','manufacturing-demo-project')
    schema=json.loads((ROOT/'contracts/schemas/agent-review-packet.schema.json').read_text())
    assert not list(Draft202012Validator(schema).iter_errors(p))
    procedure=json.loads((ROOT/'data/fixtures/inspection_sop/demo-cnc-inspection-guidance-v1-1.json').read_text())
    assert p['sop_guidance'][0]['sop_version']==procedure['version']
    assert p['sop_guidance'][0]['procedure_title']==procedure['title']
    p['maintenance_history_summary']['inspection_results']=[
        _history_record(owner(),source_prefix='closed-loop://inspection-result')
    ]
    p['maintenance_history_summary']['work_orders']=[
        _history_record(owner(status='approved',approved_at='2026-07-31T23:55:00+09:00'),source_prefix='closed-loop://work-order')
    ]
    assert not list(Draft202012Validator(schema).iter_errors(p))
    delivered=build_tool_selected_agent_review_summary_prompt_payload(
        packet=p,baseline_summary=compose_deterministic_agent_review_summary(p))['summary_context']
    assert delivered['sop_guidance'][0]['sensor_judgment']['criteria']
    assert delivered['maintenance_history']['inspection_results'][0]['findings']==['커플링 편심 확인']
    assert delivered['maintenance_history']['work_orders'][0]['status']=='approved'

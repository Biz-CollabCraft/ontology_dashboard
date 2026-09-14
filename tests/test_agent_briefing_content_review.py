from copy import deepcopy
import json
from pathlib import Path
import pytest
from app.operations.agent_briefing_review import decision_facts,briefing_issues
from app.operations.agent_review_summary_provider import AgentReviewSummaryProvider
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.context_providers import _history_record
ROOT=Path(__file__).resolve().parents[1]
def packet():
 p=json.loads((ROOT/'tests/fixtures/agent_review_packets/GS-002.json').read_text())
 raw={'asset_id':p['asset_id'],'event_id':p['snapshot_basis']['event_id'],'work_order_id':'WO-1','status':'approved','created_at':'2026-07-31T23:40:00+09:00','approved_at':'2026-07-31T23:55:00+09:00'}
 p['maintenance_history_summary']['work_orders']=[_history_record(raw,source_prefix='closed-loop://work-order')]
 return p

def good(p):
 b=compose_deterministic_agent_review_summary(p)
 b['role_summaries'][1]['quote']='작업요청은 7월 31일 23:55 승인 기록이 있습니다. 착수 준비와 일정을 검토하세요.'
 b['role_summaries'][2]['quote']='작업요청은 승인 상태입니다. 정지 120분 가정 시 예상 손실을 고려해 일정을 검토하세요.'
 return b

def test_scoped_records_exclude_future_other_event_and_conflicts():
 p=packet();r=p['maintenance_history_summary']['work_orders'][0]
 assert len(decision_facts(p)['work_orders'])==1
 for field,value in [('event_id','other'),('asset_id','other'),('approved_at','2026-08-02T00:00:00+09:00')]:
  q=deepcopy(p);q['maintenance_history_summary']['work_orders'][0]['owner_record_provenance'][field]=value
  assert not decision_facts(q)['work_orders']
 q=deepcopy(p);r=deepcopy(q['maintenance_history_summary']['work_orders'][0]);r['status']='requested';q['maintenance_history_summary']['work_orders'].append(r)
 assert not decision_facts(q)['work_orders']

def test_retry_is_bounded_and_usage_counts_both_calls():
 p=packet();valid=good(p);bad=deepcopy(valid);bad['role_summaries'][2]['quote']='점검 승인 여부는 검토 중입니다.'
 class Provider:
  name='test'
  def __init__(self,always_bad=False):self.calls=[];self.always_bad=always_bad
  def generate_json_with_metadata(self,system,payload,**kwargs):
   self.calls.append(payload)
   return {'payload':bad if len(self.calls)==1 or self.always_bad else valid,'provider_metadata':{'usage':{'prompt_tokens':10,'completion_tokens':5,'total_tokens':15}}}
 provider=Provider();result,meta=AgentReviewSummaryProvider(provider).generate_with_metadata(p)
 assert len(provider.calls)==2 and 'review_feedback' in provider.calls[1]
 assert meta['usage']['total_tokens']==30
 assert not briefing_issues(result,decision_facts(p))
 rejected=Provider(True)
 with pytest.raises(ValueError,match='briefing_content_review_failed') as e:AgentReviewSummaryProvider(rejected).generate(p)
 assert len(rejected.calls)==2 and len(e.value.review_attempts)==2

def test_record_ids_are_not_required_in_prose():
 p=packet();assert 'WO-1' not in good(p)['role_summaries'][1]['quote']
 assert not briefing_issues(good(p),decision_facts(p))

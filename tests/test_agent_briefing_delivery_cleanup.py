import json
from pathlib import Path
from copy import deepcopy
import pytest
from app.operations.agent_review_summary_provider import build_tool_selected_agent_review_summary_prompt_payload, build_agent_review_summary_prompt_payload,AgentReviewSummaryProvider
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary,_validate_prose_priorities,_directive_prose_claims
from app.operations.agent_context_tool_pipeline import execute_packet_context_tool
from app.operations.agent_briefing_review import briefing_issues,decision_facts
from app.operations.context_providers import _history_record
ROOT=Path(__file__).resolve().parents[1]
def packet():return json.loads((ROOT/'tests/fixtures/agent_review_packets/GS-002.json').read_text())
@pytest.mark.parametrize('builder',[build_tool_selected_agent_review_summary_prompt_payload,build_agent_review_summary_prompt_payload])
def test_priority_and_stale_draft_projection(builder):
 p=packet();p['review_draft']['history_summary']=['STALE-CONTRADICTING-TEXT']
 c=builder(packet=p,baseline_summary=compose_deterministic_agent_review_summary(p))['summary_context']
 assert c['review_priority']==p['review_priority']
 assert 'STALE-CONTRADICTING-TEXT' not in json.dumps(c)

def test_tools_return_only_the_requested_relation_details():
 p=packet();a=execute_packet_context_tool('spare_part.lookup',p);b=execute_packet_context_tool('similar_event.lookup',p)
 assert a['traversals'] and b['traversals']
 assert all('similar_events' not in x for x in a['traversals'])
 assert all('spare_parts' not in x for x in b['traversals'])

def test_priority_and_negative_boundary_do_not_hide_real_errors():
 p=packet()
 assert not _validate_prose_priorities(['production_impact: medium, 정비 우선순위 high'],packet=p)
 assert _validate_prose_priorities(['priority low'],packet=p)
 assert _validate_prose_priorities(['low priority'],packet=p)
 assert not _directive_prose_claims(['수리 지시를 대신하지 않는 점을 유의하십시오.'])
 assert _directive_prose_claims(['수리 지시를 대신하지 않는 점을 유의하십시오. 부품을 교체하세요.'])

def test_verified_record_references_are_preserved_and_untrusted_refs_are_not():
 p=packet();raw={'asset_id':p['asset_id'],'event_id':p['snapshot_basis']['event_id'],'inspection_result_id':'IR-CLEAN','recorded_at':'2026-07-31T23:40:00+09:00','outcome':'maintenance_recommended','findings':['커플링 편심 확인']}
 record=_history_record(raw,source_prefix='closed-loop://inspection-result');p['maintenance_history_summary']['inspection_results']=[record];p['source_refs'].append(record['source_ref'])
 b=compose_deterministic_agent_review_summary(p);b['role_summaries'][1]['quote']='커플링 편심 확인 결과는 정비 권고이며, 일정 판단에는 작업요청과 작업 가능 시간 근거가 필요합니다.';b['role_summaries'][2]['quote']='정지 120분 가정은 생산 일정 판단용 추정치이며, 생산 순서 판단에는 승인 상태와 작업 가능 시간 근거가 필요합니다.'
 assert not briefing_issues(b,decision_facts(p))
 class Fake:
  name='test'
  def generate_json(self,*a,**kw):
   r=deepcopy(b)
   for role in r['role_summaries']:role['source_refs']=['invented://ref']
   return r
 result=AgentReviewSummaryProvider(Fake()).generate(p)
 assert all(record['source_ref'] in r['source_refs'] for r in result['role_summaries'])
 assert 'invented://ref' not in json.dumps(result)

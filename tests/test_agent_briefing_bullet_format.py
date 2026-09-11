from copy import deepcopy
import pytest
from app.operations.agent_briefing_review import decision_facts
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary,validate_agent_review_summary_contract
from app.operations.agent_review_summary_provider import AgentReviewSummaryProvider
from test_agent_briefing_luna_boundaries import packet

def test_bold_does_not_hide_wrong_lost_quantity():
 p=packet();s=compose_deterministic_agent_review_summary(p)
 s.update(mode='llm',summary='예상 손실 수량은 **999개**입니다. [[ref:1]]')
 assert any(e.startswith('prose_lost_units_mismatch') for e in validate_agent_review_summary_contract(s,packet=p))

@pytest.mark.parametrize('citation,valid',[('1',True),('99999',False),('javascript:alert(1)',False)])
def test_inline_citations_require_registered_index(citation,valid):
 p=packet();s=compose_deterministic_agent_review_summary(p)
 for role in s['role_summaries']:role['quote']='정지 120분 가정과 예상 손실 25개는 생산 일정 판단용 추정치입니다. [[ref:'+citation+']]'
 class Fake:
  name='test'
  def generate_json(self,*a,**kw):return deepcopy(s)
 if valid:
  result=AgentReviewSummaryProvider(Fake()).generate(p)
  assert result['source_refs'][0]==decision_facts(p)['citation_catalog']['1']
 else:
  with pytest.raises(ValueError,match='citation_catalog'):AgentReviewSummaryProvider(Fake()).generate(p)

@pytest.mark.parametrize('phrase',['운영 스냅샷','일부 운영 스냅샷','계획 가정','estimated_lost_units','production_impact'])
def test_internal_snapshot_or_assumption_terms_are_repaired_or_rejected(phrase):
 p=packet();s=compose_deterministic_agent_review_summary(p)
 for role in s['role_summaries']:
  role['quote']='- 실제 가용성은 '+phrase+'으로 확인되지 않았습니다. [[ref:1]]'
 class Fake:
  name='test'
  def generate_json(self,*a,**kw):return deepcopy(s)
 with pytest.raises(ValueError,match='내부 표현'):AgentReviewSummaryProvider(Fake()).generate(p)

def test_provider_repairs_raw_units_internal_codes_and_directive_claims_on_second_attempt():
 p=packet();baseline=compose_deterministic_agent_review_summary(p)
 bad=deepcopy(baseline);bad.update(mode='llm')
 good=deepcopy(baseline);good.update(mode='llm')
 for role in bad['role_summaries']:
  role['quote']='제품 유형 M 기준에서 12,650 N·m·min입니다. 승인 검토와 라인·셀 순서를 결정하세요. [[ref:1]]'
 for role in good['role_summaries']:
  role['quote']='과부하 지표 12,650 뉴턴미터·분은 기준을 넘어 동력 전달부 확인으로 이어집니다. 라인·셀 순서 판단에는 승인 상태와 작업 가능 시간 근거가 더 필요합니다. [[ref:1]]'
 class Fake:
  name='test'
  def __init__(self):self.calls=0
  def generate_json(self,*a,**kw):
   self.calls+=1
   return deepcopy(bad if self.calls==1 else good)
 fake=Fake();result=AgentReviewSummaryProvider(fake).generate(p)
 assert fake.calls==2
 assert '제품 유형 M' not in str(result)
 assert 'N·m·min' not in str(result)
 assert '결정하세요' not in str(result)

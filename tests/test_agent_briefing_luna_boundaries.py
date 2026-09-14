import json
from pathlib import Path
from copy import deepcopy
import pytest
from app.operations.agent_briefing_review import decision_facts,briefing_issues
from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
from app.operations.agent_review_summary_provider import build_agent_review_summary_prompt_payload,build_tool_selected_agent_review_summary_prompt_payload
from app.operations.context_providers import _history_record
ROOT=Path(__file__).resolve().parents[1]
def packet(case='GS-002'):return json.loads((ROOT/f'tests/fixtures/agent_review_packets/{case}.json').read_text())
@pytest.mark.parametrize('step',['승인 여부 재확인이 아니라 준비·일정 검토입니다.','승인 여부를 다시 확인하는 단계가 아니라 준비·일정 검토입니다.'])
def test_approved_record_allows_negated_reapproval_step(step):
 facts={'inspection_results':[],'work_orders':[{'status':'approved'}],'operation_context':{}}
 def candidate(t):return {'role_summaries':[{'role':r,'quote':'작업요청은 승인된 상태입니다. '+t} for r in ('maintenance_technician','process_manager')]}
 assert not briefing_issues(candidate(step),facts)
 assert briefing_issues(candidate('승인 여부 검토와 준비가 필요합니다.'),facts)
 assert briefing_issues(candidate('승인 대기 상태로 일정 검토가 필요합니다.'),facts)
@pytest.mark.parametrize('builder',[build_agent_review_summary_prompt_payload,build_tool_selected_agent_review_summary_prompt_payload])
def test_hold_withholds_planning_values_on_all_paths(builder):
 p=packet('GS-007');original=deepcopy(p)
 payload=builder(packet=p,baseline_summary=compose_deterministic_agent_review_summary(p))
 for c in (payload['summary_context']['operation_context'],payload['decision_facts']['operation_context']):
  assert c['production_impact'] is None and c['estimated_lost_units'] is None and c['estimated_downtime_minutes'] is None
 assert p==original
@pytest.mark.parametrize('claim',['생산 영향과 예상 손실 수량은 확정할 수 있으며, 추가 점검이 필요합니다.','생산 영향은 확정됩니다.'])
def test_hold_rejects_positive_claim_even_with_negative_elsewhere(claim):
 f=decision_facts(packet('GS-007'));candidate={'summary':'생산 영향은 확인되지 않습니다.','role_summaries':[{'role':'process_manager','quote':claim}]}
 assert briefing_issues(candidate,f)
 candidate['role_summaries'][0]['quote']='생산 영향과 예상 손실은 확정할 수 없습니다.'
 assert not briefing_issues(candidate,f)
@pytest.mark.parametrize('change',[{'approved_at':'2026-08-01T00:05:00+09:00'},{'asset_id':'OTHER','event_id':'OTHER'}])
def test_excluded_approval_facts_are_removed_but_audit_metadata_remains(change):
 p=packet();raw={'work_order_id':'WO-OLD','asset_id':p['asset_id'],'event_id':p['snapshot_basis']['event_id'],'status':'approved','recorded_at':'2026-07-31T23:45:00+09:00','approved_at':'2026-07-31T23:55:00+09:00',**change}
 p['maintenance_history_summary']['work_orders']=[_history_record(raw,source_prefix='closed-loop://work-order')]
 payload=build_tool_selected_agent_review_summary_prompt_payload(packet=p,baseline_summary=compose_deterministic_agent_review_summary(p))
 h=payload['summary_context']['maintenance_history'];assert not h['work_orders'] and h['reference_history']
 assert 'approved' not in json.dumps(h['reference_history'])
 assert not payload['decision_facts']['work_orders']
 assert briefing_issues({'summary':'현재 작업 요청은 승인된 상태입니다.','role_summaries':[]},payload['decision_facts'])
 assert not briefing_issues({'summary':'제공된 기록에서 승인 여부는 확인되지 않습니다.','role_summaries':[]},payload['decision_facts'])

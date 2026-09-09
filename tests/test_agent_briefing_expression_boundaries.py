import pytest
from app.operations.agent_briefing_review import briefing_issues
from app.operations.agent_review_summary_provider import _editable_prose_review_issues

FACTS={'data_quality_hold':True,'inspection_results':[],'work_orders':[],'operation_context':{}}

def test_hold_allows_future_review_purpose_without_claiming_current_impact():
    assert not briefing_issues({'summary':'관측값을 보강한 뒤 생산 영향을 재판단할 수 있도록 자료를 확보해야 합니다.'},FACTS)

@pytest.mark.parametrize('field',['title','summary','quote'])
def test_hold_still_rejects_current_certainty_in_every_prose_surface(field):
    text='생산 영향은 확정할 수 있습니다.'
    p={'role_summaries':[{'role':'process_manager','quote':text}]} if field=='quote' else {field:text}
    assert briefing_issues(p,FACTS)

@pytest.mark.parametrize('field',['title','summary','quote'])
@pytest.mark.parametrize('text',['점검 outcome 기록','예상 정지 60 min'])
def test_internal_terms_are_checked_in_all_editable_prose(field,text):
    p={'role_summaries':[{'role':'process_manager','quote':text}]} if field=='quote' else {field:text}
    assert _editable_prose_review_issues(p)


def test_purpose_clause_does_not_hide_an_independent_current_certainty_claim():
    assert briefing_issues({'summary':'생산 영향을 재판단할 수 있도록 자료를 확보합니다. 예상 손실은 확정할 수 있습니다.'},FACTS)

@pytest.mark.parametrize('case',['GS-002','GS-007'])
def test_both_prompt_paths_share_expression_policy_without_mutating_facts(case):
    import json
    from pathlib import Path
    from copy import deepcopy
    from app.operations.agent_review_summary import compose_deterministic_agent_review_summary
    from app.operations.agent_review_summary_provider import build_agent_review_summary_prompt_payload,build_tool_selected_agent_review_summary_prompt_payload
    packet=json.loads((Path(__file__).parents[1]/f'tests/fixtures/agent_review_packets/{case}.json').read_text())
    original=deepcopy(packet);baseline=compose_deterministic_agent_review_summary(packet)
    a=build_agent_review_summary_prompt_payload(packet=packet,baseline_summary=baseline)
    b=build_tool_selected_agent_review_summary_prompt_payload(packet=packet,baseline_summary=baseline)
    assert a['expression_policy']==b['expression_policy']
    assert packet==original
    assert a['expression_policy']['decision_owner'].startswith('human')
    assert a['expression_policy']['display_units']['N·m·min']=='뉴턴미터·분'
    if case=='GS-007':assert a['expression_policy']['production_claim'].startswith('unconfirmed')


def test_conditional_planning_assumption_is_not_an_internal_code():
    assert not _editable_prose_review_issues({'summary':'정지 60분 가정의 예상 손실이며 확정 실적이 아닙니다.'})

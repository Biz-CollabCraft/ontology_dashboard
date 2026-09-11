import json
from pathlib import Path

import pytest

from app.operations.agent_review_summary import compose_deterministic_agent_review_summary, validate_agent_review_summary_contract, validated_agent_review_summary
from app.operations.agent_review_summary_provider import build_agent_review_summary_prompt_payload, build_tool_selected_agent_review_summary_prompt_payload

ROOT = Path(__file__).resolve().parents[1]

def packet_for(case):
    return json.loads((ROOT / f'tests/fixtures/agent_review_packets/{case}.json').read_text())

@pytest.mark.parametrize('builder', [build_agent_review_summary_prompt_payload, build_tool_selected_agent_review_summary_prompt_payload])
@pytest.mark.parametrize('case', ['GS-001', 'GS-002', 'GS-003', 'GS-004', 'GS-005', 'GS-006', 'GS-007', 'GS-008'])
def test_prompt_preserves_hold_condition_and_zero_quantity(builder, case):
    packet = packet_for(case)
    baseline = compose_deterministic_agent_review_summary(packet)
    # The evaluation path deliberately withholds baseline prose.
    payload = builder(packet=packet, baseline_summary={'role_summaries': []})
    assert payload['summary_context']['confidence_label'] == baseline['confidence_label']
    if baseline['confidence_label'] == 'data_quality_hold':
        assert payload['summary_context']['operation_context'] == {
            'production_impact': None,
            'estimated_downtime_minutes': None,
            'estimated_lost_units': None,
            'status': 'unconfirmed_due_to_data_quality',
        }
    else:
        assert payload['summary_context']['operation_context']['estimated_lost_units'] == packet['operation_context_summary']['estimated_lost_units']

@pytest.mark.parametrize('surface', ['title', 'summary', 'process_engineer', 'maintenance_technician', 'process_manager'])
@pytest.mark.parametrize('text', ['25건의 손실 유닛이 추정됩니다.', '예상 손실 유닛 수는 25건입니다.', '예상 손실 수량은 25개입니다.', '추정 물량 손실은 25건입니다.'])
def test_zero_loss_packet_rejects_wrong_quantity_in_any_editable_prose(text, surface):
    packet = packet_for('GS-001')
    candidate = compose_deterministic_agent_review_summary(packet)
    candidate['mode'] = 'llm'
    if surface in {'title', 'summary'}:
        candidate[surface] = text
    else:
        next(r for r in candidate['role_summaries'] if r['role'] == surface)['quote'] = text
    errors = validate_agent_review_summary_contract(candidate, packet=packet)
    assert any(e.startswith('prose_lost_units_mismatch:') for e in errors)
    result, _ = validated_agent_review_summary(packet=packet, candidate=candidate)
    assert result['mode'] == 'deterministic_fallback'

@pytest.mark.parametrize('text', ['25개 부품 재고를 확인하세요.', '예상 손실 유닛 수는 0건입니다.'])
def test_loss_validation_does_not_confuse_inventory_with_production_loss(text):
    packet = packet_for('GS-001')
    candidate = compose_deterministic_agent_review_summary(packet)
    candidate.update(mode='llm', summary=text)
    assert not any(e.startswith('prose_lost_units_mismatch:') for e in validate_agent_review_summary_contract(candidate, packet=packet))

def test_manager_expected_quantity_cannot_match_suffix_of_wrong_number():
    packet = packet_for('GS-002')
    candidate = compose_deterministic_agent_review_summary(packet)
    manager = next(r for r in candidate['role_summaries'] if r['role'] == 'process_manager')
    manager['quote'] = '생산 영향이 중간 수준입니다. 예상 손실 유닛 수는 125건입니다. 점검 승인 여부를 검토하세요.'
    errors = validate_agent_review_summary_contract(candidate, packet=packet)
    assert any(e.startswith('prose_lost_units_mismatch:') for e in errors)


@pytest.mark.parametrize('builder', [build_agent_review_summary_prompt_payload, build_tool_selected_agent_review_summary_prompt_payload])
def test_prompt_preserves_unlimited_selected_evidence(builder):
    packet = packet_for('GS-004')
    packet['evidence_context'] = {
        'selection_policy_version': 'operational-evidence-selection-v0.1',
        'decision_as_of': '2026-09-02T01:00:00+00:00',
        'selected_candidate_count': 1,
        'full_candidate_count': 1,
        'selected_basis': [
            {
                'candidate_id': 'fact:maintenance-readiness-context-demo-v1#/concurrent_work_checks/0',
                'candidate_type': 'fact',
                'source_ref': 'maintenance-readiness-context-demo-v1#/concurrent_work_checks/0',
                'domain': 'maintenance_readiness',
                'fact_type': 'concurrent_work_checks',
                'value_summary': 'concurrent_work_checks: check_id=CWCHK-001',
                'freshness_state': 'fresh',
                'required_for_boundary': True,
            }
        ],
    }

    payload = builder(
        packet=packet,
        baseline_summary=compose_deterministic_agent_review_summary(packet),
    )
    evidence = payload['summary_context']['selected_evidence']

    assert evidence['selected_candidate_count'] == 1
    assert evidence['full_candidate_count'] == 1
    assert evidence['selected_basis'][0]['fact_type'] == 'concurrent_work_checks'


@pytest.mark.parametrize('old_version', ['agent-review-summary-prompt-v1.8-demo-impact-boundary', 'agent-review-summary-prompt-v1.9-production-grounding', 'agent-review-summary-prompt-v1.9-three-role-briefing'])
def test_prompt_version_separates_old_materialized_summaries(monkeypatch, old_version):
    from app.operations import agent_review_summary_materialization as materialization
    kwargs = dict(packet=packet_for('GS-001'), project_id='test', history_window='30d', provider=None)
    current_key = materialization.summary_key(materialization.summary_key_payload(**kwargs))
    monkeypatch.setattr(materialization, 'AGENT_REVIEW_SUMMARY_PROMPT_VERSION', old_version)
    old_key = materialization.summary_key(materialization.summary_key_payload(**kwargs))
    assert current_key != old_key

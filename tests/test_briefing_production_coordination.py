from copy import deepcopy
from app.operations.agent_review_packet import _closed_loop_record
from app.operations.agent_briefing_context import briefing_activities
from app.operations.agent_briefing_review import decision_facts, build_decision_flow, _has_execution_record, briefing_issues


def activity(status='confirmed', at='2026-09-08T06:51:39+00:00'):
    return _closed_loop_record({
        'activity_id': status, 'activity_type': 'inspection.coordination.' + status,
        'equipment_id': 'CNC-1', 'event_id': 'FILE#1', 'work_order_id': 'WO-1', 'created_at': at,
        'payload': {'request_id': 'R-1', 'work_order_id': 'WO-1', 'status': status,
                    'requested_at': '2026-09-08T06:51:00+00:00', 'responded_at': at,
                    'responded_by_name': '생산 관리자',
                    'request': {'downtime_minutes': 60, 'work_summary': '점검 후 정비'},
                    'response': {'decision': status, 'scheduled_window': '저녁시간 30분만', 'production_response': '일정 준수'}}
    }, source_prefix='closed-loop://activity')


def packet(*activities):
    return {'asset_id': 'CNC-1', 'snapshot_basis': {'event_id': 'FILE#1', 'observed_at': '2026-09-08T10:50:43+00:00'},
            'maintenance_history_summary': {'activities': list(activities)}, 'source_refs': []}


def test_response_preserved_and_latest_state_shared():
    p = packet(activity('pending', '2026-09-08T06:51:00+00:00'), activity())
    facts = decision_facts(p)
    c = facts['production_coordination'][0]['production_coordination']
    assert len(facts['production_coordination']) == 1
    assert c['status'] == 'confirmed'
    assert c['request']['downtime_minutes'] == 60
    assert c['response']['scheduled_window'] == '저녁시간 30분만'
    assert c['response']['production_response'] == '일정 준수'
    assert build_decision_flow(p)['current_stage'] == 'production_approved_pending_start'
    assert not _has_execution_record(p)


def test_future_and_other_equipment_not_current_approval():
    wrong = activity()
    wrong['owner_record_provenance']['equipment_id'] = 'CNC-2'
    p = packet(wrong, activity('confirmed', '2026-09-09T06:51:39+00:00'))
    assert decision_facts(p)['production_coordination'] == []
    assert len(decision_facts(p)['excluded_records']) == 2
    assert not _has_execution_record(p)


def test_late_approval_not_lost_after_routine_activity_limit():
    approval = activity()
    items = [{'activity_type': 'routine', 'record_id': str(i)} for i in range(8)] + [approval]
    assert approval in briefing_activities(items)


def test_execution_status_not_approval_pending():
    p = packet(activity())
    order = _closed_loop_record({'work_order_id': 'WO-1', 'equipment_id': 'CNC-1', 'event_id': 'FILE#1',
                                'status': 'in_progress', 'created_at': '2026-09-08T07:00:00+00:00'},
                               source_prefix='closed-loop://work-order')
    result = deepcopy(order)
    result.update(record_id='IR-1', outcome='maintenance_recommended')
    p['maintenance_history_summary'].update(work_orders=[order], inspection_results=[result])
    assert build_decision_flow(p)['current_stage'] == 'maintenance_in_progress'
    assert _has_execution_record(p)


def test_new_request_supersedes_previous_confirmation():
    new = activity('pending', '2026-09-08T08:00:00+00:00')
    new['production_coordination']['request_id'] = 'R-2'
    p = packet(activity(), new)
    assert build_decision_flow(p)['current_stage'] == 'production_approval_pending'


def test_schedule_formatting_does_not_reject_same_recorded_window():
    facts = decision_facts(packet(activity()))
    candidate = {'role_summaries': [{'role': role, 'quote': '승인 일정은 **저녁시간**, **30분만**입니다.'}
                                  for role in ('maintenance_technician', 'process_manager')]}
    assert not briefing_issues(candidate, facts)
    candidate['role_summaries'][0]['quote'] = '승인과 저녁시간 30분 작업 일정이 확정되었습니다.'
    assert not briefing_issues(candidate, facts)
    candidate['role_summaries'][0]['quote'] = '승인 일정은 저녁시간 60분만입니다.'
    assert briefing_issues(candidate, facts)

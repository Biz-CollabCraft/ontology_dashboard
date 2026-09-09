"""Read-only, event/as-of scoped facts and bounded prose checks.

Checks are deliberately narrow; passing them is not semantic or human validation.
"""
from datetime import datetime
import re
from app.operations.agent_briefing_context import record_context


def decision_facts(packet):
    history=packet.get('maintenance_history_summary') or {}
    facts={'inspection_results':[], 'work_orders':[], 'excluded_records':[],
           'boundary':'Only supplied records are known. Missing records do not establish that an action never occurred.'}
    for key in ('inspection_results','work_orders'):
        groups={}
        for raw in history.get(key) or []:
            r=record_context(raw,packet=packet);scope=r['record_context']
            if scope.get('temporal_relation')!='at_or_before_basis' or scope.get('asset_scope')!='matches_asset' or scope.get('event_relation')!='matches_event':
                facts['excluded_records'].append({'record_id':r.get('record_id'),'scope':scope});continue
            groups.setdefault(r.get('record_id') or r.get('source_ref'),[]).append(r)
        for revisions in groups.values():
            def at(r):
                provenance=r.get('owner_record_provenance') or {}
                times=[r.get('recorded_at')]+[provenance.get(k) for k in ('created_at','updated_at','approved_at','started_at','completed_at','recorded_at')]
                return max(datetime.fromisoformat(t.replace('Z','+00:00')) for t in times if t)
            latest=max(at(r) for r in revisions);current=[r for r in revisions if at(r)==latest]
            if len({r.get('status') for r in current})>1:
                facts['excluded_records'].append({'record_id':current[0].get('record_id'),'reason':'conflicting_latest_status'});continue
            r=current[-1];facts[key].append({k:r[k] for k in ('record_id','status','outcome','findings','measurements','recorded_at','source_ref','owner_record_provenance','summary','production_coordination') if k in r})
    facts['data_quality_hold'] = (packet.get('review_draft') or {}).get('priority_label') == '미확정'
    facts['operation_context'] = ({'production_impact': None, 'estimated_downtime_minutes': None,
                                   'estimated_lost_units': None, 'status': 'unconfirmed_due_to_data_quality'}
                                  if facts['data_quality_hold'] else packet.get('operation_context_summary') or {})
    facts['citation_catalog'] = {str(i): ref for i, ref in enumerate(dict.fromkeys(packet.get('source_refs') or []), 1)}
    return facts


def briefing_issues(candidate,facts):
    def plain(value):return re.sub(r'\[\[ref:[^\]\n]+\]\]', '', value).replace('**','')
    roles={r.get('role'):plain(r.get('quote','')) for r in candidate.get('role_summaries',[]) if isinstance(r,dict)}
    prose=' '.join([candidate.get('summary',''),*roles.values()]);issues=[]
    if facts.get('data_quality_hold'):
        for sentence in re.split(r'[.!?\n]', prose):
            if re.search(r'생산\s*영향|손실', sentence) and re.search(r'(?:확정|확인|산정|판단)할\s*수\s*있|확정(?:됐|되었|됩니다|입니다)', sentence):
                issues.append('데이터 품질 보류에서는 생산 영향과 예상 손실을 확정할 수 있다고 쓰지 마세요. 미확인 상태를 유지하세요.')
    if not facts['work_orders'] and facts.get('excluded_records'):
        for sentence in re.split(r'[.!?\n]', prose):
            # Explicit missing-record statements are not claims of approval.
            checked = re.sub(r'승인(?:된| 상태)[^,;]{0,30}(?:없|미확인|확인되지)', '', sentence)
            if re.search(r'승인(?:된|되었|됐|되었습니다)|상태(?:는|가)?\s*승인|승인\s*상태(?:입니다|로)', checked):
                issues.append('현재 설비·이벤트·기준 시각에 맞는 승인 기록이 없습니다. 제외된 기록을 현재 승인으로 설명하지 마세요.')
    if not facts['inspection_results'] and not facts['work_orders']:return issues
    technician=roles.get('maintenance_technician','');manager=roles.get('process_manager','')
    for r in facts['inspection_results']:
        # Narrow domain anchors, never claimed to validate arbitrary free-text findings.
        findings=' '.join(r.get('findings') or [])
        for term in ('편심','누유','균열'):
            if term in findings and term not in technician:issues.append('보전 설명에 기록된 발견 사항 '+term+'을 반영하세요.')
        if r.get('outcome')=='maintenance_recommended' and 'maintenance_recommended' not in technician and not re.search(r'정비.{0,8}(권고|권장)',technician):
            issues.append('점검 결과 maintenance_recommended를 정비 권고로 설명하세요. 확정 실행으로 바꾸지 마세요.')
    for order in facts['work_orders']:
        coordination = order.get('production_coordination')
        if not coordination:
            continue
        minutes = (coordination.get('request') or {}).get('downtime_minutes')
        for role in ('maintenance_technician', 'process_manager'):
            quote = roles.get(role, '')
            if coordination.get('status') == 'pending' and not re.search(r'승인.{0,12}(대기|기다)', quote):
                issues.append('생산 관리자 승인 대기 상태를 보전·생산 브리핑에 명시하세요. 작업지시 approved는 점검 접수이며 생산 승인이 아닙니다.')
            if coordination.get('status') == 'pending' and re.search(r'승인 시각|승인 완료|승인되었습니다', quote):
                issues.append('생산 승인 대기 중입니다. 점검 접수 시각을 생산 승인 시각으로 표현하지 마세요.')
            if minutes is not None and str(minutes) not in quote:
                issues.append(f'보전·생산 브리핑에 요청 정지 {minutes}분을 반영하세요.')
    if '승인 여부는 검토 중' in prose:issues.append('기록에 없는 승인 검토 진행 상태를 단정하지 마세요.')
    orders=facts['work_orders']
    if len(orders)==1:
        r=orders[0];status=r.get('status');provenance=r.get('owner_record_provenance') or {}
        if status=='approved' and not r.get('production_coordination'):
            for role,quote in (('보전',technician),('생산관리',manager)):
                # A negated re-approval step does not contradict a recorded approval.
                checked = re.sub(r'승인\s*여부(?:\s*재확인|를\s*다시\s*확인하는)?(?:\s*단계)?(?:가|이)?\s*아니라', '', quote)
                if '승인' not in quote or re.search(r'승인\s*(여부|검토|대기)',checked):
                    issues.append(role+' 설명은 해당 작업요청의 기록 상태가 승인임을 반영하고 착수 준비와 일정 검토로 연결하세요.')
            timestamp=provenance.get('approved_at')
            if timestamp:
                hh,mm=timestamp[11:16].split(':')
                if timestamp[11:16] not in technician and not re.search(rf'{int(hh)}시\s*{int(mm)}분',technician):
                    issues.append('보전 설명에 기록된 승인 시각 '+timestamp+'을 표시하세요.')
        elif status=='requested':
            if '요청' not in technician:issues.append('보전 설명에 작업요청이 등록된 상태를 반영하세요.')
            if re.search(r'승인(되었|됐|됨|되었습니다)|승인 상태(?:입니다|로 기록|로 확인)' ,prose):issues.append('요청됨 기록을 승인 상태로 바꾸지 마세요.')
    for role,quote in (('보전',technician),('생산관리',manager)):
        if not re.search(r'검토|조율|일정|준비|요청하|결정',quote):issues.append(role+' 설명에 현재 단계에서 필요한 다음 판단을 제시하세요.')
    impact=facts['operation_context'];minutes=impact.get('estimated_downtime_minutes')
    if minutes is not None and (str(minutes) not in manager or not re.search(r'가정|경우|예상 정지',manager)):
        issues.append('생산관리 설명에 정지 '+str(minutes)+'분 가정이라는 손실 추정 조건을 함께 표시하세요.')
    return issues


def build_decision_flow(packet, facts=None):
    """Build a deterministic decision-flow skeleton for prose generation.

    The flow is not generated prose. It orders already-grounded facts so the LLM
    can write a connected briefing instead of re-inventing the relationship order.
    """
    facts = facts or decision_facts(packet)
    flow = {
        'flow_version': 'decision-flow-v1',
        'current_stage': _current_stage(packet, facts),
        'stage_label': _stage_label(_current_stage(packet, facts)),
        'primary_chain': [],
        'role_focus': {
            'process_engineer': ['risk_factors', 'inspection_targets', 'sop_thresholds', 'inspection_findings', 'remaining_measurements'],
            'maintenance_technician': ['inspection_result', 'work_order_status', 'execution_records', 'parts_and_readiness'],
            'process_manager': ['work_order_status', 'downtime_plan', 'lost_units_plan', 'production_quality_delivery_gaps'],
        },
        'composition_rule': 'Follow the primary_chain order: current state, causal relation, recorded owner state, blocking gaps, next decision.',
    }
    for step in (
        _risk_factor_step(packet),
        _inspection_target_step(packet),
        _inspection_result_step(facts),
        _work_order_step(facts),
        _execution_state_step(packet),
        _readiness_gap_step(packet),
        _production_decision_step(facts),
    ):
        if step:
            flow['primary_chain'].append(step)
    return flow


def _current_stage(packet, facts):
    if facts.get('data_quality_hold'):
        return 'data_quality_hold_pending_observation'
    orders = facts.get('work_orders') or []
    if any((order.get('production_coordination') or {}).get('status') == 'pending' for order in orders):
        return 'inspection_completed_pending_production_approval'
    if any(order.get('status') == 'approved' for order in orders):
        if not _has_execution_record(packet):
            return 'approved_work_order_pending_start'
        return 'approved_work_order_in_execution_review'
    if any(order.get('status') == 'requested' for order in orders):
        return 'work_order_registered_pending_approval'
    if facts.get('inspection_results'):
        return 'inspection_result_recorded_pending_work_order_review'
    return 'risk_review_pending_inspection'


def _stage_label(stage):
    return {
        'inspection_completed_pending_production_approval': '점검 완료 · 생산 관리자 승인 대기',
        'data_quality_hold_pending_observation': '데이터 보강 후 위험·생산 영향 재판단',
        'approved_work_order_pending_start': '승인된 작업요청의 착수 조건 판단',
        'approved_work_order_in_execution_review': '작업 실행 기록과 후속 일정 판단',
        'work_order_registered_pending_approval': '등록된 작업요청의 승인·일정 판단',
        'inspection_result_recorded_pending_work_order_review': '점검 결과 기반 조치 범위 판단',
        'risk_review_pending_inspection': '위험 신호 기반 점검 필요성 판단',
    }.get(stage, '현재 증거 기반 다음 판단')


def _risk_factor_step(packet):
    factors = [
        f for f in (packet.get('model_expression_context') or {}).get('top_factors') or []
        if isinstance(f, dict) and f.get('direction') == 'risk_up'
    ]
    if not factors:
        return None
    facts = []
    for factor in factors[:3]:
        label = factor.get('display_name') or factor.get('feature')
        value = factor.get('value')
        unit = factor.get('unit')
        if label and value is not None:
            facts.append(_fact(str(label), value=value, unit=unit, source_ref=factor.get('source_ref')))
    exceeded = _sop_exceedance_facts(packet)
    return {'step': 'risk_factors_exceed_sop' if exceeded else 'risk_factors_identified', 'facts': [*facts, *exceeded]}


def _sop_exceedance_facts(packet):
    factors = {
        f.get('feature'): f for f in (packet.get('model_expression_context') or {}).get('top_factors') or []
        if isinstance(f, dict)
    }
    product_variant = (packet.get('operation_context_summary') or {}).get('product_variant')
    results = []
    for guidance in packet.get('sop_guidance') or []:
        for criterion in ((guidance.get('sensor_judgment') or {}).get('criteria') or []):
            feature = criterion.get('factor_key')
            factor = factors.get(feature)
            threshold = criterion.get('threshold') or {}
            if not factor or criterion.get('operator') != '>=':
                continue
            limit = threshold.get('value')
            if threshold.get('kind') == 'product_type_map':
                limit = (threshold.get('values') or {}).get(product_variant)
            value = factor.get('value')
            if value is None or limit is None or value < limit:
                continue
            label = factor.get('display_name') or feature
            unit = factor.get('unit') or threshold.get('unit')
            results.append(_fact(f'{label} SOP 기준 이상', value=value, threshold=limit, unit=unit, source_ref=factor.get('source_ref')))
    unique = []
    seen = set()
    for item in results:
        key = (item.get('label'), item.get('source_ref'))
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique


def _inspection_target_step(packet):
    targets = []
    for target in packet.get('inspection_targets') or []:
        if isinstance(target, dict):
            targets.append(_fact(target.get('location_label') or target.get('component_label'), source_ref=target.get('source_ref') or target.get('location_source_ref')))
    if not targets:
        return None
    return {'step': 'inspection_targets_identified', 'facts': targets[:4]}


def _inspection_result_step(facts):
    results = []
    for item in facts.get('inspection_results') or []:
        finding = ', '.join(item.get('findings') or []) or item.get('summary') or item.get('outcome') or item.get('status')
        results.append(_fact(finding, status=item.get('outcome') or item.get('status'), recorded_at=item.get('recorded_at'), source_ref=item.get('source_ref')))
    if not results:
        return None
    return {'step': 'inspection_result_recorded', 'facts': results}


def _work_order_step(facts):
    coordinated = [item for item in facts.get('work_orders') or [] if item.get('production_coordination')]
    if coordinated:
        return {'step': 'production_approval_review', 'facts': coordinated, 'boundary': '작업지시 approved는 점검 접수 상태이며 생산 승인은 production_coordination.status로 판단한다.'}
    orders = []
    for item in facts.get('work_orders') or []:
        provenance = item.get('owner_record_provenance') or {}
        orders.append(_fact(item.get('summary') or item.get('record_id'), status=item.get('status'), recorded_at=item.get('recorded_at'), approved_at=provenance.get('approved_at'), source_ref=item.get('source_ref')))
    if not orders:
        return None
    if any(order.get('status') == 'approved' for order in orders):
        step = 'work_order_approved'
    elif any(order.get('status') == 'requested' for order in orders):
        step = 'work_order_registered'
    else:
        step = 'work_order_recorded'
    return {'step': step, 'facts': orders}


def _execution_state_step(packet):
    history = packet.get('maintenance_history_summary') or {}
    has_start_or_completion = _has_execution_record(packet)
    if has_start_or_completion:
        facts = []
        for key in ('maintenance_actions', 'maintenance_events', 'activities'):
            for item in history.get(key) or []:
                if isinstance(item, dict):
                    facts.append(_fact(item.get('summary') or item.get('record_id') or key, status=item.get('status'), source_ref=item.get('source_ref')))
        return {'step': 'execution_recorded', 'facts': facts[:4]}
    if history.get('work_orders') or history.get('inspection_results'):
        return {'step': 'execution_not_confirmed', 'facts': [_fact('시작 기록 없음'), _fact('완료 기록 없음')]}
    return None


def _has_execution_record(packet):
    history = packet.get('maintenance_history_summary') or {}
    if any(order.get('production_coordination') for order in history.get('work_orders') or []):
        if history.get('maintenance_actions') or history.get('maintenance_events'):
            return True
        return any(item.get('activity_type') in ('maintenance.execution.start', 'maintenance.execution.complete')
                   for item in history.get('activities') or [])
    if any(history.get(key) for key in ('maintenance_actions', 'maintenance_events', 'activities')):
        return True
    for order in history.get('work_orders') or []:
        provenance = order.get('owner_record_provenance') or {}
        if provenance.get('started_at') or provenance.get('completed_at') or order.get('status') in ('started', 'completed', 'done'):
            return True
    return False


def _readiness_gap_step(packet):
    context = packet.get('evidence_context') or {}
    refs = {str(item.get('source_ref') or '') for item in context.get('selected_basis') or [] if isinstance(item, dict)}
    domains = {str(item.get('domain') or '') for item in context.get('selected_basis') or [] if isinstance(item, dict)}
    facts = []
    if 'context:maintenance_readiness' in refs or 'relation-gap:maintenance_readiness' in refs or 'maintenance_readiness' in domains:
        facts.extend([_fact('실제 재고 수량 미확인', source_ref='context:maintenance_readiness'), _fact('작업 가능 시간 미확인', source_ref='context:maintenance_readiness')])
    if not facts:
        return None
    return {'step': 'readiness_gap', 'facts': facts}


def _production_decision_step(facts):
    context = facts.get('operation_context') or {}
    if context.get('status') == 'unconfirmed_due_to_data_quality':
        return {'step': 'production_impact_unconfirmed', 'facts': [_fact('생산 영향 미확인'), _fact('예상 손실 미확인')]}
    items = []
    if context.get('production_impact') is not None:
        items.append(_fact('생산 영향', value=context.get('production_impact'), source_ref=context.get('source_ref') or 'operation-context://production-planning-context-v1'))
    if context.get('estimated_downtime_minutes') is not None:
        items.append(_fact('정지 시간 가정', value=context.get('estimated_downtime_minutes'), unit='분', source_ref=context.get('source_ref') or 'operation-context://production-planning-context-v1'))
    if context.get('estimated_lost_units') is not None:
        items.append(_fact('예상 손실', value=context.get('estimated_lost_units'), unit='개', source_ref=context.get('source_ref') or 'operation-context://production-planning-context-v1'))
    if items:
        return {'step': 'production_decision', 'facts': items}
    return None


def _fact(label, **values):
    return {'label': label, **{k: v for k, v in values.items() if v not in (None, '', [])}}

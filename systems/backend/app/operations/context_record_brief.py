"""Read-only record availability for grounded AI explanations."""
FIELDS = {
    'production': ('생산 주문·재공', ('production_orders', 'wip')),
    'maintenance_readiness': ('정비 인력·재고·일정', ('inventory_snapshots', 'maintenance_windows', 'technician_candidates')),
    'quality_delivery': ('품질·납기', ('delivery_commitments', 'quality_lots')),
    'impact_policy': ('생산량 산정 기준', ('primary_capacity_units',)),
    'planning': ('생산 운영 계획', ('production_plan',)),
}

def record_limitations(read):
    notes = ['자료 문서 조회 성공은 정비 착수 가능·품질 통과·생산 회복을 뜻하지 않습니다.']
    for domain, (label, keys) in FIELDS.items():
        context = read.get('domains', {}).get(domain, {}).get('context', {})
        status = context.get('status')
        if status != 'available':
            notes.append(f'{label}: 선택 시점 기록 미등록 또는 조회 불가 ({status}).')
        elif not any(context.get('data', {}).get(key) for key in keys):
            notes.append(f'{label}: 문서만 조회됐으며 세부 기록은 미등록입니다.')
        elif not all(context.get('data', {}).get(key) for key in keys):
            notes.append(f'{label}: 일부 기록만 등록되어 있습니다.')
    if any('MISSING_WIP' in o.get('reason_codes', []) for o in read.get('production_impact', {}).get('options', [])):
        notes.append('생산 차질 계산 불가: 연결된 재공 기록이 없습니다. 압축기는 공급 대상·생산량 연결을 확인해야 하며 손실 0으로 해석하지 않습니다.')
    production=read.get('domains',{}).get('production',{}).get('context',{}).get('data',{})
    basis=production.get('supply_basis')
    if basis:
        targets=sorted({e['to_asset_id'] for e in basis['edges']})
        notes.append('공급 대상 설비: '+', '.join(targets))
        notes.extend(basis['assumptions'])
        for option in read.get('production_impact',{}).get('options',[]):
            if option.get('state')=='calculated':
                notes.append(f"조건부 생산 비교 {option['option']}: 대상 재공 {option['required_units']}개, 잔여 차질 {option['remaining_exposed_units']}개. 실제 손실이나 운전 허가는 아닙니다.")
    return notes

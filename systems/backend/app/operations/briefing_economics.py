"""Shared UI reference costs, never authoritative production facts."""
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
BASIS = ROOT / 'systems/frontend/src/features/operations/overview/production-economic-basis.v1.json'

def reference_economics(packet, basis_path=None):
    from app.operations.agent_briefing_review import decision_facts
    asset = packet.get('asset_id', '')
    kind = 'CNC' if asset.startswith('CNC-') else 'CMP' if asset.startswith('CMP-') else None
    if packet.get('project_id') != 'manufacturing-demo-project' or not kind:
        return {'status': 'not_applicable'}
    try:
        raw = Path(basis_path or BASIS).read_bytes()
        basis = json.loads(raw)
        profile = basis['profiles'][kind]
        params = {p['key']: p['value'] for p in basis['parameters']}
    except (OSError, ValueError, KeyError) as exc:
        return {'status': 'unavailable', 'reason': type(exc).__name__}
    coords = decision_facts(packet)['production_coordination']
    if len(coords) > 1:
        return {'status': 'unavailable', 'reason': 'ambiguous_work_order_scope'}
    request = (coords[0]['production_coordination'].get('request') or {}) if coords else {}
    minutes = request.get('downtime_minutes')
    default = minutes is None
    minutes = profile['default_stop_minutes'] if default else minutes
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or not math.isfinite(minutes) or minutes < 0:
        return {'status': 'unavailable', 'reason': 'invalid_requested_stop_minutes'}
    units = params['units_per_hour'] * profile['affected_cnc']
    rnd = lambda n: math.floor(n + .5)
    sha = hashlib.sha256(raw).hexdigest()
    metric = lambda value, unit: {'value': value, 'unit': unit}
    return {'status': 'illustrative_not_site_quote', 'asset_id': asset,
        'version': basis['version'], 'source_sha256': sha,
        'source_ref': 'reference-economics://' + basis['version'] + '/' + sha,
        'metrics': {
            'stop_minutes': {**metric(minutes, '분'), 'basis': 'default_assumption' if default else 'recorded_request'},
            'hourly_production_cost': metric(rnd(units * params['unit_production_cost']), '원/시간'),
            'stop_production_cost': metric(rnd(rnd(units * params['unit_production_cost']) * minutes / 60), '원'),
            'hourly_contribution': metric(rnd(units * params['unit_contribution']), '원/시간'),
            'opportunity_exposure': metric(rnd(units * params['unit_contribution'] * minutes / 60), '원'),
            'reference_lost_units': metric(math.ceil(units * minutes / 60), '개'),
            'daily_capacity': metric(math.floor(units * params['daily_hours']), '개/일'),
            'conditional_maintenance_labor': metric(rnd(params['labor_hourly'] * profile['labor_minutes'] / 60), '원'),
            'conditional_replacement_parts': metric(profile['parts_cost'], '원')},
        'parameters': basis['parameters'], 'profile': profile, 'sources': basis['sources'],
        'limitations': basis['limitations'], 'request_source_ref': coords[0].get('source_ref') if coords else None,
        'formulas': {'hourly_production_cost': 'units_per_hour * affected_cnc * unit_production_cost',
                     'stop_production_cost': 'hourly_production_cost * stop_minutes / 60',
                     'opportunity_exposure': 'units_per_hour * affected_cnc * unit_contribution * stop_minutes / 60'},
        'interpretation': '가정 기반 참고 산정. 확정 손실·매출·영업이익 아님. 생산원가와 기회손실을 합산하지 않음. 정비·교체비는 해당 작업을 수행하는 조건부 예시. 승인 시간이나 실제 작업을 변경하지 않음.'}

def attach_economics(packet):
    economics = reference_economics(packet)
    packet['reference_economics'] = economics
    if economics.get('source_ref'):
        packet['source_refs'].append(economics['source_ref'])
    return packet

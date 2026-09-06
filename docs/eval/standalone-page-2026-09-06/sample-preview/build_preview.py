"""Build and validate a synthetic manifest; never connects to the running database."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from app.infra.db.migrations import migrate
from app.infra.db.operational_context_repository import ContextSnapshot, OperationalContextRepository
from app.operations.operational_context_contract import OperationalRequestIdentity

OUT = Path(__file__).resolve().parent
BUNDLE = 'DEMO-S03L03-20260829-v1'
ASOF = '2026-08-29T14:00:00+00:00'
START = '2026-08-28T15:00:00+00:00'
END = '2026-08-29T15:00:00+00:00'
CLASS = 'synthetic_demo_context'
LIMITS = ['시연용 가정이며 실제 생산·재고·인력·승인 사실이 아닙니다.', '정비 완료·위험 등급·예측 결과는 변경하지 않습니다.']
rows = []
assets = json.loads((OUT / 'target-assets.json').read_text())
for asset in assets:
    aid = asset['asset_id']; cnc = aid.startswith('CNC-')
    ref = f'synthetic_demo:{BUNDLE}:{aid}'
    relation = dict(relationship_state='assumed_demo', source_refs=[ref])
    order, wip, lot = [f'{BUNDLE}:{aid}:{x}' for x in ('order', 'wip', 'lot')]
    production = dict(source_classification=CLASS, production_orders=[], wip=[], alternative_resources=[], limitations=LIMITS)
    quality = dict(source_classification=CLASS, asset_id=aid, quality_lots=[], delivery_commitments=[], limitations=LIMITS)
    if cnc:
        production['production_orders'] = [dict(order_id=order, product_id='DEMO-PART-A', product_label='시연 부품 A', required_quantity=200, completed_quantity=150, due_at=END, priority=1, operation_id='DEMO-CUTTING', assigned_asset_id=aid, **relation)]
        production['wip'] = [dict(wip_id=wip, order_id=order, operation_id='DEMO-CUTTING', asset_id=aid, quantity=50, lot_ids=[lot], status='in_process', **relation)]
        quality['quality_lots'] = [dict(lot_id=lot, wip_id=wip, order_id=order, quantity=50, quality_state='unverified', release_required=True, **relation)]
        quality['delivery_commitments'] = [dict(delivery_id=f'{order}:delivery', order_id=order, committed_quantity=200, due_at=END, priority=1, **relation)]
    else:
        production['limitations'] = LIMITS + ['압축기와 절삭기 생산의 의존관계가 미등록이므로 생산 손실량을 계산하지 않습니다.']
    payloads = {
        'production': production,
        'maintenance_readiness': dict(source_classification=CLASS, asset_id=aid, action_code='DEMO_INSPECTION', required_skill_codes=['DEMO_MECHANICAL_INSPECTION'], maintenance_windows=[], part_requirements=[], inventory_snapshots=[], technician_candidates=[], limitations=LIMITS + ['실제 Action Candidate와 연결되지 않은 시연 항목입니다. 착수·승인 근거로 사용할 수 없습니다.']),
        'quality_delivery': quality,
        'impact_policy': dict(policy_version=BUNDLE, primary_capacity_units={'stop_now':0,'continue_operation':50} if cnc else {}, alternative_capacity_allowed={'stop_now':False,'continue_operation':False} if cnc else {}, source_refs=[ref]),
    }
    if cnc:
        version = f'{BUNDLE}:{aid}:planning'
        payloads['planning'] = dict(context_id=version, source_type='capacity_model', temporal_scope=dict(snapshot_id=version, timezone='Asia/Seoul', valid_from=START, valid_to=END, generated_at=ASOF), production_plan=dict(plan_id=f'{order}:plan', plan_date='2026-08-29', planned_units=200, product_mix=[dict(variant='시연 부품 A', share=1, planned_units=200)]), capacity_model=dict(active_asset_count=1, planned_operating_hours=8, oee=1, standard_cycle_minutes_per_unit=2.4, asset_units_per_hour=25, daily_capacity_units=200, basis='시연 가정: 시간당 25개 × 8시간 = 200개. 실제 가동 실적이 아닙니다.'), event_impact=dict(event_id=asset['event_id'], equipment_id=aid, line='S03-L03', product_variant='시연 부품 A', screen_priority='monitor', impact_status='estimated', estimated_lost_units=25, basis=dict(estimated_downtime_minutes=60, asset_units_per_hour=25, formula='시연 정지시간 60분 ÷ 60 × 시간당 25개 = 25개. 실제 예측 정지시간이 아닙니다.')), limitations=LIMITS + ['설비별 계획 200개; 절삭기 4대 합계 800개. 압축기를 합산하지 않습니다.', '정지 1시간의 계획 영향 25개와 잔여 재공 50개의 선택지 노출량은 서로 다른 지표입니다.'])
    for domain, payload in payloads.items():
        rows.append(ContextSnapshot.model_validate(dict(organization_id='org-ontology-demo', project_id='manufacturing-demo-project', workspace_id='manufacturing-demo', asset_id=aid, owner_domain=domain, source_version=f'{BUNDLE}:{aid}:{domain}', source_ref=ref, source_classification=CLASS, source_updated_at=ASOF, valid_from=START, valid_to=END, evidence_snapshot_id=asset['event_id'], payload=payload)))
(OUT / 'manifest.json').write_text(json.dumps([r.model_dump(mode='json') for r in rows], ensure_ascii=False, indent=2)+'\n')
with TemporaryDirectory(prefix='ontology-sample-preview-') as temp:
    db = str(Path(temp)/'preview.sqlite'); migrate(db)
    repo = OperationalContextRepository(db)
    first = repo.import_snapshots(rows); repeat = repo.import_snapshots(rows)
    assert first == {'inserted': 24, 'unchanged': 0}
    assert repeat == {'inserted': 0, 'unchanged': 24}
    previews = []
    for asset in assets:
        identity = OperationalRequestIdentity(organization_id='org-ontology-demo', project_id='manufacturing-demo-project', workspace_id='manufacturing-demo', asset_id=asset['asset_id'], evidence_snapshot_id=asset['event_id'], decision_as_of=ASOF)
        view = repo.read_view(identity=identity, retrieved_at=identity.decision_as_of, risk_status=asset['status'])
        options = {o.option.value: o for o in view.production_impact.options}
        if asset['asset_id'].startswith('CNC-'):
            assert options['stop_now'].remaining_exposed_units == 50
            assert options['continue_operation'].remaining_exposed_units == 0
            assert 'MAINTENANCE_BLOCKED' in options['planned_maintenance'].reason_codes
        else:
            assert all('MISSING_WIP' in o.reason_codes for o in options.values())
        previews.append(view.model_dump(mode='json'))
    result = dict(validation_environment='temporary_sqlite_context_preview_only', live_database_applied=False, bundle=BUNDLE, first_import=first, repeat_import=repeat, views=previews)
    (OUT/'expected-context.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(dict(validated=len(rows), first_import=first, repeat_import=repeat, live_database_applied=False)))

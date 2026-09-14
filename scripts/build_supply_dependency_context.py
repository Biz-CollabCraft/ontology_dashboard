"""Build immutable demo scenarios from stored air-supply edges and scoped CNC records.
Writes a manifest only. Apply with the existing import_operational_context CLI.
"""
import argparse, copy, json, os
from datetime import datetime
from pathlib import Path
from app.infra.db.connection import tenant_connection
from app.infra.db.operational_context_repository import ContextSnapshot, OperationalContextRepository
from app.operations.operational_context_contract import OperationalRequestIdentity

SUPPLY_DEPENDENCY_VERSION = 'SUPPLY-DEPENDENCY-v3'


def build(repository, identity, dataset, edges):
    targets=sorted({r['to_asset_id'] for r in edges})
    if not targets or len(targets)!=len(edges):
        raise ValueError('missing or duplicate supply edges')
    production={'source_classification':'synthetic_demo_context','production_orders':[], 'wip':[], 'alternative_resources':[]}
    quality={'source_classification':'synthetic_demo_context','asset_id':identity.asset_id,'quality_lots':[], 'delivery_commitments':[]}
    refs=[]; inputs=[]
    for target in targets:
        if not target.startswith('CNC-'): raise ValueError('supply target must be CNC')
        # Canonical result events use the asset identity and the same observation time.
        prefix, selected, timestamp=identity.evidence_snapshot_id.split('#',2)
        if prefix!='RESULT' or selected!=identity.asset_id: raise ValueError('unsupported snapshot identity')
        target_identity=identity.model_copy(update={'asset_id':target,'evidence_snapshot_id':f'RESULT#{target}#{timestamp}'})
        view=repository.read_view(identity=target_identity,retrieved_at=identity.decision_as_of,risk_status='normal')
        for domain in ('production','quality_delivery'):
            item=view.domains[domain]
            if item.context.status!='available' or item.provenance.bound_evidence_snapshot_id!=target_identity.evidence_snapshot_id:
                raise ValueError(f'{target}: missing exact bound {domain}')
            inputs.append({'asset_id':target,'domain':domain,**item.provenance.model_dump(mode='json')})
            refs.extend(item.context.source_refs)
        p=view.domains['production'].context.data
        if not p.get('wip') or not p.get('production_orders'): raise ValueError(f'{target}: missing production records')
        if any(w['asset_id']!=target for w in p['wip']) or any(o['assigned_asset_id']!=target for o in p['production_orders']): raise ValueError('cross-asset records')
        for key in ('production_orders','wip'):production[key].extend(copy.deepcopy(p[key]))
        for key in ('quality_lots','delivery_commitments'):quality[key].extend(copy.deepcopy(view.domains['quality_delivery'].context.data.get(key,[])))
    for key,idkey in [('production_orders','order_id'),('wip','wip_id')]:
        ids=[r[idkey] for r in production[key]]
        if len(ids)!=len(set(ids)): raise ValueError('shared records require explicit deduplication')
    edge_refs=[f"pm_asset_relations:{dataset}:{identity.asset_id}:SUPPLIES_AIR_TO:{r['to_asset_id']}:{r['source_sha256']}" for r in edges]
    ref='synthetic_demo:'+SUPPLY_DEPENDENCY_VERSION+':'+identity.asset_id
    refs=list(dict.fromkeys([ref,*edge_refs,*refs]))
    units=sum(r['quantity'] for r in production['wip'])
    half_units=units//2
    limits=['비교 구간: 08.29 23:00~08.30 01:00 (한국시간), 2시간, 예비 공급 없음.',
        '생산능력: 절삭기 4대 × 시간당 25개 = 시간당 100개.',
        '즉시 정지: 비교 구간 2시간 정지, 처리 가능 0개.',
        f'계획 정비: 23:30~00:30 60분 정지, 나머지 1시간 처리 가능 {half_units}개.',
        f'운전 지속: 2시간 처리 가능 {units}개. 운전 허가나 고장 미발생 보장이 아닌 비교 조건.',
        '공급 대상 절삭기의 재공만 비교하며 실제 손실·승인·착수 기록과 구분합니다.',
        '공급 대상: '+', '.join(targets)]
    production['limitations']=limits;quality['limitations']=limits
    production['supply_basis']={'dataset_version_id':dataset,'evidence_snapshot_id':identity.evidence_snapshot_id,'edges':[dict(from_asset_id=identity.asset_id,to_asset_id=e['to_asset_id'],relation_type='SUPPLIES_AIR_TO',source_sha256=e['source_sha256']) for e in edges],'assumptions':limits}
    for key in ('production_orders','wip'):
        for record in production[key]:record['source_refs']=list(dict.fromkeys([*record['source_refs'],*edge_refs,ref]))
    policy={'policy_version':SUPPLY_DEPENDENCY_VERSION,'primary_capacity_units':{'stop_now':0,'planned_maintenance':half_units,'continue_operation':units},'alternative_capacity_allowed':{'stop_now':False,'planned_maintenance':False,'continue_operation':False},'source_refs':refs}
    valid_from=max(datetime.fromisoformat(r['valid_from'].replace('Z','+00:00')) for r in inputs)
    valid_to=min(datetime.fromisoformat(r['valid_to'].replace('Z','+00:00')) for r in inputs)
    readiness={'source_classification':'synthetic_demo_context','asset_id':identity.asset_id,'action_code':'air_compressor_inspection','required_skill_codes':['air-compressor-maintenance'],'technician_candidates':[{'technician_id':'tech-air-01','skill_codes':['air-compressor-maintenance'],'available_from':'2026-08-29T14:30:00+00:00','available_to':'2026-08-29T16:00:00+00:00','assignment_state':'candidate','relationship_state':'assumed_demo','source_refs':[ref]},{'technician_id':'tech-air-02','skill_codes':['air-compressor-maintenance'],'available_from':'2026-08-29T15:00:00+00:00','available_to':'2026-08-29T17:00:00+00:00','assignment_state':'candidate','relationship_state':'assumed_demo','source_refs':[ref]}],'maintenance_windows':[{'window_id':'MW:'+identity.asset_id+':20260829T1430Z','asset_id':identity.asset_id,'available_from':'2026-08-29T14:30:00+00:00','available_to':'2026-08-29T15:30:00+00:00','expected_duration_minutes':60,'approval_required':True,'active_work_order_conflict':False,'relationship_state':'assumed_demo','source_refs':[ref]}],'part_requirements':[],'inventory_snapshots':[],'limitations':['정비 착수 조건은 후보 시간·인력·작업지시 승인 확인용이며 승인 기록이 아닙니다.']}
    rows=[ContextSnapshot(organization_id=identity.organization_id,project_id=identity.project_id,workspace_id=identity.workspace_id,asset_id=identity.asset_id,owner_domain=d,schema_version=2 if d=='production' else 1,source_version=SUPPLY_DEPENDENCY_VERSION+':'+identity.asset_id+':'+d,source_ref=ref,source_classification='synthetic_demo_context',source_updated_at=identity.decision_as_of,valid_from=valid_from,valid_to=valid_to,evidence_snapshot_id=identity.evidence_snapshot_id,payload=p) for d,p in [('production',production),('quality_delivery',quality),('impact_policy',policy),('maintenance_readiness',readiness)]]
    return rows,{'identity':identity.model_dump(mode='json'),'dataset_version_id':dataset,'edges':edges,'inputs':inputs,'assumptions':limits,'required_units':units}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    scope=p.add_mutually_exclusive_group(required=True)
    scope.add_argument('--asset-id')
    scope.add_argument('--all-compressors',action='store_true')
    p.add_argument('--snapshot');p.add_argument('--as-of',required=True);p.add_argument('--dataset',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();db=os.environ['ONTOLOGY_DASHBOARD_DATABASE_URL']
    timestamp = (a.snapshot or '').split('#',2)[2] if a.snapshot else '2026-08-29T23:00:00+09:00'
    asset_ids=[a.asset_id]
    if a.all_compressors:
        with tenant_connection(db,'org-ontology-demo',project_id='manufacturing-demo-project') as c:
            rows=c.execute('SELECT DISTINCT from_asset_id FROM pm_asset_relations WHERE organization_id=%s AND project_id=%s AND workspace_id=%s AND dataset_version_id=%s AND relation_type=%s ORDER BY from_asset_id',('org-ontology-demo','manufacturing-demo-project','manufacturing-demo',a.dataset,'SUPPLIES_AIR_TO')).fetchall()
        asset_ids=[r['from_asset_id'] for r in rows]
    all_rows=[];proofs=[]
    for asset_id in asset_ids:
        snapshot=a.snapshot or f'RESULT#{asset_id}#{timestamp}'
        identity=OperationalRequestIdentity(organization_id='org-ontology-demo',project_id='manufacturing-demo-project',workspace_id='manufacturing-demo',asset_id=asset_id,evidence_snapshot_id=snapshot,decision_as_of=a.as_of)
        with tenant_connection(db,identity.organization_id,project_id=identity.project_id) as c:
            edges=c.execute('SELECT to_asset_id,source_sha256 FROM pm_asset_relations WHERE organization_id=%s AND project_id=%s AND workspace_id=%s AND dataset_version_id=%s AND from_asset_id=%s AND relation_type=%s ORDER BY to_asset_id',(identity.organization_id,identity.project_id,identity.workspace_id,a.dataset,asset_id,'SUPPLIES_AIR_TO')).fetchall()
        rows,proof=build(OperationalContextRepository(db),identity,a.dataset,[dict(r) for r in edges])
        all_rows.extend(rows);proofs.append(proof)
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'manifest.json').write_text(json.dumps([r.model_dump(mode='json') for r in all_rows],ensure_ascii=False,indent=2))
    (a.output/'provenance.json').write_text(json.dumps({'scenarios':proofs},ensure_ascii=False,indent=2))
    print(json.dumps({'compressors':len(asset_ids),'validated':len(all_rows),'required_units':sum(p['required_units'] for p in proofs),'applied':False}))
if __name__=='__main__':main()

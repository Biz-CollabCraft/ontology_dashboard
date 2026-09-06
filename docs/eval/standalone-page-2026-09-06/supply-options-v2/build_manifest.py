import json,copy
from pathlib import Path
from app.infra.db.operational_context_repository import ContextSnapshot
old=Path('docs/eval/standalone-page-2026-09-06/supply-dependency/manifest.json');rows=json.loads(old.read_text());a=rows[0]['asset_id'];ref='synthetic_demo:SUPPLY-DEPENDENCY-v2:'+a
conditions=['비교 구간: 08.29 23:00~08.30 01:00 (한국시간), 2시간, 예비 공급 없음.', '생산능력: 절삭기 4대 × 시간당 25개 = 시간당 100개.', '즉시 정지: 비교 구간 2시간 정지, 처리 가능 0개.', '계획 정비: 23:30~00:30 60분 정지, 나머지 1시간 처리 가능 100개.', '운전 지속: 2시간 처리 가능 200개. 운전 허가나 고장 미발생 보장이 아닌 비교 조건.', '공급 대상 절삭기의 재공만 비교하며 실제 손실·승인·착수 기록과 구분합니다.']
for r in rows:
 r['source_version']=r['source_version'].replace('v1','v2');r['source_ref']=ref
 if r['owner_domain']=='production':r['payload']['supply_basis']['assumptions']=conditions;r['payload']['limitations']=conditions
 if r['owner_domain']=='impact_policy':r['payload'].update(policy_version='SUPPLY-DEPENDENCY-v2',primary_capacity_units={'stop_now':0,'planned_maintenance':100,'continue_operation':200},alternative_capacity_allowed={k:False for k in ['stop_now','planned_maintenance','continue_operation']});r['payload']['source_refs'].append(ref)
readiness=copy.deepcopy(rows[0]);readiness.update(owner_domain='maintenance_readiness',schema_id='operational-context.maintenance_readiness',schema_version=1,source_version='SUPPLY-DEPENDENCY-v2:'+a+':maintenance_readiness')
relationship={'relationship_state':'assumed_demo','source_refs':[ref]}
readiness['payload']={'source_classification':'synthetic_demo_context','asset_id':a,'action_code':'DEMO_INSPECTION','required_skill_codes':['DEMO_MECHANICAL_INSPECTION'],'maintenance_windows':[{'window_id':'SUPPLY-v2:window:'+a,'asset_id':a,'available_from':'2026-08-29T14:30:00+00:00','available_to':'2026-08-29T15:30:00+00:00','expected_duration_minutes':60,'approval_required':True,'active_work_order_conflict':False,**relationship}],'part_requirements':[],'inventory_snapshots':[],'technician_candidates':[{'technician_id':'SUPPLY-v2:technician-candidate','skill_codes':['DEMO_MECHANICAL_INSPECTION'],'available_from':'2026-08-29T14:00:00+00:00','available_to':'2026-08-29T16:00:00+00:00','assignment_state':'candidate_only',**relationship}],'limitations':conditions+['점검 비교에는 교체 부품을 요구하지 않는 가정. 실제 교체 작업에는 별도 부품·Action Candidate 검증이 필요합니다.','인력은 후보일 뿐 배정되지 않았으며 승인 대기·미착수 상태입니다.']}
rows.append(readiness)
rows=[ContextSnapshot.model_validate(r).model_dump(mode='json') for r in rows]
out=Path('docs/eval/standalone-page-2026-09-06/supply-options-v2');(out/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print('validated',len(rows))

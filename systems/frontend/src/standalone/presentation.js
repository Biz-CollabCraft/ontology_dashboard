import {mapRoleData} from './roleData.js';
import {roleContext} from './roleContext.js';
import {contextStatus} from './contextStatus.js';
import {briefPresentation} from './aiBrief.js';
import {equipmentName,locationName,supplyTargetLabel,selectedBrief,briefContext,eventBrief} from './fieldBrief.js';
// Display-only mappings. API identifiers, command payloads and permissions stay unchanged.
const names = {
  process_engineer:'설비 엔지니어',maintenance_technician:'보전 담당자',process_manager:'생산관리자',
  compressor:'공기압축기',pump:'펌프',motor:'전동기',cnc:'CNC 공작기계',conveyor:'컨베이어',
  failure_risk:'고장 위험 감지',review_shutdown:'설비 정지 검토',monitor:'추이 관찰',
  normal:'정상',attention:'주의',warning:'위험',critical:'긴급 확인',hold:'판단 보류',
  requested:'접수 대기',accepted:'접수됨',approved:'승인됨',in_progress:'작업 중',completed:'작업 완료',planned:'계획됨',
  rejected:'반려됨',cancelled:'취소됨',available:'확인됨',stale:'갱신 필요',missing:'자료 없음',unknown:'미확인',
  not_connected:'자료 미연결',failed:'조회 실패',good:'유효한 관측',partial:'일부 구간만 조회됨',empty:'관측 이력 없음',
  production:'생산 계획',planning:'생산 운영 자료',maintenance_readiness:'정비 준비 상태',quality_delivery:'품질·납기',impact_policy:'생산 영향 산정 기준',
  stop_now:'즉시 정지',planned_maintenance:'계획 정비',continue_operation:'운전 지속',
  tool_replacement:'공구 교체',cooling_system_repair:'냉각 계통 정비',inspection:'점검',maintenance:'정비',
  no_action_required:'조치 불필요',maintenance_recommended:'정비 검토 필요',data_check_required:'추가 확인 필요',
  '시연 부품 A':'부품 A','Production Reliability':'생산 설비 관리','Smart Factory A':'스마트 공장 A','model unit':'모델 변환값',
};
export const label = value => names[value] || value || '미확인';
export const number = value => typeof value==='number'&&Number.isFinite(value)?new Intl.NumberFormat('ko-KR',{maximumFractionDigits:3}).format(value):'미산정';
export function date(value){if(!value)return '시각 미확인';const d=new Date(value);return Number.isNaN(d.getTime())?'시각 미확인':new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);}
export function feature(value){
 const key=String(value||'').replaceAll(' ','_').replace(/^factor:/,'');
 const sensors={air_temperature_k:'주변 온도',process_temperature_k:'공정 온도',relative_vibration_z:'상대 진동',rotational_speed_rpm:'회전속도',tool_wear_min:'공구 사용시간',torque_nm:'토크',rotation_raw:'회전 신호',voltage_raw:'전압',pressure_raw:'압력',vibration_raw:'진동',temperature:'온도',torque:'토크',tool_wear:'공구 마모'};
 const prefix=Object.keys(sensors).find(k=>key===k||key.startsWith(k+'_'));
 if(!prefix)return /[가-힣]/.test(value||'')?value:'추가 분석 지표';
 const suffix=key.slice(prefix.length).replace(/^_/,'');
 if(!suffix)return sensors[prefix];
 if(suffix==='current')return sensors[prefix]+' · 기준 시점';
 if(suffix==='abs_current')return sensors[prefix]+' · 기준 시점 절댓값';
 const match=suffix.match(/^(\d+)h_(abs_mean|mean|std|min|max|max_abs|change)$/);
 return sensors[prefix]+(match?` · ${match[1]}시간 `+{mean:'평균',abs_mean:'절댓값 평균',std:'변동폭(표준편차)',min:'최솟값',max:'최댓값',max_abs:'절댓값 최댓값',change:'변화량'}[match[2]]:' · 분석값');
}
export function message(value){
 const s=String(value||'');
 if(s.includes('No matching scoped operational snapshot'))return '선택한 설비·시점에 맞는 생산 운영 자료가 없습니다.';
 if(s.includes('equipment_history'))return '설비 정비 이력이 연결되지 않았습니다.';
 if(s.includes('maintenance_context.last_maintenance_days_ago'))return '선택 시점 이전의 정비 완료 기록이 없습니다.';
 if(s.includes('maintenance_context.similar_events_30d'))return '최근 30일 유사 사례 집계가 연결되지 않았습니다.';
 if(s.includes('maintenance_context.open_work_order_exists'))return '선택 시점의 미완료 작업지시 상태를 확인할 수 없습니다.';
 if(s.includes('maintenance_context'))return '일부 정비 참고 항목이 연결되지 않았습니다.';
 if(s.includes('operation_context.load_level'))return '설비 부하 등급이 등록되지 않았습니다.';
 if(s.includes('operation_context.runtime_hours_7d'))return '최근 7일 가동시간 집계가 연결되지 않았습니다.';
 if(s.includes('operation_context.production_impact'))return '생산 영향 등급이 등록되지 않았습니다.';
 if(s.includes('operation_context'))return '일부 생산 운영 항목이 연결되지 않았습니다.';
 if(s.includes('review_priority'))return '점검 우선순위를 정할 근거가 부족합니다.';
 if(s.includes('404'))return '선택한 판단 근거에 해당하는 자료를 찾지 못했습니다. (404)';
 if(s.includes('403'))return '이 작업을 수행할 권한이 없습니다. (403)';
 if(s.includes('409'))return '작업 상태 또는 판단 기준이 변경됐습니다. 다시 조회하세요. (409)';
 if(s.includes('503'))return '조회 서비스를 사용할 수 없습니다. 잠시 후 다시 조회하세요. (503)';
 if(s.includes('CONTEXT_')||s.includes('MISSING_'))return '선택 시점의 필수 자료가 없거나 유효하지 않습니다.';
 return text(s);
}
export function text(value){
 let s=String(value??'');
 for(const [key,val] of Object.entries(names).sort((a,b)=>b[0].length-a[0].length))s=s.replace(new RegExp('(?<![A-Za-z0-9_-])'+key.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?![A-Za-z0-9_-])','gi'),val);
 return s.replaceAll('Backend','서버').replaceAll('WorkOrder','작업지시').replaceAll('event·snapshot','이벤트·판단 기준').replaceAll('snapshot','판단 기준').replaceAll('as-of','기준 시점').replaceAll('SOP','표준작업서').replaceAll('published · 최신 설비 판단','저장된 설비 판단').replaceAll('서버 역할 계약 미지원','현재 계정으로 요청할 수 없음').replaceAll('서버 역할·요청 권한 계약 필요','점검 요청 권한 확인 필요').replaceAll('서버 허용 액션 없음','실행 가능한 작업 없음').replaceAll('계약 미지원','기능 미연결').replaceAll('계약 확인 필요','자료 연결 확인 필요').replaceAll('Unassigned · policy review','미배정 · 담당자 확인 필요');
}
function displayTree(value){
 if(typeof value==='string')return text(value);
 if(Array.isArray(value))return value.map(displayTree);
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,displayTree(v)]));
 return value;
}
function row(label,value){return {label,value,color:'#0F1E33'};}
export function mapPresentation(values,state){
 const v={...values},d=state.detail,ctx=state.contextRead;
 // The manufacturing catalog encodes the line in S and the cell in L.
 // Regroup existing tiles so selection handlers and server identities are preserved.
 const grouped=new Map();
 for(const oldLine of v.lines||[])for(const oldCell of oldLine.cells||[])for(const tile of oldCell.assets||[]){
   const match=tile.no?.match(/^[^-]+-S(\d+)-L(\d+)-/);
   const lineKey=match?String(Number(match[1])):oldLine.name;
   const cellKey=match?String(Number(match[2])):oldCell.name;
   if(!grouped.has(lineKey))grouped.set(lineKey,{name:match?`${lineKey}라인`:oldLine.name,cells:new Map()});
   const line=grouped.get(lineKey);
   if(!line.cells.has(cellKey))line.cells.set(cellKey,{name:match?`${cellKey}셀`:oldCell.name,assets:[]});
   line.cells.get(cellKey).assets.push({...tile,code:equipmentName({assetId:tile.no},true).replace(/ (\d+호)$/,tile.metaShow==='block'?' $1':'\n$1'),tileH:tile.metaShow==='block'?'52px':'44px',title:`${locationName({assetId:tile.no})} · ${equipmentName({assetId:tile.no})} · ${tile.no}`});
 }
 const numeric=(a,b)=>a[0].localeCompare(b[0],'ko',{numeric:true});
 v.lines=[...grouped].sort(numeric).map(([,line])=>{
   const cells=[...line.cells].sort(numeric).map(([,cell])=>({...cell,assets:cell.assets.sort((a,b)=>a.no.localeCompare(b.no,'en',{numeric:true}))}));
   return {...line,cells,summary:`${cells.length}셀 · 설비 ${cells.reduce((sum,c)=>sum+c.assets.length,0)}대`};
 });
 const tileCount=v.lines.reduce((sum,line)=>sum+line.cells.reduce((n,c)=>n+c.assets.length,0),0);
 v.siteLabel=`${state.model?.context?.workspaceName||'작업장 확인 필요'} · ${v.lines.length}개 라인 · ${v.lines.reduce((n,l)=>n+l.cells.length,0)}개 셀 · 설비 ${tileCount}대`;

 if(!d)return displayTree(v);
 const oc=d.operationContext||{},planning=ctx?.domains?.planning?.context;
 const plan=planning?.status==='available'?planning.data.production_plan:null;
 const currentPlan=plan?{plannedUnits:plan.planned_units,productMix:plan.product_mix?.map(x=>({variant:x.variant,plannedUnits:x.planned_units})),planDate:plan.plan_date}:oc.productionPlan;
 const limits=[...new Set((oc.limitations||[]).map(message))];
 const impact=oc.eventImpact;
 const syntheticPlanning=ctx?.domains?.planning?.provenance?.source_classification==='synthetic_demo_context';
 const impactNote=syntheticPlanning?'정지시간 가정 기준 · 실제 손실과 별도':'서버 산정값 · 실제 손실과 별도';
 for(const key of ['shiftEvents','planEvents'])v[key]=(v[key]||[]).map(e=>({...e,time:date(e.time)}));
 v.nowLabel=date(state.model?.context.observedAt)+' (한국시간)';v.selObservedAt=date(d.snapshotBasis?.observedAt);
 v.signalAgeLabel=date(d.snapshotBasis?.observedAt);v.chartTicks=(d.riskSeries||[]).filter((_,i,a)=>i===0||i===a.length-1).map(x=>({label:date(x.observedAt)}));
 v.sourceLabel=state.error||state.workflowError?message(state.error||state.workflowError):state.notice||`${text(state.model?.context.sourceStatus)}${state.model?.context.stale?' · 오래된 관측 자료':''}${state.contextError?' · 생산 자료 조회 실패':''}`;
 const warningResolved=raw=>{
   const s=String(raw||'');
   if(s.includes('operation_context.production_impact'))return ctx?.domains?.production?.context?.status==='available'&&ctx?.production_impact?.options?.some(o=>o.state==='calculated');
   if(s.includes('maintenance_context.similar_events_30d'))return state.factoryRecords?.status==='available'&&state.factoryRecords.similar_events_30d!=null;
   return false;
 };
 v.selSourceNote=[...new Set([...(state.model?.context.warnings||[]),...(d.warnings||[])].filter(w=>!warningResolved(w)).map(message))].join(' · ')||'저장된 판단 근거 기준';v.staleLine=v.selSourceNote;
 v.selRisk=d.event.failureProbability==null?'미산정':d.event.failureProbability.toFixed(2);v.selGrade=label(d.event.status);
 v.priorityHead=label(d.event.predictedFailureType);v.selName=text(v.selName);v.machineKind=label(v.machineKind);
 const productionImpactText=oc.productionImpact==null?(state.selectedAssetId?.startsWith('CMP-')?'공급 대상·생산 영향 미등록':'생산 영향 등급 미등록'):{none:'없음',low:'낮음',medium:'보통',high:'높음'}[oc.productionImpact]||'미확인';
 v.context=[row('생산 영향',syntheticPlanning&&oc.productionImpact!=null?`${productionImpactText} · 데모 가정 기준`:productionImpactText),row('예상 정지시간',d.event.estimatedDowntimeMinutes==null?'미산정':number(d.event.estimatedDowntimeMinutes)+'분'),row('최근 정비 이후',d.maintenanceContext?.lastMaintenanceDaysAgo==null?'이력 없음':number(d.maintenanceContext.lastMaintenanceDaysAgo)+'일'),row('30일 유사 사례',number(d.maintenanceContext?.similarEvents30d)),row('미완료 작업지시',d.maintenanceContext?.openWorkOrderExists==null?'미확인':d.maintenanceContext.openWorkOrderExists?'있음':'없음'),row('기준 시각',date(d.snapshotBasis?.observedAt))];
 const production=ctx?.domains?.production?.context;
 if(production?.status==='available'){
   const orders=production.data.production_orders||[],wip=production.data.wip||[];
   if(orders.length)v.context.push(row('선택 설비 주문 수량',number(orders.reduce((sum,o)=>sum+o.required_quantity,0))+'개'),row('주문 기준 완료 수량',number(orders.reduce((sum,o)=>sum+o.completed_quantity,0))+'개 · 교대 실적과 별도'));
   if(wip.length)v.context.push(row('재공 수량',number(wip.reduce((sum,o)=>sum+o.quantity,0))+'개'));
 }
 const supply=production?.status==='available'?production.data.supply_basis:null;
 if(supply){
   const targets=[...new Set(supply.edges.map(e=>e.to_asset_id))];
   v.context.push(row('공기 공급 대상',supplyTargetLabel(targets)));
   v.context.push(row('생산 영향 계산 조건',supply.assumptions.filter(x=>x.startsWith('비교 구간:')||x.startsWith('생산능력:')).join(' ')||'예비 공급 없음 · 공급 대상 재공 기준'));
   const stop=ctx?.production_impact?.options?.find(o=>o.option==='stop_now'&&o.state==='calculated');
   if(stop){v.context[0]=row('생산 영향 · 공급 대상 기준',`즉시 정지 시 재공 ${number(stop.remaining_exposed_units)}개 노출 (조건부)`);if(v.isShift)v.kpis[2]={label:'공급 대상 재공 차질 예상',value:number(stop.remaining_exposed_units),unit:'개',note:'즉시 정지 · 예비 공급 없음'};}
 }
 v.opCtx=v.context.slice(0,3);
 for(const [domain,item] of Object.entries(ctx?.domains||{})){v.context.push(row(label(domain)+' · 자료 상태',contextStatus(domain,item)));}

 if(currentPlan?.plannedUnits!=null){
   if(v.isPlan)v.kpis=[{label:'선택 시점 계획 수량',value:number(currentPlan.plannedUnits),unit:'개',note:currentPlan.planDate||'생산 계획 근거 기준'},{label:'선택 설비 예상 생산 차질',value:number(impact?.estimatedLostUnits),unit:'개',note:impactNote},{label:'계획 품목',value:number(currentPlan.productMix?.length),unit:'종',note:'생산 계획에 등록된 품목'}];
   v.shifts=[{name:'일간 생산 계획',hours:currentPlan.planDate||'선택 시점',mark:'계획 조회',markFg:'#4A5C74',markBg:'#EEF3F8',border:'1px solid #DDE6F0',plan:number(currentPlan.plannedUnits),made:'실적 자료 없음',loss:number(impact?.estimatedLostUnits),madePct:'0%',lossPct:'0%',lossColor:'#4A5C74'}];
   v.variants=(currentPlan.productMix||[]).map(x=>({name:x.variant,plan:number(x.plannedUnits),price:'미산정',due:'납기 자료 없음',dueColor:'#4A5C74',dueBg:'#EEF3F8',short:'미산정',money:'미산정',moveable:'확인 필요',shortColor:'#4A5C74',okPct:'0%',shortPct:'0%',recoveryLabel:'생산 대응 확인',onRecovery:values.onOpenSelected}));
 }
 v.planHeadNote=currentPlan?'일간 계획 기준 · 교대 실적은 별도 확인':limits[0]||'선택 시점의 생산 계획이 없습니다.';
 if(v.isShift&&impact?.estimatedLostUnits!=null)v.kpis[2]={label:'선택 설비 예상 생산 차질',value:number(impact.estimatedLostUnits),unit:'개',note:impactNote};
 for(const option of ctx?.production_impact?.options||[])v.context.push(row(label(option.option)+' · 잔여 차질',option.state==='calculated'?number(option.remaining_exposed_units)+'개 (조건부 예상)':option.reason_codes?.includes('MAINTENANCE_BLOCKED')?'정비 착수 조건 미충족':option.reason_codes?.includes('MISSING_WIP')?state.selectedAssetId?.startsWith('CMP-')?'압축기 공급 대상·생산량 연결 필요':'선택 설비 재공 기록 미등록':'계산 조건 미등록'));
 // Plot observed history only. Scaling is visual; it does not create a risk or a normal range.
 const sensors=[...(d.sensors||[])].sort((a,b)=>(b.historyPoints?.length||0)-(a.historyPoints?.length||0)).slice(0,4);
 v.signals=sensors.map(s=>{
   const points=(s.historyPoints||[]).filter(x=>Number.isFinite(x.value));const last=points.at(-1);const nums=points.map(x=>x.value);const min=Math.min(...nums),max=Math.max(...nums);
   return {label:/[가-힣]/.test(s.label||'')?s.label:feature(s.id||s.label),value:number(s.value??last?.value),unit:s.unit?label(s.unit):'단위 미제공',state:points.length?`최근 관측 ${date(last.observedAt)} · ${points.length}건`:'관측 이력 없음',stateColor:'#4A5C74',arrow:'',bandBottom:'0%',bandHeight:'0%',bars:points.map(x=>({h:(max===min?50:5+90*(x.value-min)/(max-min))+'%',bg:'#527795',op:1}))};
 });
 const factors=d.topFactors||[],max=Math.max(...factors.map(f=>Math.abs(f.contribution||0)),1);
 v.reasons=factors.map((f,i)=>({no:String(i+1).padStart(2,'0'),parts:[{text:feature(f.feature||f.label)+' '+number(f.value)+' '+label(f.unit||'단위 미제공'),weight:600,color:'#0F1E33'}]}));
 v.detailSignals=factors.map((f,i)=>({rank:i+1,label:feature(f.feature||f.label),value:number(f.value),unit:label(f.unit||'단위 미제공'),baseline:'비교 기준 미제공',contribPct:Math.abs(f.contribution||0)/max*100+'%',contribVal:number(f.contribution),direction:f.direction==='risk_up'?'위험 증가 방향':f.direction==='risk_down'?'위험 감소 방향':'방향 미확인',color:'#527795',state:'위험 판단 요인',stateColor:'#4A5C74',quality:'모델 분석값',qualityColor:'#4A5C74',window:'선택 시점 기준',spark:''}));
 v.signalQualityNote='';
 const work=state.lineage?.work_orders||[],actions=state.lineage?.maintenance_actions||[];
 v.steps=[...work.map(w=>({label:w.work_type==='inspection'?'점검 작업지시':'정비 작업지시',mark:label(w.status)})),...actions.map(a=>({label:'정비 수행',mark:label(a.status)}))].map((x,i)=>({...x,no:i+1,glyph:'·',bg:'#EEF3F8',border:'1px solid #DDE6F0',fg:'#2C4159',subFg:'#566B85',weight:600}));
 v.reqQueue=v.reqQueue.map((r,i)=>({...r,age:date(work[i]?.updated_at||work[i]?.created_at),assignee:text(work[i]?.assigned_to||'미배정')}));
 v.timeline=(state.lineage?.activities||d.activity||[]).map(a=>({label:label(a.action||a.title||a.activity_type||'작업 기록'),status:label(a.status||a.detail||'저장된 기록'),when:date(a.created_at||a.createdAt||a.occurred_at),who:label(a.actor_role||a.actor||'담당자 미확인'),bg:'#EEF3F8',color:'#003C96',fg:'#4A5C74'}));
 v.gaps=[...new Set((d.warnings||[]).map(message)),...limits,...(state.contextError?[message(state.contextError)]:[])].map(reason=>({name:'자료 확인',reason,owner:'담당 부서 확인',blocks:'없는 값은 추정하지 않습니다.',state:'확인 필요',stateColor:'#4A5C74'}));
 if(state.factoryRecordsError)v.gaps.push({name:'상태·사례 집계',reason:message(state.factoryRecordsError),owner:'운영 기록',blocks:'조회 실패',state:'조회 실패',stateColor:'#B02F26'});
 v.primaryOwner=label(state.role);
 v.primaryInput=state.command?'':state.role==='process_engineer'?'현재 계정의 점검 요청 기능이 연결되지 않았습니다.':state.role==='maintenance_technician'?'현재 계정의 점검 수행 기능이 연결되지 않았습니다. 정비는 승인된 작업지시가 필요합니다.':'현재 설비에서 실행 가능한 정비 작업을 확인할 수 없습니다.';
 v.handoffBlocked=state.command?'':v.primaryInput;v.readOnlyNote=values.readOnlyNote?.startsWith('다른 역할')?values.readOnlyNote:'';
 v.flowSummary=(state.candidates||[]).map(c=>label(c.action_code)).join(' · ');
 v.machineHiddenNote=d.inspectionTargets?.length?'등록된 점검 대상 기준':'이 설비에 연결된 점검 부위·표준작업서가 없습니다.';
 v.procurementEmpty='부품 재고 정보가 연결되지 않았습니다.';
 const asset=state.model?.assets?.find(a=>a.assetId===state.selectedAssetId)||{assetId:state.selectedAssetId};
 v.selName=equipmentName(asset);v.selPlace=locationName(asset);v.curReqAsset=v.selName;
 v.reasons=selectedBrief(d,state.lineage);v.opCtx=v.context;v.context=briefContext(d,state.lineage,asset,ctx);
 v.priorityHead='';
 v.priorityLabel=d.reviewPriority?.level==='immediate'?'즉시':'근거 확인';
 for(const key of ['shiftEvents','planEvents'])v[key]=(v[key]||[]).map(e=>{const event=state.model?.events?.find(x=>x.assetId===e.assetId&&date(x.observedAt)===e.time);const a=state.model?.assets?.find(x=>x.assetId===e.assetId);return event&&a?{...e,...eventBrief(event,a,event.eventId===state.selectedEventId?d:null)}:e;});
 v.eventsSub='최근 '+Math.max(v.shiftEvents.length,v.planEvents.length)+'건';v.shiftBadge=String(v.shiftEvents.length);v.planBadge=String(v.planEvents.length);
 const records=state.factoryRecords;
 if(records?.status==='available'){
   v.selThreshold=number(records.policy.action_threshold);
   v.warnValLabel=number(records.policy.action_threshold);v.attnValLabel=number(records.policy.attention_threshold);
   v.lineWarnY=300-records.policy.action_threshold*300;v.lineAttnY=300-records.policy.attention_threshold*300;
   v.opCtx.push(row('조치 기준 적용 모델',records.policy.model_version),row('30일 사건 집계 기준','같은 설비 · 같은 고장 유형 · 기준 시각까지'));
 }
 if(v.isShift&&v.kpis?.length){v.kpis[0]={...v.kpis[0],label:'위험 확인 필요 설비',note:'위험·긴급 확인 등급'};v.kpis[1]={label:'가동 중 설비',value:records?.status==='available'?number(records.counts.running):'미확인',unit:'/ '+(records?.total||state.model?.assets?.length||0)+'대',note:records?.status==='available'?`정지 ${records.counts.stopped}대 · 정비 ${records.counts.maintenance}대 · 상태 미확인 ${records.counts.unknown}대`:state.factoryRecordsError?'상태 기록 조회 실패':'가동·정비 상태 기록이 연결되지 않았습니다.'};}
 Object.assign(v,briefPresentation(state));
 v.aiBriefVisible=true;
 if(state.aiBrief){
   v.priorityHead=(v.isPlan?state.aiBrief.role_summaries?.find(r=>r.role==='process_manager')?.quote:null)||state.aiBrief.summary;
 }else{
   v.priorityHead=state.aiError?message(state.aiError):state.aiFallback?'생성 결과 검증 실패':state.canGenerateAi?'생성 대기':'생성 권한 없음';
 }
 v.onAiSummary=e=>{e?.stopPropagation();window.dispatchEvent(new CustomEvent('factory:request',{detail:{type:'operations:ai-summary',assetId:state.selectedAssetId,eventId:state.selectedEventId}}));};
 const maintenanceWork=(state.lineage?.work_orders||[]).filter(w=>w.work_type==='maintenance');
 v.opCtx.push(row('정비 작업 상태',maintenanceWork.length?maintenanceWork.map(w=>label(w.status)).join(' · '):'정비 작업지시 없음'));
 const readiness=ctx?.domains?.maintenance_readiness?.context;
 if(readiness?.status==='available'){
   const windows=readiness.data.maintenance_windows||[];
   v.opCtx.push(row('정비 후보 시간',windows.length?windows.map(w=>`${date(w.available_from)} ~ ${date(w.available_to)} · ${number(w.expected_duration_minutes)}분`).join(' / '):'후보 시간 미등록'));
   v.opCtx.push(row('인력 후보',`후보 ${readiness.data.technician_candidates?.length||0}명`));
 }
 mapRoleData(v,state,{number,date,label});
 v.signalShow='flex';
 v.roleContext=roleContext(v);
 const result=displayTree(v);
 // Keep provenance identifiers verbatim, including case, for traceability.
 result.artifactLine=values.artifactLine;result.shaLine=values.shaLine;
 return result;
}

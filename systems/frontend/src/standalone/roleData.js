// Read-only projections of the selected, snapshot-scoped context.
export function mapRoleData(v,state,{number,date,label}) {
 const domains=state.contextRead?.domains||{};
 const available=name=>domains[name]?.context?.status==='available'?domains[name].context.data:null;
 const production=available('production'),ready=available('maintenance_readiness');
 const orders=production?.production_orders||[],wip=production?.wip||[];
 const options=state.contextRead?.production_impact?.options||[];
 const optionValue=o=>o.state==='calculated'?number(o.remaining_exposed_units)+'개':'조건 미충족';
 if(v.isPlan&&production){
  const total=orders.reduce((n,o)=>n+o.required_quantity,0),done=orders.reduce((n,o)=>n+o.completed_quantity,0);
  v.kpis=[{label:'선택 설비 주문 수량',value:number(total),unit:'개',note:'연결된 주문 기준'},{label:'주문 기준 완료 수량',value:number(done),unit:'개',note:'기준 시점 누적'},{label:'재공 수량',value:number(wip.reduce((n,w)=>n+w.quantity,0)),unit:'개',note:'연결된 재공 기준'}];
  v.planHeadNote='선택 시점 · 주문 기준';
  v.shifts=orders.map(o=>({name:label(o.product_label||o.product_id),hours:'납기 '+date(o.due_at),mark:'주문',markFg:'#4A5C74',markBg:'#EEF3F8',border:'1px solid #DDE6F0',plan:number(o.required_quantity),made:number(o.completed_quantity),loss:number(wip.filter(w=>w.order_id===o.order_id).reduce((n,w)=>n+w.quantity,0)),madePct:(o.required_quantity?Math.min(100,o.completed_quantity/o.required_quantity*100):0)+'%',lossPct:'0%',lossColor:'#4A5C74'}));
  v.variants=options.map(o=>({name:label(o.option),due:o.state==='calculated'?'조건부 예상':'조건 미충족',dueColor:'#4A5C74',dueBg:'#EEF3F8',plan:number(o.required_units),short:optionValue(o),money:number(o.primary_capacity_after_action),price:'',moveable:'',okPct:'0%',shortPct:'0%',shortColor:'#4A5C74',recoveryLabel:'근거 확인',onRecovery:v.onOpenSelected}));
 }
 if(v.isMaint){
  const windows=ready?.maintenance_windows||[],work=state.lineage?.work_orders||[];
  v.kpis=[{label:'선택 이벤트 작업지시',value:state.lineage?number(work.length):'조회 실패',unit:'건',note:'서버 저장 상태'},{label:'인력 후보',value:ready?number(ready.technician_candidates?.length||0):'자료 없음',unit:'명',note:'확정 배정 별도'},{label:'정비 후보 시간',value:ready?number(windows.length):'자료 없음',unit:'구간',note:'승인된 일정과 별도'}];
  v.windows=windows.length?windows.map(w=>({when:date(w.available_from),span:date(w.available_to)+' · '+number(w.expected_duration_minutes)+'분',line:'정비 후보',state:w.active_work_order_conflict?'작업 충돌 확인 필요':'시간 충돌 없음',color:'#4A5C74',bg:'#EEF3F8',note:w.approval_required?'작업지시 승인 필요':'승인 조건 없음'})):[{when:'정비 후보 시간',span:'미등록',line:'',state:ready?'후보 없음':'자료 없음',color:'#4A5C74',bg:'#EEF3F8',note:''}];
  v.procurementSub='선택 설비 기준';
  v.procurementEmpty=ready?(ready.part_requirements?.length?'필요 부품 '+number(ready.part_requirements.length)+'종 · 재고 근거 확인':'등록된 필요 부품 없음'):'부품 자료 없음';
  if(!work.length){v.curReqId='작업지시 없음';v.curReqState='';v.curReqWhat='선택 설비 점검 근거';v.curReqFrom='없음';v.curReqAssignee='미배정';v.reqEmpty='선택 이벤트의 작업지시 없음';}
  const target=state.detail?.inspectionTargets?.[0];
  v.curReqChecks=(target?.inspectionGuidance?.checklistDraft||[]).map((text,i)=>({no:i+1,text}));
  v.flowTitle=state.command?.label||'작업 가능 상태';v.flowSummary=state.command?'':state.workflowError||state.blockedReason;
 }
}

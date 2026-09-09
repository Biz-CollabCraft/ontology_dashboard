// Only the shared maintenance/production section is filtered; permissions are unchanged.
export function roleContext(values){
 const all=[...(values.context||[]),...(values.opCtx||[])];
 const common=['설비 종류'];
 const engineer=['마지막 정비 경과','30일 유사 사례','미종결 작업지시','공기 공급 대상'];
 const maintenance=['마지막 정비 경과','미종결 작업지시','예상 정지시간','정비 후보 시간','인력 후보','정비 작업 상태'];
 const manager=['미종결 작업지시','공기 공급 대상','생산 영향 · 공급 대상 기준','선택 설비 주문 수량','주문 기준 완료 수량','재공 수량','생산 영향 계산 조건','즉시 정지 · 잔여 차질','계획 정비 · 잔여 차질','운전 지속 · 잔여 차질','정비 후보 시간','정비 작업 상태'];
 const allowed=new Set([...common,...(values.isMaint?maintenance:values.isPlan?manager:engineer)]);
 const seen=new Set();return all.filter(r=>allowed.has(r.label)&&!seen.has(r.label)&&seen.add(r.label));
}

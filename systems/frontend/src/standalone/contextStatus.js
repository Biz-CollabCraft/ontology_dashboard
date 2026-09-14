const fields={production:['production_orders','wip'],maintenance_readiness:['inventory_snapshots','maintenance_windows','technician_candidates'],quality_delivery:['delivery_commitments','quality_lots'],impact_policy:['primary_capacity_units'],planning:['production_plan']};
export function contextStatus(domain,item){
 const c=item?.context;
 if(c?.status!=='available')return {not_connected:'선택 시점 기록 미등록',failed:'자료 조회 실패',stale:'자료 유효기간 확인 필요'}[c?.status]||'자료 확인 필요';
 const has=v=>Array.isArray(v)?v.length>0:v&&typeof v==='object'?Object.keys(v).length>0:v!=null;
 const keys=fields[domain]||[];const filled=keys.filter(k=>has(c.data?.[k])).length;
 return filled===0?'세부 기록 미등록':filled<keys.length?'일부 기록 등록':'기록 조회됨';
}

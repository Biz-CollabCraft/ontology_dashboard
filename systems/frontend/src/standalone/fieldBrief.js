// Human-facing brief assembled only from the selected ViewModel and persisted records.
import {feature, number, label, date} from './presentation.js';
export function equipmentName(asset,short=false){
 const type=asset?.assetType||asset?.asset_type||String(asset?.assetId||'').split('-')[0];
 const stem=({cnc:'절삭기',CNC:'절삭기',compressor:'공기압축기',CMP:'공기압축기',pump:'펌프',motor:'전동기'})[type]||'설비';
 const end=String(asset?.assetId||'').split('-').at(-1);const suffix=/^\d+$/.test(end)?Number(end)+'호':'';
 return (short?stem.replace('공기압축기','압축').replace('절삭기','절삭'):stem)+(suffix?' '+suffix:'');
}
export function locationName(asset){
 const parts=String(asset?.assetId||'').match(/^[^-]+-S(\d+)-L(\d+)-/);
 return parts?`${Number(parts[1])}라인 · ${Number(parts[2])}셀`:asset?.line||'위치 미확인';
}
const sentence=(parts,i)=>({no:String(i+1).padStart(2,'0'),parts:parts.map(p=>typeof p==='string'?{text:p,weight:500,color:'#2C4159'}:{text:p.bold,weight:700,color:'#0F1E33'})});
export function selectedBrief(detail,lineage){
 const risk=detail.event.failureProbability,threshold=detail.threshold,mc=detail.maintenanceContext||{};
 const upward=[...new Set((detail.topFactors||[]).filter(f=>f.direction==='risk_up').map(f=>feature(f.feature||f.label)))];
 const incomplete=(lineage?.work_orders||[]).filter(w=>!['completed','cancelled','rejected'].includes(w.status));
 const open=mc.openWorkOrderExists===true||incomplete.length>0;
 const reasons=[
 [{bold:`위험 점수 ${risk==null?'미산정':risk.toFixed(2)}`},threshold==null?' · 조치 기준 미등록':` · 조치 기준 ${threshold.toFixed(2)} ${risk==null?'비교 불가':risk>=threshold?'초과':'미만'}`],
 upward.length?['위험 증가 요인: ',{bold:upward.slice(0,2).join(' · ')}]:['위험 증가 요인 미제공'],
 [mc.lastMaintenanceDaysAgo==null?'최근 정비일 미등록':{bold:`최근 정비 ${number(mc.lastMaintenanceDaysAgo)}일 전`},' · ',mc.similarEvents30d==null?'30일 유사 사례 미확인':{bold:`30일 유사 사례 ${number(mc.similarEvents30d)}건`}],
 [open?'미종결 작업지시 있음':mc.openWorkOrderExists===false?'미종결 작업지시 없음':'미종결 작업지시 미확인'],
 ];
 return reasons.map(sentence);
}
export function briefContext(detail,lineage,asset,contextRead){
 const mc=detail.maintenanceContext||{};const open=(lineage?.work_orders||[]).filter(w=>!['completed','cancelled','rejected'].includes(w.status));
 const rows=[['마지막 정비 경과',mc.lastMaintenanceDaysAgo==null?'미확인':number(mc.lastMaintenanceDaysAgo)+'일'],['30일 유사 사례',mc.similarEvents30d==null?'미확인':number(mc.similarEvents30d)+'건'],['미종결 작업지시',open.length?open.length+'건':mc.openWorkOrderExists===false?'없음':mc.openWorkOrderExists===true?'있음':'미확인'],['설비 중요도',({high:'높음',medium:'보통',low:'낮음'})[detail.assetCriticality||detail.event.criticality]||'미확인'],['예측 구간',detail.predictionHorizonHours==null?'미확인':number(detail.predictionHorizonHours)+'시간'],['설비 종류',equipmentName(asset).replace(/ \d+호$/,'')]];
 const production=contextRead?.domains?.production?.context;
 const supply=production?.status==='available'?production.data.supply_basis:null;
 if(supply){
   const optionValue=name=>{
    const option=contextRead.production_impact?.options?.find(o=>o.option===name);
    return option?.state==='calculated'?number(option.remaining_exposed_units)+'개':'계산 조건 미충족';
   };
   rows.push(['공기 공급 대상',supplyTargetLabel(supply.edges.map(e=>e.to_asset_id))]);
   rows.push(['즉시 정지 · 잔여 차질',optionValue('stop_now')]);
   rows.push(['계획 정비 · 잔여 차질',optionValue('planned_maintenance')]);
   rows.push(['운전 지속 · 잔여 차질',optionValue('continue_operation')]);
 }
 return rows.map(([label,value])=>({label,value,color:label==='미종결 작업지시'&&open.length?'#B02F26':'#0F1E33'}));
}
export function eventBrief(event,asset,selectedDetail){
 const factors=selectedDetail?.topFactors||asset?.topFactors||[];
 const signal=[...new Set(factors.filter(f=>f.direction==='risk_up').map(f=>feature(f.feature||f.label).split(' · ')[0]))].slice(0,2).join(' · ');
 return {title:`${label(event.status)} · ${signal?signal+' 상승 기여':'분석 요인 미제공'}`,place:locationName(asset)+' · '+equipmentName(asset),time:date(event.observedAt),cue:''};
}

export function supplyTargetLabel(ids){
 const groups=new Map();
 for(const id of [...new Set(ids)].sort()){
   const match=id.match(/^CNC-S(\d+)-L(\d+)-(\d+)$/);
   const place=locationName({assetId:id});
   if(!groups.has(place))groups.set(place,[]);
   groups.get(place).push(match?Number(match[3]):equipmentName({assetId:id}));
 }
 return [...groups].map(([place,items])=>{
   const nums=items.filter(x=>typeof x==='number').sort((a,b)=>a-b);
   const consecutive=nums.length===items.length&&nums.every((n,i)=>i===0||n===nums[i-1]+1);
   const names=nums.length===items.length?`절삭기 ${consecutive&&nums.length>1?`${nums[0]}–${nums.at(-1)}`:nums.join('·')}호` :items.map(x=>typeof x==='number'?`절삭기 ${x}호`:x).join(' · ');
   return `${place}\n${names} · ${items.length}대`;
 }).join('\n\n');
}

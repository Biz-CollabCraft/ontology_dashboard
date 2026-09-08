// Safe text-only presentation: no HTML or arbitrary link execution.
const isoPattern=/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})/g;
function kst(value){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).reduce((a,p)=>({...a,[p.type]:p.value}),{});}
export function relativeRecordTime(value,now=new Date()){
 if(!Number.isFinite(new Date(value).getTime())||!Number.isFinite(new Date(now).getTime()))return value;
 const p=kst(value),n=kst(now),days=(Date.UTC(+n.year,+n.month-1,+n.day)-Date.UTC(+p.year,+p.month-1,+p.day))/86400000;
 let date;
 if(days===0)date='오늘';
 else if(days===1)date='어제';
 else if(days>1)date=days+'일 전';
 else if(days===-1)date='내일';
 else date=Math.abs(days)+'일 후';
 return date+' '+p.hour+':'+p.minute;
}
export function readableUnits(text){
 return String(text||'')
  .replace(/(\d[\d,]*(?:\.\d+)?)\s*N·m·min\b/g,'$1 뉴턴미터·분')
  .replace(/(\d[\d,]*(?:\.\d+)?)\s*N·m\b/g,'$1 뉴턴미터')
  .replace(/(\d[\d,]*(?:\.\d+)?)\s*min\b/g,'$1분');
}
export function briefRows(quote,allowedRefs=[],now=new Date()){
 const catalog=[...new Set(allowedRefs)];
 // Emphasis changes typography only; historical wording and claims stay intact.
 const lines=String(quote||'').replace(/\\n/g,'\n').split(/\n+/).filter(s=>s.trim());
 const last=lines.length-1;
 if(last>=0&&!lines[last].includes('**'))lines[last]=lines[last].replace(/현장 측정과 비교 결과|현장 측정 결과|추가 상태 측정 및 결과 기록|유효한 운전 관측값과 이력|관측값과 정비 기록|관측·정비 자료|현장에서 확인|현장 확인 결과|작업 가능 시간|착수 가능 여부|조치 범위|현장 확인|다음 기술 판단|부품 가용성|승인 검토 결과/,word=>'**'+word+'**');
 return lines.map(line=>{
  const refs=[];const text=line.replace(/^\s*-\s+/,'').replace(/\[\[ref:([^\]\n]+)\]\]/g,(_,id)=>{const ref=/^[1-9][0-9]*$/.test(id)?catalog[Number(id)-1]:null;if(ref&&!refs.some(x=>x.text===ref))refs.push({text:ref,label:'근거'});return '';});
  const parts=[];
  text.split(/(\*\*[^*\n]+\*\*)/).filter(Boolean).forEach(s=>{
   const bold=s.startsWith('**')&&s.endsWith('**');if(bold)s=s.slice(2,-2);
   let pos=0;for(const m of s.matchAll(isoPattern)){if(m.index>pos)parts.push({text:readableUnits(s.slice(pos,m.index)),weight:bold?'700':'400',title:''});parts.push({text:relativeRecordTime(m[0],now),weight:bold?'700':'400',title:m[0]});pos=m.index+m[0].length;}
   if(pos<s.length)parts.push({text:readableUnits(s.slice(pos)),weight:bold?'700':'400',title:''});
  });
  return {parts,refs:refs.length?[{text:refs.map(ref=>ref.text).join('\n'),label:'근거'}]:[]};
 });
}

// Keep identifiers available to the formatter; disclose source categories to readers.
export function referenceLabels(refs){
 return [...new Set(String(refs).split('\n').filter(Boolean).map(ref=>{
  if(ref.includes('inspection-result'))return '점검 결과 기록';
  if(ref.includes('work-order'))return '작업요청 기록';
  if(ref.includes('inspection_sop'))return '점검 절차 기준';
  if(ref.includes('inspection_location'))return '점검 위치 참고';
  if(ref.includes('spare_part'))return '부품 참고 자료';
  if(ref.includes('similar_event'))return '유사 사례';
  if(ref.includes('production-planning'))return '생산 영향 계획 추정';
  if(ref.includes('maintenance_readiness'))return '작업 준비 조건의 확인 범위';
  if(ref.includes('quality_delivery'))return '품질·납품 정보의 확인 범위';
  if(ref.includes('production'))return '생산 조건의 확인 범위';
  if(ref.startsWith('RESULT#'))return '선택 설비의 진단 근거';
  if(ref.includes('maintenance-context'))return '정비 이력 참고';
  return '선택된 판단 근거';
 }))];
}
export function readerLimitations(items=[]){
 return [...new Set(items.map(item=>{
  const s=String(item);
  if(/read-only|mutate|Recommendation|WorkOrder|MaintenanceAction|Replay/.test(s))return 'AI 설명은 작업요청 등록·승인·정비 실행을 수행하지 않습니다.';
  if(/SOP|fixture|수리 지시/.test(s))return '점검 절차는 참고 기준이며, 현장 확인과 조치 판단이 필요합니다.';
  if(/maintenance_readiness/.test(s))return '실제 재고·조달 기간·작업 가능 시간은 제공된 기록으로 확인해야 합니다.';
  if(/quality_delivery/.test(s))return '품질·납품 조건이 연결되지 않아 영향 확정에 제한이 있습니다.';
  if(/production/.test(s))return '생산 계획 추정과 실제 손실을 구분해 확인해야 합니다.';
  if(/snapshot|스냅샷|not_connected|owner_domain|schema|source_ref|[{}]|^[A-Za-z]/.test(s))return '선택한 설비와 기준 시각에 맞는 일부 기록이 제공되지 않았습니다.';
  return readableUnits(s).replace(isoPattern,v=>relativeRecordTime(v));
 }))];
}

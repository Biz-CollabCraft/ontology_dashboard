import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { EngineerFactoryStandalone } from "./EngineerFactoryStandalone";
import type { OperationsBootstrapModel, OperationsAgentReviewSummaryResponse } from "../api/operationsContracts";
import { relativeRecordTime } from "../../../standalone/briefFormat.js";
import "../../../app.css";
import "../operations.css";
import "./FinalBriefingDemo.css";

type Delivery = {
  case_id: number; label: string; checks: Record<string, boolean>; evidence_count: number; excluded_record_count: number;
  input_sha256: string; response: OperationsAgentReviewSummaryResponse;
  view_model: { asset: {asset_id:string; display_name:string; observed_at:string}; snapshot_basis:{event_id:string; observed_at:string};
    data_status:{is_data_quality_hold:boolean};
    risk:{current:number|null;status_grade: OperationsBootstrapModel["assets"][number]["status"]|null};
    features:Array<{key:string;label:string;unit:string;current:{value:number|null};top_factor:{contribution:number;direction:"risk_up"|"risk_down"}|null}> };
  facts: { data_quality_hold:boolean; inspection_results:Array<{recorded_at:string; findings:string[]}>;
    work_orders:Array<{status:string;recorded_at:string;owner_record_provenance?:{approved_at?:string}}>;
    operation_context:{estimated_downtime_minutes?:number; estimated_lost_units?:number} };
};
const API = "http://127.0.0.1:8328/api/demo-briefing";
const pending = {summary:null,trace:{fallback:false,materialization:{status:"pending"}}} as OperationsAgentReviewSummaryResponse;
const units: Record<string,string> = {min:"분", "N·m":"뉴턴미터", "N·m·min":"뉴턴미터·분"};
// Reject incomplete responses before they enter React rendering or enable confirmation.
function validDelivery(d: Delivery, caseId: number) {
  const vm=d?.view_model, facts=d?.facts;
  return d?.case_id===caseId && /^[a-f0-9]{64}$/.test(d?.input_sha256 ?? "")
    && ["input_hash","asset_event_time","selected_evidence_only","screen_context"].every(k=>d.checks?.[k]===true)
    && typeof vm?.asset?.asset_id==="string" && typeof vm.asset.display_name==="string"
    && typeof vm.snapshot_basis?.event_id==="string" && Number.isFinite(Date.parse(vm.snapshot_basis.observed_at))
    && vm.asset.observed_at===vm.snapshot_basis.observed_at
    && ((vm.data_status?.is_data_quality_hold===true && facts?.data_quality_hold===true && vm.risk?.current===null && vm.risk.status_grade===null) || ["normal","attention","warning","critical"].includes(vm.risk?.status_grade ?? ""))
    && Array.isArray(vm.features) && vm.features.every(f=>typeof f?.key==="string" && typeof f.label==="string" && typeof f.unit==="string" && f.current && (f.current.value===null || Number.isFinite(f.current.value)))
    && Array.isArray(facts?.inspection_results) && facts.inspection_results.every(r=>typeof r.recorded_at==="string" && Array.isArray(r.findings) && r.findings.every(f=>typeof f==="string"))
    && Array.isArray(facts.work_orders) && facts.work_orders.every(r=>typeof r.status==="string" && typeof r.recorded_at==="string")
    && facts.operation_context && d.response?.summary===null && d.response.trace?.materialization?.status==="pending";
}
async function fetchDemo(url: string, options: RequestInit) {
  const signal=AbortSignal.any([options.signal!, AbortSignal.timeout(10000)]);
  const response=await fetch(url,{...options,signal});
  if(!response.ok)throw new Error("demo_response_failed");
  return response.json();
}
function modelFromDelivery(d: Delivery): OperationsBootstrapModel {
  const vm=d.view_model, asset=vm.asset, asOf=vm.snapshot_basis.observed_at;
  const status=vm.data_status.is_data_quality_hold?"data_quality_hold":vm.risk.status_grade!;
  return {
    context:{projectId:"manufacturing-demo-project",workspaceId:"manufacturing-demo",workspaceName:"공장 A · 최종 시연",datasetVersionId:"recorded-demo",observedAt:asOf,warnings:[],projectName:"최종 시연",datasetLabel:"보관된 관측",sourceVersion:null,modelVersion:null,schemaVersion:null,sourceMode:"gold-fixture-fallback",sourceStatus:"recorded",refreshedAt:asOf,stale:true},
    assets:[{assetId:asset.asset_id,displayName:asset.display_name,assetType:"cnc",line:asset.asset_id.split("-")[1],cell:asset.asset_id.split("-").slice(1,3).join("-"),site:"공장 A",
      status,failureProbability:vm.risk.current,confidence:"unavailable",confidenceScore:null,criticality:null,assignedEngineer:null,
      estimatedDowntimeMinutes:d.facts.operation_context.estimated_downtime_minutes??null,sparePartAvailable:null,
      predictedFailureType:"",recommendedDecision:d.facts.data_quality_hold?"hold_for_data_check":"request_inspection",provenance:{datasetId:null,datasetVersionId:"recorded-demo",datasetLabel:"보관된 관측",sourceVersion:null,modelVersion:null,policyVersion:null,schemaVersion:null,promptVersion:null,sourceRefs:[]},observedAt:asOf,eventId:vm.snapshot_basis.event_id,
      topFactors:vm.features.map((f,i)=>({id:String(i),feature:f.key,label:f.label,value:f.current.value,unit:units[f.unit]||f.unit,
        contribution:f.top_factor?.contribution??0,direction:f.top_factor?.direction??"risk_up",explanationMethod:null})),riskHistory:[],sensorHistory:[]}],
    events:[],lineRisk:[],metrics:{totalAssets:1,dataQualityHold:d.facts.data_quality_hold?1:0,averageRisk:vm.risk.current,pendingDecisions:0,critical:vm.risk.status_grade==="critical"?1:0,warning:vm.risk.status_grade==="warning"?1:0,attention:0,normal:0,estimatedDowntimeMinutes:d.facts.operation_context.estimated_downtime_minutes??null},
  };
}
function FinalDemo(){
  const [cases,setCases]=useState<Array<{case_id:number;label:string}>>([]);
  const [caseId,setCaseId]=useState(3);
  const [delivery,setDelivery]=useState<Delivery|null>(null);
  const [response,setResponse]=useState(pending);
  const [phase,setPhase]=useState("loading");
  const [error,setError]=useState("");
  const [confirmed,setConfirmed]=useState(false);
  const [role,setRole]=useState<"process_engineer"|"maintenance_technician"|"process_manager">(()=>new URLSearchParams(location.search).get("view")==="maintenance"?"maintenance_technician":new URLSearchParams(location.search).get("view")==="production"?"process_manager":"process_engineer");
  const controller=useRef<AbortController|null>(null);
  const inFlight=useRef<object|null>(null);
  useEffect(()=>{const c=new AbortController(); fetchDemo(`${API}/cases`,{signal:c.signal}).then(items=>{if(!Array.isArray(items)||!items.every(x=>Number.isInteger(x?.case_id)&&typeof x.label==="string"))throw Error();setCases(items);}).catch(()=>{if(!c.signal.aborted)setError("시연 서버 연결을 확인해 주세요.");});return()=>c.abort();},[]);
  useEffect(()=>{
    controller.current?.abort(); inFlight.current=null; const c=new AbortController();controller.current=c;
    setDelivery(null);setResponse(pending);setPhase("loading");setConfirmed(false);setError("");
    fetchDemo(`${API}/cases/${caseId}`,{signal:c.signal}).then(d=>{
      if(!validDelivery(d,caseId))throw Error();
      if(!c.signal.aborted){setDelivery(d);setResponse(d.response);setPhase("pending");}
    }).catch(()=>{if(!c.signal.aborted){setError("시연 서버에 연결하지 못했습니다. 서버를 실행한 뒤 새로고침해 주세요.");setPhase("error");}});
    return()=>c.abort();
  },[caseId]);
  async function validate(variant:"recorded"|"rejected"){
    if(!delivery||inFlight.current)return;
    const requestToken={};inFlight.current=requestToken;
    const c=controller.current!;setResponse(pending);setConfirmed(false);setPhase("checking");setError("");
    try{
      const next=await fetchDemo(`${API}/cases/${caseId}/validate`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({variant}),signal:c.signal});
      if(c.signal.aborted)return;
      if(next.replay.input_sha256!==delivery.input_sha256||next.replay.case_id!==caseId)throw Error();
      if(next.trace?.fallback===true){
        if(next.summary!==null || next.trace.materialization?.status!=="fallback")throw Error();
        setResponse(next);setPhase("fallback");
      }else{
        const summary=next.summary;
        if(next.trace?.fallback!==false || next.trace.materialization?.status!=="ready"
          || summary?.asset_id!==delivery.view_model.asset.asset_id || summary.mode!=="llm"
          || typeof summary.summary!=="string" || !Array.isArray(summary.role_summaries)
          || !summary.role_summaries.every((r: {role:string;quote:string})=>typeof r?.role==="string"&&typeof r.quote==="string")
          || !Array.isArray(summary.source_refs) || !summary.source_refs.every((r:unknown)=>typeof r==="string")
          || !Array.isArray(summary.limitations) || !summary.limitations.every((r:unknown)=>typeof r==="string"))throw Error();
        setResponse(next);setPhase("ready");
      }
    }catch{if(!c.signal.aborted){setPhase("error");setError("검증 응답을 확인하지 못했습니다. 다시 검사해 주세요.");}}
    finally{if(inFlight.current===requestToken)inFlight.current=null;}
  }
  const ready=phase==="ready"; const model=delivery?modelFromDelivery(delivery):null;
  const scrollBrief=()=>document.querySelector('.natural-briefing')?.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});
  const records=delivery?<div className="engineer-status-side-stack final-demo-records"><section className="engineer-factory-card"><header><strong>기준 시각의 작업 기록</strong><span>현재 설비에 해당하는 기록</span></header><div>{delivery.facts.work_orders.length?delivery.facts.work_orders.map((r,i)=><p key={i}><strong>{r.status==="approved"?"작업요청 승인 기록 있음":"작업요청 등록 기록 있음"}</strong><br/>{relativeRecordTime(r.owner_record_provenance?.approved_at||r.recorded_at)}</p>):<p>작업요청·승인 기록이 제공되지 않았습니다.</p>}{delivery.facts.inspection_results.map((r,i)=><p key={i}>{r.findings.join(" · ")}<br/>{relativeRecordTime(r.recorded_at)} 점검 기록</p>)}{delivery.excluded_record_count>0&&<p>시각·설비·사건 범위가 맞지 않는 기록 {delivery.excluded_record_count}건 제외</p>}</div></section><section className="engineer-factory-card"><header><strong>다음 판단 전 확인할 조건</strong></header><div><p>착수·완료 기록 <strong>미확인</strong></p><p>실제 재고·조달 기간 <strong>미확인</strong></p><p>작업 가능 시간 <strong>미확인</strong></p><p>승인 기록만으로 실행 준비가 끝났다고 판단하지 않습니다.</p></div></section></div>:undefined;
  return <div className="final-briefing-demo">
    <header className="final-demo-header"><div><span>서버 기반 AI 브리핑</span><h1>근거에서 확인까지</h1><p>보관된 입력과 응답을 현재 서버에서 다시 검사하는 로컬 시연</p></div><a href="#demo-screen" onClick={e=>{e.preventDefault();scrollBrief();}}>브리핑으로 이동 ↓</a></header>
    <section className="final-demo-controls" aria-label="시연 흐름">
      <div className="final-demo-selects"><label>입력 사례<select value={caseId} onChange={e=>setCaseId(Number(e.target.value))}>{cases.map(c=><option key={c.case_id} value={c.case_id}>{c.label}</option>)}</select></label>
      <label>확인 관점<select value={role} onChange={e=>{setRole(e.target.value as typeof role);setConfirmed(false);}}><option value="process_engineer">설비 판단</option><option value="maintenance_technician">점검·작업 준비</option><option value="process_manager">생산 영향</option></select></label></div>
      <ol className="final-demo-flow">{["입력","근거 패키지","화면 전달","AI 브리핑 검증","엔지니어 확인"].map((label,i)=>
        <li key={label} data-complete={i<3?Boolean(delivery&&Object.values(delivery.checks).every(Boolean)):i===3?ready:confirmed}><span>{i+1}</span><strong>{label}</strong><small>{i<3?delivery?"연결 확인":"대기":i===3?ready?"내용 검사 통과":phase==="fallback"?"응답 제외":phase==="checking"?"검사 중":"검사 대기":confirmed?"읽음 확인":"확인 대기"}</small></li>)}</ol>
      <div className="final-demo-actions"><button disabled={!delivery||phase==="checking"} onClick={()=>void validate("recorded")}>브리핑 검증</button><button className="secondary" disabled={!delivery||phase==="checking"} onClick={()=>void validate("rejected")}>검증 실패 시연</button><button className="secondary" disabled={!ready||confirmed} onClick={()=>setConfirmed(true)}>{confirmed?"엔지니어 확인 완료":"근거를 읽고 확인"}</button><span role="status">{error|| (phase==="fallback"?"검사에서 탈락한 문장은 제공하지 않습니다.":ready?"검사 통과 후에만 브리핑을 표시합니다.":"현재 근거의 브리핑 검증을 기다리고 있습니다.")}</span></div>
      <p className="final-demo-boundary">엔지니어 확인은 이 화면의 읽음 표시입니다. 작업요청 등록·승인·정비 실행 상태를 바꾸지 않습니다.</p>
      {delivery&&<details className="final-demo-evidence"><summary>근거 연결 보기</summary><div>
        <p><strong>{delivery.view_model.asset.display_name}</strong> · 기준 시각 {relativeRecordTime(delivery.view_model.snapshot_basis.observed_at)}</p>
        <p>동일 입력 확인 · 설비·사건·시각 유지 · 선택된 근거만 전달 · 화면용 값 연결 확인</p>
        {delivery.facts.inspection_results.map((r,i)=><p key={i}>{relativeRecordTime(r.recorded_at)} 점검 기록: {r.findings.join(" · ")}</p>)}
        {delivery.facts.work_orders.map((r,i)=><p key={i}>{relativeRecordTime(r.owner_record_provenance?.approved_at||r.recorded_at)} 작업요청 {r.status==="approved"?"승인 기록 있음":"등록 기록 있음"}. 착수·완료 기록과 실제 재고·작업 가능 시간은 별도 확인이 필요합니다.</p>)}
        {!delivery.facts.work_orders.length&&<p>기준 시각에 맞는 현재 설비의 작업요청·승인 기록이 제공되지 않았습니다.</p>}
        {delivery.excluded_record_count>0&&<p>기준 시각 이후이거나 다른 설비·사건에 속한 기록 {delivery.excluded_record_count}건을 현재 상태 판단에서 제외했습니다.</p>}
        {delivery.facts.data_quality_hold?<p>데이터 품질 확인이 필요해 진단값보다 계측 상태 확인을 우선합니다.</p>:<p>생산 영향: 정지 {delivery.facts.operation_context.estimated_downtime_minutes??"미확인"}분 가정의 예상 손실 {delivery.facts.operation_context.estimated_lost_units??"미확인"}개. 계획 추정이며 실제 손실이 아닙니다.</p>}
      </div></details>}
      <details className="final-demo-evidence"><summary>검증 성과와 범위</summary><div className="final-demo-metrics"><p>입력→화면 제공 안정성<strong>40/40</strong></p><p>내용 검사 통과 후보 반환율<strong>20.8% → 80.8%</strong><span>+60.0%p · 각 120개 응답</span></p><p>블라인드 에이전트 선호율<strong>17/24 · 70.8%</strong></p></div><p>기존 gpt-5.6-luna A/B 산출물 기준입니다. 자동 판단 유용성 통과는 18/120이며, 사람의 현장 평가나 운영 성과를 뜻하지 않습니다. 현재 화면 수정에 대한 신규 모델 비교 실험은 수행하지 않았습니다.</p></details>
    </section>
    <div id="demo-screen">{model&&delivery?<EngineerFactoryStandalone key={caseId} model={model} selectedAssetId={model.assets[0].assetId} briefingResponse={response} briefingRole={role} recordPanel={records} readOnly currentUser={{displayName:"시연",title:""}} onSelectAsset={()=>{}} onRefresh={()=>{}}/>:<p className="final-demo-empty">{error||"입력과 근거를 불러오고 있습니다."}</p>}</div>
  </div>;
}
createRoot(document.getElementById("root")!).render(<FinalDemo/>);

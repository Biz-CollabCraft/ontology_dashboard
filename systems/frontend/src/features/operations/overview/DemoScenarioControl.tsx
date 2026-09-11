import { useEffect, useRef, useState } from "react";
import "./DemoScenarioControl.css";
type Mode = "live" | "normal" | "emergency";
type State = { mode: Mode; options: Partial<Record<Mode, {observed_at: string}>> };
const url = "/api/projects/manufacturing-demo-project/workspaces/manufacturing-demo/predictive-maintenance/demo-scenario";
export function DemoScenarioControl() {
  const [state,setState]=useState<State|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState(false);
  const previousMode=useRef<Mode|null>(null);
  useEffect(()=>{
    let alive=true;
    async function load(){try{const r=await fetch(url,{credentials:"include"});if(!r.ok)throw new Error();const data=await r.json();if(alive){if(previousMode.current!==null&&previousMode.current!==data.mode){window.location.reload();return;}previousMode.current=data.mode;setState(data);setError(false);}}catch{if(alive)setError(true);}}
    void load();const timer=setInterval(()=>void load(),10000);
    return()=>{alive=false;clearInterval(timer);};
  },[]);
  async function select(mode:Mode){
    setBusy(true);setError(false);
    try{
      const csrf=document.cookie.split(";").map(v=>v.trim()).find(v=>v.startsWith("ontology_csrf="))?.slice(14);
      const r=await fetch(url,{method:"POST",credentials:"include",headers:{"Content-Type":"application/json",...(csrf?{"X-CSRF-Token":decodeURIComponent(csrf)}:{})},body:JSON.stringify({mode})});
      if(!r.ok)throw new Error();
      window.location.reload();
    }catch{setError(true);setBusy(false);}
  }
  return <footer className="demo-scenario-control" aria-label="시연 데이터 전환">
    <div><strong>시연 데이터</strong><span>모든 사용자 공통 적용 · 기존 점검·승인 이력 유지</span></div>
    <div>{([['normal','평시'],['emergency','비상'],['live','기존 데이터']] as const).map(([mode,label])=><button key={mode} type="button" aria-pressed={state?.mode===mode} disabled={busy||!state||(mode!=='live'&&!state.options[mode])} onClick={()=>void select(mode)}>{label}</button>)}</div>
    <small role="status">{error?"시나리오 연결을 확인해 주세요.":busy?"전환 중…":!state?"적용 상태 확인 중…":state.mode==='live'?"기존 데이터 적용 중":`${state.mode==='normal'?'평시':'비상'} 시연 관측 · ${state.options[state.mode]?.observed_at??''} · 재생용 고정 데이터`}</small>
  </footer>;
}

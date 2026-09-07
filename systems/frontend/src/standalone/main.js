import {acceptedBrief} from './aiBrief.js';
import {mapPresentation, label} from './presentation.js';
window.factoryDisplay=mapPresentation;
import { API_BASE, getCurrentUser, getProjects, getProjectWorkspaces, setActiveProject, logout, getMaintenanceEventLineage, getMaintenanceActionCandidates, getPostMaintenanceProductResults } from '../api';
import { loadOperationsBootstrap } from '../features/operations/api/operationsApi';
import { composeEventDetail, applyAssetDetailViewModel } from '../features/operations/api/operationsAdapters';

const base = import.meta.env.BASE_URL;
const params = new URLSearchParams(location.search);
const state = {model:null,detail:null,lineage:null,candidates:[],role:null,selectedAssetId:params.get('asset'),selectedEventId:params.get('event'),snapshotId:params.get("snapshot"),asOf:params.get("asof"),busy:false,error:null,workflowError:null,blockedReason:'조회 중 · 실행할 수 없습니다.'};
let user, generation=0, controller, projectId=params.get('project'), workspaceId=params.get('workspace');
const idempotency = new Map();
const emit=()=>{window.factoryState={...state};window.dispatchEvent(new CustomEvent('factory:state',{detail:window.factoryState}));};
const errorText=e=>e instanceof Error?e.message:String(e);
function login(){location.replace(`${base}login?returnTo=${encodeURIComponent(location.pathname+location.search+location.hash)}`);}
async function request(path, options={}) {
  const headers = new Headers(options.headers);
  if(options.body){headers.set('Content-Type','application/json');headers.set('X-CSRF-Token',decodeURIComponent(document.cookie.split('; ').find(x=>x.startsWith('ontology_csrf='))?.split('=').slice(1).join('=')||''));}
  const response=await fetch(`${API_BASE}${path}`,{credentials:'include',...options,headers});
  const body=await response.json().catch(()=>({}));
  if(response.status===401){login();throw new Error('세션이 만료되었습니다.');}
  if(!response.ok)throw new Error(`${response.status} · ${body.error?.code||body.detail?.code||body.detail||body.error?.message||'서버 요청 실패'}`);
  return body;
}
function url(){const q=new URLSearchParams({project:projectId,workspace:workspaceId});if(state.selectedAssetId)q.set('asset',state.selectedAssetId);if(state.selectedEventId)q.set('event',state.selectedEventId);if(state.snapshotId)q.set('snapshot',state.snapshotId);if(state.asOf)q.set('asof',state.asOf);history.replaceState(null,'',`${location.pathname}?${q}${location.hash}`);}
async function viewModel(signal) {
  const q=new URLSearchParams({project_id:projectId,workspace_id:workspaceId,event_id:state.selectedEventId,history_window:'24h'});
  const dataset=state.model?.events.find(e=>e.eventId===state.selectedEventId)?.datasetVersionId||state.model?.context.datasetVersionId;
  if(dataset)q.set('dataset_version_id',dataset);
  return request(`/api/objects/${encodeURIComponent(state.selectedAssetId)}/detail-view?${q}`,{signal});
}
function commandFor(vm,lineage) {
  if(!vm||!lineage||state.error||state.workflowError||state.busy)return null;
  const allowed=(id,target)=>vm.closed_loop?.available_actions?.some(a=>a.action_id===id&&a.target_id===target&&!a.disabled_reason);
  const cmd=(id,target,label,path,body)=>({actionId:id,targetId:target,label,path,body});
  const root=`/api/projects/${encodeURIComponent(projectId)}/workspaces/${encodeURIComponent(workspaceId)}/maintenance`;
  if(state.role==='process_manager'&&user.permissions.includes('events.decision')) {
    for(const r of lineage.recommendations||[])if(allowed('decide_operations_manual_recommendation',r.recommendation_id))return cmd('decide_operations_manual_recommendation',r.recommendation_id,'정비안 채택 · WorkOrder 승인 별도',`${root}/recommendations/${encodeURIComponent(r.recommendation_id)}/decisions`,{disposition:'accept',note:'사용자 명시적 판단'});
    for(const w of lineage.work_orders||[])if(w.work_type==='maintenance'&&allowed('approve_maintenance_work_order',w.work_order_id))return cmd('approve_maintenance_work_order',w.work_order_id,'정비 WorkOrder 명시적 승인',`${root}/maintenance-work-orders/${encodeURIComponent(w.work_order_id)}/approve`,{});
  }
  if(state.role==='maintenance_technician'&&user.permissions.includes('ontology.actions.execute'))for(const a of lineage.maintenance_actions||[]) {
    if(allowed('start_maintenance_action',a.maintenance_action_id))return cmd('start_maintenance_action',a.maintenance_action_id,'승인된 정비 시작',`${root}/maintenance-actions/${encodeURIComponent(a.maintenance_action_id)}/start`,{});
    if(allowed('complete_maintenance_action',a.maintenance_action_id))return cmd('complete_maintenance_action',a.maintenance_action_id,'실제 수행 결과 저장·정비 완료',`${root}/maintenance-actions/${encodeURIComponent(a.maintenance_action_id)}/complete`,null);
  }
  return null;
}
let rawView=null;
async function refresh({reloadList=true}={}) {
  const token=++generation;controller?.abort();controller=new AbortController();const signal=controller.signal;
  Object.assign(state,{detail:null,lineage:null,contextRead:null,contextError:null,factoryRecords:null,factoryRecordsError:null,aiBrief:null,aiError:null,aiFallback:null,aiLoading:false,aiGenerating:false,candidates:[],command:null,prediction:null,detailError:null,workflowError:null,error:null});rawView=null;emit();
  try{
    if(reloadList){const model=await loadOperationsBootstrap(projectId,workspaceId,state.selectedEventId);if(token!==generation)return;if(model.context.workspaceId!==workspaceId)throw new Error('요청 Workspace를 복원할 수 없습니다.');state.model=model;}
    if(token!==generation)return;
    const events=state.model.events;
    let event=events.find(e=>e.eventId===state.selectedEventId&&(!state.selectedAssetId||e.assetId===state.selectedAssetId));
    if(!state.selectedEventId)event=events.find(e=>!state.selectedAssetId||e.assetId===state.selectedAssetId);
    if(!event)throw new Error('선택한 설비·이벤트를 조회할 수 없습니다. 다른 대상으로 대체하지 않았습니다.');
    state.selectedAssetId=event.assetId;state.selectedEventId=event.eventId;url();emit();
    const vm=await viewModel(signal);if(token!==generation)return;
    if(vm.snapshot_basis.asset_id!==event.assetId||![vm.snapshot_basis.event_id,vm.snapshot_basis.artifact_id].includes(event.eventId))throw new Error('snapshot 불일치 · 조회 및 저장을 중단했습니다.');
    if((state.snapshotId&&state.snapshotId!==vm.snapshot_basis.artifact_id)||(state.asOf&&Date.parse(state.asOf)!==Date.parse(vm.snapshot_basis.observed_at)))throw new Error('URL snapshot/as-of 불일치 · 저장을 중단했습니다.');
    state.snapshotId=vm.snapshot_basis.artifact_id;state.asOf=vm.snapshot_basis.observed_at;url();
    rawView=vm;state.detail=applyAssetDetailViewModel(composeEventDetail({event,evidence:null,report:null,activity:[],warnings:state.model.context.warnings||[]}),vm);state.detail.event={...state.detail.event,failureProbability:vm.risk.current,status:vm.risk.status_grade};emit();
    const contextQuery=new URLSearchParams({project_id:projectId,workspace_id:workspaceId,evidence_snapshot_id:vm.snapshot_basis.artifact_id,decision_as_of:vm.snapshot_basis.observed_at});
    try {const context=await request(`/api/objects/${encodeURIComponent(event.assetId)}/operational-context?${contextQuery}`,{signal});if(token!==generation)return;state.contextRead=context;}catch(e){if(token!==generation)return;state.contextError=errorText(e);}
    try {
      const records=await request(`/api/objects/${encodeURIComponent(event.assetId)}/factory-records?${contextQuery}`,{signal});
      if(token!==generation)return;
      state.factoryRecords=records;
      if(records.status==='available'){
        state.detail={...state.detail,threshold:records.policy.action_threshold,
          maintenanceContext:{...state.detail.maintenanceContext,similarEvents30d:records.similar_events_30d},
          warnings:state.detail.warnings.filter(w=>!(records.similar_events_30d!=null&&w.includes('maintenance_context.similar_events_30d')))};
      }
    }catch(e){if(token!==generation)return;state.factoryRecordsError=errorText(e);}
    const lineage=await getMaintenanceEventLineage(projectId,workspaceId,event.eventId,signal);if(token!==generation)return;
    if(lineage.event_id!==event.eventId)throw new Error('정비 이력 event 불일치');state.lineage=lineage;
    const result=lineage.inspection_results?.at(-1);
    if(result?.outcome==='maintenance_recommended'){const response=await getMaintenanceActionCandidates(projectId,workspaceId,result.inspection_result_id,signal);if(token!==generation)return;state.candidates=response.items;}
    const maintenance=lineage.maintenance_events?.at(-1);
    if(maintenance){const result=await getPostMaintenanceProductResults(projectId,workspaceId,event.assetId,maintenance.maintenance_event_id,signal);if(token!==generation)return;state.prediction=result?`후속 관측 ${result.observed_at} · ${result.status_grade} · 생산 회복은 별도 확인`:'후속 관측 미확인 · 정비 완료와 이상 해소는 별도입니다.';}
    state.command=commandFor(vm,lineage);

    state.blockedReason=state.role==='process_engineer'?'엔지니어 점검 요청은 현재 서버 역할 계약 미지원입니다.':state.role==='maintenance_technician'?'보전팀 점검 수락·시작·기록은 현재 서버 역할 계약 미지원입니다. 정비는 승인 및 서버 허용 액션이 필요합니다.':'현재 상세 조회에 정비 허용 액션이 제공되지 않아 실행할 수 없습니다. 신규 정비안 생성은 비용 분석 참조 계약 연결 전이며 일정·예상 정지시간 저장은 미지원입니다.';
  }catch(e){if(token!==generation||signal.aborted)return;state.command=null;if(state.detail)state.workflowError=errorText(e);else state.detailError=state.error=errorText(e);}
  finally{if(token===generation){emit();if(state.detail)void loadAiBrief(token,signal);}}
}
function aiPath(){
 const q=new URLSearchParams({project_id:projectId,event_id:state.selectedEventId,history_window:'24h'});
 if(state.model?.context.datasetVersionId)q.set('dataset_version_id',state.model.context.datasetVersionId);
 return `/api/objects/${encodeURIComponent(state.selectedAssetId)}/agent-review-summary?${q}`;
}
async function loadAiBrief(token,signal){
 if(workspaceId!=='manufacturing-demo'){state.aiError='현재 작업장은 AI 브리핑 계약 미지원';emit();return;}
 state.aiLoading=true;emit();
 try{const response=await request(aiPath(),{signal});if(token!==generation)return;
 state.aiBrief=acceptedBrief(response,state.selectedAssetId);state.aiFallback=response.trace?.fallback?response.trace:null;state.aiTrace=response.trace;
 }catch(e){if(token!==generation||signal?.aborted)return;state.aiError=errorText(e);}
 finally{if(token===generation){state.aiLoading=false;emit();}}
}
async function generateAi(data){
 if(!state.canGenerateAi||state.aiGenerating||state.aiLoading||!state.detail||state.error||data.assetId!==state.selectedAssetId||data.eventId!==state.selectedEventId)return;
 const token=generation,signal=controller.signal;state.aiGenerating=true;state.aiError=null;emit();
 try{const response=await request(aiPath()+'&trigger=ui_manual_regeneration',{method:'POST',body:'{}',headers:{'Idempotency-Key':crypto.randomUUID()},signal});if(token!==generation)return;
 const generated=acceptedBrief(response,state.selectedAssetId);
 state.aiFallback=response.trace?.fallback?response.trace:null;
 if(!generated){state.aiBrief=null;state.aiError='AI 생성 결과가 검증을 통과하지 못했습니다. 기존 판단 근거를 확인하세요.';return;}
 await loadAiBrief(token,signal);
 }catch(e){if(token!==generation||signal.aborted)return;state.aiError=errorText(e);}
 finally{if(token===generation){state.aiGenerating=false;emit();}}
}
async function save(data) {
  if(state.busy||!state.command||data.assetId!==state.selectedAssetId||data.eventId!==state.selectedEventId||JSON.stringify(data.snapshotBasis)!==JSON.stringify(state.detail?.snapshotBasis)||data.command?.actionId!==state.command.actionId||data.command?.targetId!==state.command.targetId)return;
  const selected=generation, original=rawView.snapshot_basis, command=state.command;
  if(command.actionId==='complete_maintenance_action'&&(!data.outcome?.trim()||data.outcome.length>4000)){state.workflowError='실제 수행 결과를 1~4000자로 입력하세요.';emit();return;}
  state.busy=true;state.command=null;state.notice=null;emit();
  try {
    const current=await viewModel();if(selected!==generation)return;
    if(JSON.stringify(current.snapshot_basis)!==JSON.stringify(original))throw new Error('snapshot 변경 · 다시 조회 후 판단하세요.');
    state.busy=false;const fresh=commandFor(current,state.lineage);state.busy=true;
    if(!fresh||fresh.actionId!==command.actionId||fresh.targetId!==command.targetId)throw new Error('허용 액션 또는 작업 상태가 변경되었습니다.');
    const body=command.body??{outcome:data.outcome.trim()};
    const key=JSON.stringify([projectId,workspaceId,data.eventId,original,command.actionId,command.targetId,body]);
    if(!idempotency.has(key))idempotency.set(key,crypto.randomUUID());
    await request(command.path,{method:'POST',body:JSON.stringify(body),headers:{'Idempotency-Key':idempotency.get(key)}});
    if(selected!==generation)return;
    state.busy=false;const refreshGeneration=generation+1;await refresh();
    if(generation===refreshGeneration){state.notice=state.error||state.workflowError?'저장은 성공했으나 재조회 실패 · 다시 조회하세요.':'서버 저장 후 목록·상세 재조회 완료';emit();}
  } catch(e){if(selected===generation)state.workflowError=errorText(e);}
  finally{state.busy=false;if(selected===generation)emit();}
}
window.addEventListener('factory:ready',emit);
window.addEventListener('factory:request',event=>{
 const data=event.detail;
 if(data.type==='operations:select'&&!state.busy){if(data.assetId===state.selectedAssetId&&data.eventId===state.selectedEventId)return;if(!state.model?.events.some(e=>e.assetId===data.assetId&&e.eventId===data.eventId))return;state.snapshotId=null;state.asOf=null;state.selectedAssetId=data.assetId;state.selectedEventId=data.eventId;state.notice=null;url();void refresh({reloadList:false});}
 if(data.type==='operations:ai-summary')void generateAi(data);
 if(data.type==='operations:command')void save(data);
 if(data.type==='operations:session')document.getElementById('session-dialog')?.showModal();
});
window.addEventListener('popstate',()=>{if(state.busy)return;const q=new URLSearchParams(location.search);state.snapshotId=q.get('snapshot');state.asOf=q.get('asof');state.selectedAssetId=q.get('asset');state.selectedEventId=q.get('event');void refresh();});
async function sessionControls(){
 const dialog=document.getElementById('session-dialog');const projects=await getProjects();
 const userLabel=document.createElement('p');userLabel.textContent=`${user.display_name} · ${label(state.role)}`;dialog.append(userLabel);
 const project=document.createElement('select');project.ariaLabel='프로젝트';for(const p of projects){const o=new Option(p.name||p.id,p.id);project.add(o);}project.value=projectId;dialog.append(project);
 const workspace=document.createElement('select');workspace.ariaLabel='워크스페이스';for(const w of await getProjectWorkspaces(projectId))workspace.add(new Option(w.name||w.id,w.id));workspace.value=workspaceId;dialog.append(workspace);
 project.onchange=async()=>{if(state.busy){project.value=projectId;return;}try{await setActiveProject(project.value);location.assign(`${location.pathname}?project=${encodeURIComponent(project.value)}`);}catch(e){state.error=errorText(e);emit();}};
 workspace.onchange=()=>!state.busy&&location.assign(`${location.pathname}?project=${encodeURIComponent(projectId)}&workspace=${encodeURIComponent(workspace.value)}`);
 for(const [label,action] of [['새로 조회',()=>{if(state.busy)return;dialog.close();void refresh();}],['기존 앱',()=>location.assign(`${base}app/projects/${encodeURIComponent(projectId)}/operations`)],['로그아웃',async()=>{await logout();login();}],['닫기',()=>dialog.close()]]){const button=document.createElement('button');button.textContent=label;button.onclick=action;dialog.append(button);}
}
async function boot(){emit();try{user=await getCurrentUser();projectId=projectId||user.active_project_id||user.project_scopes[0];if(!projectId)throw new Error('접근 가능한 프로젝트가 없습니다.');if(user.active_project_id!==projectId)user=await setActiveProject(projectId);const roles=user.active_project_roles.length?user.active_project_roles:user.roles;state.role=['process_manager','maintenance_technician','process_engineer'].find(r=>roles.includes(r))||roles[0];const workspaces=await getProjectWorkspaces(projectId);workspaceId=workspaceId||workspaces.find(w=>user.workspace_scopes.includes(w.id))?.id||workspaces[0]?.id;if(!workspaceId)throw new Error('접근 가능한 Workspace가 없습니다.');state.canGenerateAi=workspaceId==='manufacturing-demo'&&user.permissions.includes('agent.review.materialize');await sessionControls();await refresh();}catch(e){if(e.status===401){login();return;}state.error=errorText(e);emit();}}
void boot();

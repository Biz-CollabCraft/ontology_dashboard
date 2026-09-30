import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowLeft, ArrowRight, Factory, RefreshCw, Search, LogOut } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { navigate } from "../../../routing";
import { createOperationsAgentReviewSummary, getOperationsAgentReviewSummary } from "../../../api";
import type { OperationsAgentReviewSummaryResponse, OperationsAsset, OperationsBootstrapModel, OperationsEvent, OperationsEventDetailModel, OperationsRoleLens } from "../api/operationsContracts";
import { loadDecisionWorkspaceDetail, loadOperationsBootstrap } from "../api/operationsApi";
import { OperationsSelectionProvider, useOperationsSelection } from "../context/OperationsSelectionContext";
import { STATUS_LABEL, formatTimestamp, formatProbability } from "../components/OperationsUi";
import { displayAssetName, displayEventAssetName, fieldFailureLabel } from "../displayLabels";
import { MaintenanceWorkflowActionPanel } from "../maintenance/MaintenanceWorkflowActionPanel";
import { MaintenanceCostDecisionPanel } from "../maintenance/MaintenanceCostDecisionPanel";
import { ACTION_META, PHASES, currentPhase, workflowActions } from "./decisionWorkspaceModel";
import "./decision-workspace.css";
import { OperationsSystemAdminPage } from "../system/OperationsSystemAdminPage";
import { canReadOperationsSystemLogs } from "../permissions";
import { fieldText, lineLabel, factorLabel, measurement } from "./decisionLabels";
import { DecisionVisuals } from "./DecisionVisuals";
import { DecisionConditions, DecisionProposalPanel, useDecisionProposal } from "./DecisionProposalPanel";

const message = (error: unknown) => error instanceof Error ? error.message : "조회하지 못했습니다. 다시 시도해 주세요.";
export function DecisionWorkspaceApplication({ projectId }: { projectId: string }) {
  const { user } = useAuth();
  return <OperationsSelectionProvider projectId={projectId} defaultRole="process_manager" defaultView="overview" defaultSurface="factory-status" storageScope={`decision:${user?.user_id ?? "anonymous"}`}>
    <Controller projectId={projectId} />
  </OperationsSelectionProvider>;
}
function Controller({ projectId }: { projectId: string }) {
  const { user, logout } = useAuth();
  const { selection, updateSelection } = useOperationsSelection();
  const [model, setModel] = useState<OperationsBootstrapModel | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const selectedRef = useRef(selection.eventId);
  selectedRef.current = selection.eventId;
  const refresh = useCallback(() => setRevision(v => v + 1), []);
  const roles = user?.active_project_roles.length ? user.active_project_roles : user?.roles ?? [];
  const permissions = user?.permissions ?? [];
  const inSystem = selection.view === "system";
  const canReadSystem = canReadOperationsSystemLogs(permissions);
  const inCase = !inSystem && selection.view !== "overview" && Boolean(selection.eventId || selection.assetId);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      setLoading(true);
      try {
        const next = await loadOperationsBootstrap(projectId, selection.workspaceId, selectedRef.current, { allowLocalUiSamples: false });
        if (!disposed) { setModel(next); setError(""); }
      } catch (reason) { if (!disposed) setError(message(reason)); }
      finally {
        if (!disposed) { setLoading(false); timer = setTimeout(() => void load(), 15000); }
      }
    };
    void load();
    return () => { disposed = true; clearTimeout(timer); };
  }, [projectId, selection.workspaceId, revision]);
  const select = (assetId: string, eventId: string | null) => updateSelection({
    assetId, eventId, view: "operations", surface: "decision-case",
    workspaceId: model?.context.workspaceId ?? selection.workspaceId,
  });
  const overview = () => updateSelection({ view: "overview", surface: "factory-status", assetId: null, eventId: null });
  const event = model?.events.find(item => item.eventId === selection.eventId) ?? null;
  const asset = model?.assets.find(item => item.assetId === (event?.assetId ?? selection.assetId)) ?? null;
  return <div className="dw-app">
    <header className="dw-header">
      <button className="dw-brand" onClick={overview}><Factory size={22} /> Ontology Dashboard</button>
      <nav aria-label="주요 화면"><button aria-current={!inCase && !inSystem ? "page" : undefined} onClick={overview}>공장 현황</button>{inCase && <span aria-current="page">이상 건 검토</span>}{canReadSystem && <button aria-current={inSystem ? "page" : undefined} onClick={() => updateSelection({ view: "system", surface: null })}>관리 로그</button>}</nav>
      <div className="dw-account"><span>{user?.display_name}</span><button onClick={() => void logout().then(() => navigate("/login", { replace: true }))} aria-label="로그아웃"><LogOut size={17} /></button></div>
    </header>
    <main>
      <div className="dw-context"><span>{fieldText(model?.context.projectName, "공장 현황")} · {fieldText(model?.context.workspaceName, "조회 중")}</span><button disabled={loading} onClick={refresh}><RefreshCw size={14} />{loading ? "확인 중" : "새로고침"}</button></div>
      {model && <div className="dw-live" role="status"><span className={error ? "is-error" : "is-connected"}>{error ? "연결 확인 필요" : loading ? "최신 상태 확인 중" : "서버 연결됨"}</span><span>자동 조회 · 응답 후 15초</span><span>조회 완료 {formatTimestamp(model.context.refreshedAt)}</span><span>관측 기준 {formatTimestamp(model.context.observedAt)}</span>{model.context.stale && <strong>관측 갱신 지연</strong>}</div>}
      {error && <Notice title="최신 상태 조회 실패" text={error} retry={refresh} />}
      {model?.context.warnings.length ? <details className="dw-warning"><summary>일부 데이터 확인 필요 · {model.context.warnings.length}건</summary>{model.context.warnings.map(w => <p key={w}>{w}</p>)}</details> : null}
      {!model ? <Notice title={loading ? "공장 상태를 불러오고 있습니다" : "표시할 데이터가 없습니다"} /> : inSystem ? (canReadSystem ? <OperationsSystemAdminPage model={model} refreshing={loading} onRefresh={refresh} /> : <Notice title="관리 로그 조회 권한이 필요합니다" />) : inCase ?
        <CaseLoader key={`${projectId}:${model.context.workspaceId}:${selection.eventId ?? selection.assetId}`} projectId={projectId} workspaceId={model.context.workspaceId} event={event} asset={asset} roles={roles} permissions={permissions} userId={user?.user_id ?? ""} revision={revision} onBack={overview} onChanged={refresh} onSelect={select} /> :
        <FactoryOverview model={model} onSelect={select} />}
    </main>
  </div>;
}
function Notice({ title, text, retry }: { title: string; text?: string; retry?: () => void }) {
  return <section className="dw-notice" role="status"><strong>{title}</strong>{text && <p>{text}</p>}{retry && <button onClick={retry}>다시 확인</button>}</section>;
}
function FactoryOverview({ model, onSelect }: { model: OperationsBootstrapModel; onSelect: (assetId: string, eventId: string | null) => void }) {
  const [search, setSearch] = useState("");
  const [attentionOnly, setAttentionOnly] = useState(false);
  const matches = (asset: OperationsAsset) => (!attentionOnly || asset.status !== "normal") && `${asset.assetId} ${asset.displayName} ${asset.line}`.toLowerCase().includes(search.toLowerCase().trim());
  const assets = model.assets.filter(matches);
  const lines = [...new Set(assets.map(a => a.line || "라인 미등록"))];
  const events = model.events.filter(e => e.status !== "normal").slice(0, 8);
  return <>
    <div className="dw-title"><div><small>공장 전체 현황</small><h1>지금 확인할 설비와 이상 건</h1></div><span>최근 관측 · {formatTimestamp(model.context.observedAt)}</span></div>
    <div className="dw-metrics"><Metric label="연결 설비" value={`${model.assets.length}대`} /><Metric label="주의·긴급 설비" value={`${model.metrics.attention + model.metrics.warning + model.metrics.critical}대`} /><Metric label="데이터 확인 필요" value={`${model.metrics.dataQualityHold}대`} /></div>
    <div className="dw-overview"><section className="dw-panel dw-map"><div className="dw-section-title"><h2>설비 상태</h2><label className="dw-filter"><input type="checkbox" checked={attentionOnly} onChange={e => setAttentionOnly(e.target.checked)} />확인 필요만</label></div>
      <label className="dw-search"><Search size={16} /><input aria-label="설비 검색" placeholder="설비명 · 설비 ID · 라인 검색" value={search} onChange={e => setSearch(e.target.value)} /></label>
      {!assets.length && <Notice title="조건에 맞는 설비가 없습니다" />}
      {lines.map(line => <section className="dw-line" key={line}><h3>{lineLabel(line)}</h3><div className="dw-machines">{assets.filter(a => (a.line || "라인 미등록") === line).map(a => <button className={`dw-machine tone-${a.status}`} key={a.assetId} onClick={() => onSelect(a.assetId, a.eventId)}><span className="dw-status">{STATUS_LABEL[a.status]}</span><strong>{displayAssetName(a)}</strong><small>{a.assetId}</small><span>{a.eventId && a.status !== "normal" ? "이상 건 확인 →" : "설비 상태 확인 →"}</span></button>)}</div></section>)}
    </section><section className="dw-panel"><h2>우선 확인할 이상 건</h2>{!events.length && <Notice title="확인할 이상 건이 없습니다" />}{events.map(e => <button className="dw-event" key={e.eventId} onClick={() => onSelect(e.assetId, e.eventId)}><span className={`dw-status tone-${e.status}`}>{STATUS_LABEL[e.status]}</span><strong>{displayEventAssetName(e)}</strong><span>{fieldFailureLabel(e.predictedFailureType)}</span><small>{formatTimestamp(e.observedAt)}</small><ArrowRight size={16} /></button>)}</section></div>
  </>;
}
function Metric({ label, value, children }: { label: string; value: string; children?: ReactNode }) {
  return <div className="dw-metric"><span>{label}</span><strong>{value}</strong>{children}</div>;
}
interface CaseProps {
  projectId: string; workspaceId: string; event: OperationsEvent | null; asset: OperationsAsset | null;
  roles: string[]; permissions: string[]; userId: string; revision: number;
  onBack: () => void; onChanged: () => void; onSelect: (assetId: string, eventId: string | null) => void;
}
function CaseLoader(props: CaseProps) {
  const { projectId, workspaceId, event, asset, revision } = props;
  const [detail, setDetail] = useState<OperationsEventDetailModel | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const eventId = event?.eventId, dataset = event?.datasetVersionId, assetId = event?.assetId;
  useEffect(() => {
    if (!event) { setLoading(false); return; }
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      setLoading(true);
      try {
        const next = await loadDecisionWorkspaceDetail({ projectId, workspaceId, event });
        if (!disposed) { setDetail(next); setError(""); }
      } catch (reason) { if (!disposed) { setDetail(null); setError(message(reason)); } }
      finally { if (!disposed) { setLoading(false); timer = setTimeout(() => void load(), 15000); } }
    };
    void load();
    return () => { disposed = true; clearTimeout(timer); };
  }, [projectId, workspaceId, eventId, dataset, assetId, revision, retry]);
  const back = <button className="dw-back" onClick={props.onBack}><ArrowLeft size={16} />공장 현황</button>;
  if (!event) return <>{back}<Notice title={asset ? displayAssetName(asset) : "선택한 이상 건을 찾을 수 없습니다"} text={asset ? "연결된 이상 건이 없습니다." : "목록을 새로고침하거나 다른 이상 건을 선택해 주세요."} />{asset && <Metric label="설비 상태" value={STATUS_LABEL[asset.status]} />}</>;
  if (!detail) return <>{back}<Notice title={loading ? "판단 근거를 불러오고 있습니다" : "판단 근거 확인 필요"} text={error || undefined} retry={!loading ? () => setRetry(v => v + 1) : undefined} /></>;
  return <>{back}<CaseContent {...props} event={event} detail={detail} refreshing={loading} /></>;
}
export function Briefing({ detail, projectId, canGenerate = false }: { detail: OperationsEventDetailModel; projectId: string; canGenerate?: boolean }) {
  const [response, setResponse] = useState<OperationsAgentReviewSummaryResponse | null>(null);
  const [generating, setGenerating] = useState(false);
  const generate = async () => {
    if (!canGenerate || generating) return;
    setGenerating(true);
    try { setResponse(await createOperationsAgentReviewSummary({ projectId, assetId: detail.event.assetId, eventId: detail.event.eventId, datasetVersionId: detail.event.datasetVersionId, historyWindow: "24h" })); setError(""); }
    catch (reason) { setError(message(reason)); }
    finally { setGenerating(false); }
  };
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const next = await getOperationsAgentReviewSummary({ projectId, assetId: detail.event.assetId, eventId: detail.event.eventId, datasetVersionId: detail.event.datasetVersionId, historyWindow: "24h" });
        if (!disposed) { setResponse(next); setError(""); }
      } catch (reason) { if (!disposed) { setResponse(null); setError(message(reason)); } }
      finally { if (!disposed) timer = setTimeout(() => void load(), 15000); }
    };
    void load();
    return () => { disposed = true; clearTimeout(timer); };
  }, [projectId, detail.event.assetId, detail.event.eventId, detail.event.datasetVersionId]);
  const status = response?.trace.materialization?.status;
  const valid = status === "ready" || status === "fallback";
  const summary = valid && response?.summary?.asset_id === detail.event.assetId
    && Boolean(detail.snapshotBasis?.sourceSha256)
    && response?.trace.materialization?.source_sha256 === detail.snapshotBasis?.sourceSha256
    && !response?.trace.validation_errors.length && !response?.trace.fallback_validation_errors?.length
    && detail.evidenceContext?.temporalStatus !== "stale" && !detail.assetDetailStatus?.isStale ? response?.summary : null;
  return <section className="dw-briefing"><h3>{summary?.mode === "llm" ? "AI 근거 설명" : "근거 요약"}</h3>{canGenerate && <button disabled={generating} onClick={() => void generate()}>{generating ? "근거 설명 생성 중" : "근거 설명 생성"}</button>}<p>{summary?.summary ?? (error ? "요약을 불러오지 못했습니다. 아래 원문 근거를 확인해 주세요." : response ? "현재 근거에 맞는 요약이 준비되지 않았습니다." : "근거 요약을 확인하고 있습니다.")}</p>{summary?.evidence_gaps.slice(0, 2).map(g => <p key={g.field}>확인 필요 · {fieldText(g.reason)}</p>)}</section>;
}
function CaseContent(props: CaseProps & { detail: OperationsEventDetailModel; event: OperationsEvent; refreshing: boolean }) {
  const { detail, asset, roles, permissions, projectId, workspaceId, userId, onChanged, refreshing } = props;
  const event = detail.event;
  const [dialog, setDialog] = useState<string | null>(null);
  const [formVersion, setFormVersion] = useState(0);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const actionOpener = useRef<HTMLElement | null>(null);
  const [decisionRevision, setDecisionRevision] = useState(0);
  const actions = workflowActions(detail, roles, permissions);
  const proposalState = useDecisionProposal({ projectId, workspaceId, eventId: event.eventId, assetId: event.assetId }, detail, roles, `${userId}:${decisionRevision}`);
  const phase = currentPhase(detail);
  const impact = detail.operationContext?.eventImpact;
  const lastInspection = detail.closedLoop?.inspectionResults.at(-1);
  const role: OperationsRoleLens = dialog && ACTION_META[dialog]?.role === "process_manager" ? "process_manager" : "field_operator";
  const canManage = roles.includes("process_manager") && permissions.includes("events.decision");
  const canExecute = (roles.includes("process_engineer") || roles.includes("maintenance_technician")) && permissions.includes("field.tasks.update");
  const reviewBasis = JSON.stringify([detail.snapshotBasis, detail.closedLoop?.availableActions, roles, permissions, proposalState]);
  const [openedBasis, setOpenedBasis] = useState("");
  useEffect(() => {
    if (dialog) dialogRef.current?.showModal();
    else if (dialogRef.current?.open) dialogRef.current.close();
  }, [dialog]);
  const close = () => { setDialog(null); actionOpener.current?.focus(); };
  const open = (id: string) => { actionOpener.current = document.activeElement as HTMLElement; setOpenedBasis(reviewBasis); setDialog(id); };
  const chosen = openedBasis === reviewBasis ? actions.find(a => a.actionId === dialog) : undefined;
  const changed = () => { setFormVersion(v => v + 1); onChanged(); };
  const reason = detail.evidenceGaps.find(g => g.field === "canonical_evidence")?.reason ?? detail.closedLoop?.primaryAction?.disabledReason;
  return <>
    <div className="dw-title"><div><small title={event.eventId}>{lineLabel(event.line)} · 이상 건 검토</small><h1>{displayEventAssetName(event)}</h1><p>{fieldFailureLabel(event.predictedFailureType)} · {formatTimestamp(event.observedAt)}</p></div><span className={`dw-status tone-${event.status}`}>{STATUS_LABEL[event.status]}</span></div>
    <ol className="dw-flow" aria-label="이상 건 진행 상태">{PHASES.map((label, i) => <li key={label} aria-current={phase === i ? "step" : undefined}><span>{i + 1}</span>{label}</li>)}</ol>
    <div className="dw-case-grid"><section className="dw-panel"><h2>현재 상황</h2><p className="dw-muted">진행 단계 · {phase === null ? "확인 필요" : PHASES[phase]}</p>
      <Metric label="고장 위험도" value={formatProbability(event.failureProbability)}><small>{detail.predictionHorizonHours ? `예측 범위 · ${detail.predictionHorizonHours}시간` : "예측 범위 확인 필요"}</small></Metric>
      <Metric label="생산 영향" value={impact?.impactStatus === "estimated" && impact.estimatedLostUnits !== null ? `${impact.estimatedLostUnits.toLocaleString()}개 예상 손실` : "산정 정보 없음"}>{impact?.impactStatus === "estimated" && <small>산정 기준 · 정지 {impact.basis.estimatedDowntimeMinutes}분</small>}</Metric>
      <Metric label="점검 담당" value={fieldText(detail.closedLoop?.workOrders.filter(w => w.workType === "inspection").at(-1)?.assignedTo || event.assignedEngineer, "배정 대기")} />
      <p className="dw-muted">최근 관측 · {formatTimestamp(detail.assetDetailStatus?.lastUpdatedAt ?? event.observedAt)}</p>
    </section><section className="dw-panel"><h2>판단 조건과 근거</h2>
      <Condition label="현장 점검" value={lastInspection ? ({ maintenance_recommended: "정비 검토 필요", no_action_required: "추가 정비 불필요", data_check_required: "추가 데이터 확인 필요" }[lastInspection.outcome] ?? lastInspection.outcome) : "점검 결과 없음"} />
      <Condition label="부품 가용 정보" value={event.sparePartAvailable === true ? "가용 · 예약 확인 필요" : event.sparePartAvailable === false ? "가용 부품 없음" : "확인 필요"} />
      <Condition label="진행 상태" value={phase === null ? "상태 확인 필요" : PHASES[phase]} />
      {detail.topFactors.slice(0, 3).map(f => <Condition key={f.id} label={factorLabel(f.feature, f.label)} value={measurement(f.value, f.unit)} />)}
      <DecisionConditions state={proposalState} detail={detail} />
      <details className="dw-evidence"><summary>연결 근거 · 출처와 시각 확인</summary>{detail.evidenceContext?.selectedBasis.map(b => <article key={b.candidateId}><strong>{fieldText(b.valueSummary)}</strong><p>{b.sourceRef} · {formatTimestamp(b.asOf)}</p>{b.limitationState && <p>{fieldText(b.limitationState)}</p>}</article>)}{!detail.evidenceContext?.selectedBasis.length && detail.provenance.sourceRefs.map(ref => <p key={ref}>{ref}</p>)}{detail.evidenceContext?.limitations.map(l => <p key={l}>{fieldText(l)}</p>)}</details>
    </section><aside className="dw-panel dw-next"><DecisionProposalPanel state={proposalState} detail={detail} roles={roles} permissions={permissions} refreshing={refreshing} onReview={open} onRetry={() => { onChanged(); setDecisionRevision(v => v + 1); }} />
      <section className="dw-workflow" aria-label="기존 업무 실행"><h2>업무 처리</h2><p className="dw-muted">현재 업무 단계에서 가능한 요청·작업입니다. 내용을 확인하고 직접 승인해 주세요.</p>
      {detail.closedLoop?.primaryAction && <p>{fieldText(detail.closedLoop.primaryAction.ownerLabel)}</p>}
      {actions.length ? actions.map((a, i) => <div key={a.actionId}><button className={i === 0 ? "dw-primary" : ""} disabled={Boolean(a.reason) || refreshing} onClick={() => open(a.actionId)}>{a.label}<ArrowRight size={16} /></button>{a.reason && <p className="dw-muted">{fieldText(a.reason)}</p>}</div>) : <p>{reason || (phase === 4 ? "조치 후 관측과 상태 확인 결과를 기다리고 있습니다." : "현재 실행 가능한 조치가 없습니다. 담당자의 확인을 기다리고 있습니다.")}</p>}
      {refreshing && <small role="status">최신 조치 조건 확인 중</small>}
      </section>
      {asset?.eventId && asset.eventId !== event.eventId && <div className="dw-new-event"><p>이 설비의 새로운 판단 결과가 있습니다.</p><button onClick={() => props.onSelect(asset.assetId, asset.eventId)}>새 판단 결과 확인</button></div>}
    </aside></div>
    <DecisionVisuals detail={detail} />
    <details className="dw-history"><summary>처리 이력 · {detail.closedLoop?.timeline.length ?? 0}건</summary>{detail.closedLoop?.timeline.map(t => <article key={t.timelineId}><strong>{t.label}</strong><span>{t.actorDisplayName ?? ""}</span><time>{formatTimestamp(t.occurredAt ?? null)}</time></article>)}{!detail.closedLoop?.timeline.length && <p>등록된 처리 이력이 없습니다.</p>}</details>
    <details className="dw-history"><summary>센서 관측 · {detail.sensors.length}개</summary><div className="dw-sensors">{detail.sensors.map(s => <Metric key={s.id} label={factorLabel(s.id, s.label)} value={measurement(s.value, s.unit)} />)}</div></details>
    <dialog className="dw-dialog" ref={dialogRef} onCancel={close} onClose={close}><header><h2>{chosen?.label ?? "조치 조건 확인"}</h2><button onClick={close} aria-label="닫기">닫기</button></header>
      {dialog && chosen && !chosen.reason ? chosen.actionId === "calculate_maintenance_cost" ?
        <MaintenanceCostDecisionPanel key={`${event.eventId}:${chosen.targetId}:${formVersion}`} permittedInspectionId={chosen.targetId} blocked={refreshing} projectId={projectId} workspaceId={workspaceId} eventId={event.eventId} guidance={detail.inspectionTargets.find(t => t.inspectionGuidance)?.inspectionGuidance ?? null} onChanged={changed} /> :
        <MaintenanceWorkflowActionPanel key={`${event.eventId}:${formVersion}`} projectId={projectId} workspaceId={workspaceId} datasetVersionId={event.datasetVersionId} eventId={event.eventId} assetId={event.assetId} assetType={asset?.assetType ?? ""} role={role} currentUserId={userId} snapshotBasis={detail.snapshotBasis} canManage={canManage && !refreshing} canFieldExecute={canExecute && !refreshing} permittedActions={[chosen]} onChanged={onChanged} /> :
        <Notice title="조치 조건이 변경되었습니다" text="최신 상태를 확인한 뒤 다시 선택해 주세요." />}
    </dialog>
  </>;
}
function Condition({ label, value }: { label: string; value: string }) {
  return <div className="dw-condition"><span>{label}</span><strong>{value}</strong></div>;
}

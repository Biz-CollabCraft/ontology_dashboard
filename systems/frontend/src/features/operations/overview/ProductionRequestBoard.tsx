import { LogOut } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { getMaintenanceEventLineage, listInspectionCoordinations, respondInspectionCoordination,
  type InspectionCoordination, type MaintenanceCostAnalysisReadModel, type OpenInspectionWorkOrderReadModel } from "../../../api";
import { loadOperationsAssetDetail } from "../api/operationsApi";
import type { AssetDetailViewModel, OperationsAsset, OperationsBootstrapModel } from "../api/operationsContracts";
import { displayEquipmentSensorLabel } from "../displayLabels";
import { OperationsAccountBadge } from "./OperationsAccountBadge";
import { amount, matchingCostAnalysis, numeric, productionQueue, queueStatus, type ProductionQueueItem } from "./productionRequestModel";
import "./ProductionRequestBoard.css";

type Props = {
  projectId: string; workspaceId: string; model: OperationsBootstrapModel; workOrders: OpenInspectionWorkOrderReadModel[];
  workOrderError: boolean; currentUser: { displayName: string; title: string };
  onRefresh: () => void; onLogout: () => void | Promise<void>;
};
const number = (n: number | null | undefined, unit: string) => numeric(n) ? n.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) + unit : "미산정";
const when = (value: string | null | undefined) => value ? new Date(value).toLocaleString("ko-KR") : "시각 정보 없음";
const outcome = { no_action_required: "추가 조치 불필요", maintenance_recommended: "정비 필요", data_check_required: "추천 정보 확인 대기" };
const timing = { immediate: "즉시 정비", planned_window: "계획 시간 정비", reinspect_after: "후속 점검", no_action_baseline: "조치하지 않음" };

export function ProductionRequestBoard({ projectId, workspaceId, model, workOrders, workOrderError, currentUser, onRefresh, onLogout }: Props) {
  const [consultations, setConsultations] = useState<InspectionCoordination[]>([]);
  const [queueError, setQueueError] = useState(false);
  const [queueLoading, setQueueLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [statusFilter, setStatusFilter] = useState<"active" | "completed" | "all">("active");
  const [detailOpen, setDetailOpen] = useState(false);
  const [context, setContext] = useState<{ key: string; detail: AssetDetailViewModel | null; costs: MaintenanceCostAnalysisReadModel | null; detailError: boolean; costError: boolean; detailLoading: boolean; costLoading: boolean } | null>(null);
  useEffect(() => {
    let alive = true, inflight = false;
    async function load() {
      if (inflight) return;
      inflight = true;
      try {
        const result = await listInspectionCoordinations({ projectId, workspaceId });
        if (alive) { setConsultations(result.items); setQueueError(false); }
      } catch { if (alive) setQueueError(true); }
      finally { inflight = false; if (alive) setQueueLoading(false); }
    }
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => { alive = false; clearInterval(timer); };
  }, [projectId, workspaceId, revision]);
  const queue = productionQueue(workOrders, consultations);
  const visible = queue.filter(item => statusFilter === "all" || (statusFilter === "completed" ? item.status === "completed" : item.status !== "completed"));
  const selected = visible.find(item => item.id === selectedId) ?? visible[0] ?? null;
  const asset = model.assets.find(item => item.assetId === selected?.assetId) ?? null;
  const requestKey = selected ? [projectId, workspaceId, selected.id, selected.eventId, selected.coordination?.request_id ?? "", model.context.datasetVersionId].join("|") : "";
  useEffect(() => {
    let alive = true;
    setDetailOpen(false);
    if (!selected) { setContext(null); return; }
    const selection = selected;
    setContext({ key: requestKey, detail: null, costs: null, detailError: false, costError: false, detailLoading: true, costLoading: true });
    const update = (fields: Partial<NonNullable<typeof context>>) => {
      if (alive) setContext(current => current?.key === requestKey ? { ...current, ...fields } : current);
    };
    // These independent reads never hold up the queue or approval controls.
    void loadOperationsAssetDetail(projectId, workspaceId, selection.assetId, selection.eventId, model.context.datasetVersionId, "24h")
      .then(detail => {
        if (detail.asset.asset_id !== selection.assetId) throw new Error("mismatched asset");
        update({ detail, detailLoading: false });
      }).catch(() => update({ detail: null, detailError: true, detailLoading: false }));
    void getMaintenanceEventLineage(projectId, workspaceId, selection.eventId)
      .then(data => update({ costs: matchingCostAnalysis(data.cost_analyses ?? [], selection), costLoading: false }))
      .catch(() => update({ costs: null, costError: true, costLoading: false }));
    return () => { alive = false; };
  }, [requestKey, revision]);
  const active = context?.key === requestKey ? context : null;
  const detail = active?.detail ?? null;
  const cost = active?.costs ?? null;
  const c = selected?.coordination;
  const name = detail?.asset.display_name || asset?.displayName || selected?.assetId || "정비 요청 선택";
  const refresh = useCallback(() => { setRevision(n => n + 1); onRefresh(); }, [onRefresh]);
  const onSaved = (updated: InspectionCoordination) => {
    setConsultations(items => items.map(item => item.work_order_id === updated.work_order_id ? { ...item, ...updated } : item));
    refresh();
  };
  const info = detail?.operation_context;
  const rate = info?.capacity_model?.asset_units_per_hour;
  const requestedLoss = c && numeric(rate) && rate >= 0 ? Math.ceil(rate * c.request.downtime_minutes / 60) : null;
  const awaiting = queue.filter(item => item.coordination?.status === "pending" && item.status === "approved").length;
  return <main className="engineer-lite-board production-request-board">
    <header className="engineer-factory-header">
      <div><strong>생산 대응 현황</strong><span>{model.context.workspaceName} · 정비 요청의 생산 영향과 작업 일정 협의</span></div>
      <div className="engineer-factory-live"><b>{queueLoading ? "연결 확인 중" : queueError || workOrderError ? "요청 연결 확인 필요" : "요청 연결 정상"}</b><button type="button" onClick={refresh}>↻ 새로고침</button><OperationsAccountBadge {...currentUser}/><button type="button" onClick={() => void onLogout()}><LogOut size={14}/> 로그아웃</button></div>
    </header>
    <section className="prb-kpis" aria-label="정비 요청 현황">
      <Metric label="작업 승인 대기" value={queueLoading ? "조회 중" : number(awaiting, "건")}/>
      <Metric label="진행 중 정비 요청" value={number(queue.filter(item => item.status !== "completed").length, "건")}/>
      <Metric label="협의 요청 정지 시간 합계" value={number(queue.filter(item => item.status !== "completed").reduce((sum,item) => sum + (item.coordination?.request.downtime_minutes ?? 0), 0), "분")}/>
    </section>
    <div className="prb-columns">
      <section className="prb-card prb-queue" aria-label="정비 요청 큐">
        <header><strong>정비 요청 큐</strong><div className="prb-queue-tools"><span>시간순</span><select aria-label="정비 요청 상태" value={statusFilter} onChange={e => setStatusFilter(e.target.value as typeof statusFilter)}><option value="active">진행 중</option><option value="completed">완료</option><option value="all">전체</option></select></div></header>
        <div className="prb-scroll">
          {queueError || workOrderError ? <p role="status">요청 연결을 확인해 주세요. 이전 표시 내용은 유지되며 승인은 잠깁니다.</p> : null}
          {visible.map(item => <button type="button" className="prb-queue-item" key={item.id} aria-pressed={selected?.id === item.id} onClick={() => { setSelectedId(item.id); setDetailOpen(false); }}>
            <strong>{model.assets.find(a => a.assetId === item.assetId)?.displayName ?? item.assetId}</strong>
            <span>#{item.id.slice(-8)} · {queueStatus(item)}</span><span>담당 {item.assignee}</span>
            <small>{item.coordination ? when(item.requestedAt) : "생산 협의 요청 전"}</small>
          </button>)}
          {!visible.length ? <p>{queueLoading ? "정비 요청 조회 중" : "현재 정비 요청이 없습니다."}</p> : null}
        </div>
      </section>
      <section className="prb-card prb-review" aria-label="생산 대응 검토">
        <header><strong>생산 대응 검토</strong><span>{name}</span></header>
        {selected ? <>
          <div className="prb-scroll prb-review-top">
            <ImpactSummary name={name} item={selected} detail={detail} requestedLoss={requestedLoss} loading={!active || active.detailLoading}/>
            {active?.detailError ? <p role="status">생산 영향 연결 확인 필요 · 다른 장비의 수치로 대체하지 않습니다.</p> : null}
            <CostComparison analysis={cost} loading={!active || active.costLoading} error={active?.costError ?? false}/>
          </div>
          <RiskChart asset={asset} detail={detail} name={name}/>
        </> : <p className="prb-empty">정비 요청을 선택하면 해당 장비의 손익과 생산 영향을 표시합니다.</p>}
      </section>
      <aside className="prb-card prb-actions" aria-label="다음 행동">
        <header><strong>다음 행동</strong><span>생산 대응·작업 승인</span></header>
        {selected ? <ApprovalPanel key={selected.id + ":" + (c?.request_id ?? "")} item={selected} name={name} projectId={projectId} workspaceId={workspaceId}
          requestedLoss={requestedLoss} cost={cost} connected={!queueLoading && !queueError && !workOrderError}
          onImpact={() => setDetailOpen(true)} onSaved={onSaved}/> : <p>왼쪽에서 정비 요청을 선택해 주세요.</p>}
      </aside>
    </div>
    {selected && detailOpen ? <div className="prb-overlay" onClick={() => setDetailOpen(false)}><section role="dialog" aria-modal="true" aria-label={name + " 생산 영향 상세"} className="prb-dialog" tabIndex={-1} onKeyDown={e => { if (e.key === "Escape") setDetailOpen(false); }} onClick={e => e.stopPropagation()}>
      <header><div><strong>{name} · 개별 영향 확인</strong><span>{selected.assetId} · #{selected.id.slice(-8)}</span></div><button type="button" autoFocus aria-label="생산 영향 상세 닫기" onClick={() => setDetailOpen(false)}>×</button></header>
      <div className="prb-scroll">
        <ImpactSummary name={name} item={selected} detail={detail} requestedLoss={requestedLoss} loading={!active || active.detailLoading}/>
        <CostComparison analysis={cost} loading={!active || active.costLoading} error={active?.costError ?? false}/>
        <section className="prb-basis"><h3>생산 영향 산정 근거</h3><p>계획 기준일: {info?.production_plan?.plan_date ?? "정보 없음"} · 대상 품목: {info?.event_impact?.product_variant ?? "미연결"}</p>
          <p>설비 시간당 생산능력: {number(rate, "개/시간")} · 요청 정지 예상 손실: 시간당 생산능력 × 요청 정지 시간 ÷ 60 (올림)</p>
          <p>가동률과 품목 구성이 동일하다는 가정의 수량입니다. 재고·대체 생산을 반영한 최종 부족분이나 매출 손실이 아닙니다.</p>
          <p>데이터 유효 기간: {when(info?.temporal_scope?.valid_from)} ~ {when(info?.temporal_scope?.valid_to)}</p>
          <p>출처: {info?.source_type ?? "미확인"} · {info?.capacity_model?.basis ?? "생산능력 근거 미연결"}</p>
          {info?.limitations?.map((text,i) => <p key={i}>{text}</p>)}
        </section>
        <div className="prb-detail-charts"><RiskChart asset={asset} detail={detail} name={name}/><section><h3>장비 센서별 영향 근거</h3>
          {detail?.features?.length ? detail.features.map(feature => <div className="prb-sensor" key={feature.key}><strong>{displayEquipmentSensorLabel(selected.assetId, feature.key, feature.label)}</strong><span>{number(feature.current.value, " " + feature.unit)}</span><p>관측: {when(feature.current.observed_at)} · {feature.current.quality_status === "good" ? "관측 정상" : "품질 확인 필요"}</p><SensorTrend feature={feature}/></div>) : <p>센서 근거 조회 필요</p>}
        </section></div>
      </div>
    </section></div> : null}
  </main>;
}
function SensorTrend({ feature }: { feature: AssetDetailViewModel["features"][number] }) {
  const points = feature.history.points;
  const values = points.filter(p => numeric(p.value) && p.quality_status === "good").map(p => p.value as number);
  if (!values.length) return <p>유효한 센서 추이 없음</p>;
  const min = Math.min(...values), max = Math.max(...values), range = Math.max(max - min, Math.abs(max) * .08, 1);
  let gap = true;
  const path = points.map((p,i) => {
    if (!numeric(p.value) || p.quality_status !== "good") { gap = true; return ""; }
    const command = gap ? "M" : "L"; gap = false;
    return command + (i * 100 / Math.max(1,points.length - 1)) + "," + (92 - (p.value - min) / range * 84);
  }).join(" ");
  return <><svg className="prb-sensor-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={feature.label + " 센서 추이"}><path d={path}/></svg><small>{when(points[0]?.observed_at)} ~ {when(points.at(-1)?.observed_at)}</small></>;
}
function Metric({ label, value }: { label: string; value: string }) { return <article className="prb-metric"><span>{label}</span><strong>{value}</strong></article>; }
function ImpactSummary({ name, item, detail, requestedLoss, loading }: { name: string; item: ProductionQueueItem; detail: AssetDetailViewModel | null; requestedLoss: number | null; loading: boolean }) {
  const c = item.coordination;
  return <section className="prb-impact-summary"><h3>{name} · 생산 영향 요약</h3><p>{c?.request.work_summary ?? "보전팀에서 작업 내용과 정지 시간을 작성하기 전입니다."}</p>
    <div className="prb-metric-grid"><Metric label="요청 정지 시간" value={number(c?.request.downtime_minutes, "분")}/><Metric label="요청 정지 예상 손실" value={loading ? "조회 중" : number(requestedLoss, "개")}/><Metric label="기존 고장 예측 손실" value={loading ? "조회 중" : number(detail?.operation_context.event_impact?.estimated_lost_units, "개")}/><Metric label="일일 생산 계획" value={loading ? "조회 중" : number(detail?.operation_context.production_plan?.planned_units, "개")}/></div>
    <p>협의 영향 품목: {c?.request.affected_items ?? "미작성"} · 요청 메모: {c?.request.note || "없음"}</p>
    <small>요청 시간 기준 손실과 기존 고장 예측 손실은 별도 시나리오이며 합산하지 않습니다.</small>
  </section>;
}
function CostComparison({ analysis, loading, error }: { analysis: MaintenanceCostAnalysisReadModel | null; loading: boolean; error: boolean }) {
  return <section className="prb-cost"><h3>손익·비용 대조</h3>
    {analysis ? <><p>저장된 산정: {when(analysis.calculated_at)} · {analysis.price_version}</p><div className="prb-table-scroll"><table><thead><tr><th>대응 시점</th><th>정비 직접비</th><th>생산 손실액</th><th>예상 고장 손실</th><th>총 예상 비용</th><th>미조치 대비 비용 절감</th></tr></thead><tbody>{analysis.options.map(option => {
      const baseline = analysis.options.find(o => o.action_candidate_id === option.action_candidate_id && o.execution_timing === "no_action_baseline" && o.calculation_status === "calculated");
      const direct = [option.parts_cost?.base_minor, option.labor_cost?.base_minor, option.external_service_cost?.base_minor];
      const total = option.calculation_status === "calculated" ? option.total_expected_cost?.base_minor : null;
      const savings = numeric(total) && numeric(baseline?.total_expected_cost?.base_minor) ? baseline.total_expected_cost.base_minor - total : null;
      return <tr key={option.option_id}><th>{timing[option.execution_timing]}<small>{option.action_code === "TOOL_REPLACEMENT" ? "공구 교체" : "냉각 계통 복구"} · {when(option.assumed_execution_at)}</small></th>
        <td>{amount(direct.every(numeric) ? direct.reduce((s,n) => s + n, 0) : null, analysis)}</td><td>{amount(option.production_loss?.base_minor, analysis)}</td><td>{amount(option.expected_failure_loss?.base_minor, analysis)}</td>
        <td>{amount(total, analysis)}<small>{option.total_expected_cost ? amount(option.total_expected_cost.low_minor, analysis) + " ~ " + amount(option.total_expected_cost.high_minor, analysis) : "산정 조건 부족"}</small></td><td>{amount(savings, analysis)}</td></tr>;
    })}</tbody></table></div><p>산정 시점의 가정별 예상 비용입니다. 요청 정지 시간으로 재계산한 금액이나 확정 견적·보장 수익이 아닙니다. 음수 절감액은 비용 증가를 뜻합니다.</p><details><summary>산정 조건·제약 확인</summary>{analysis.assumptions.map((text,i) => <p key={i}>{text}</p>)}<p>산정 미비 항목: {analysis.missing_inputs.join(", ") || "없음"}</p></details></>
      : <p role="status">{loading ? "비용 산정 이력 조회 중" : error ? "비용 조회 연결 확인 필요" : "이 정비 요청에 연결된 비용 산정 결과가 없습니다. 보전팀 점검·조치안 산정 후 비교할 수 있습니다."}</p>}
    <p className="prb-muted">매출·영업이익: 미산정 — 품목 단가·변동비·대체 생산 기준이 필요합니다. 비용 절감액을 영업이익으로 표시하지 않습니다.</p>
  </section>;
}
function RiskChart({ asset, detail, name }: { asset: OperationsAsset | null; detail: AssetDetailViewModel | null; name: string }) {
  const values = detail?.risk_series.length ? detail.risk_series.map(p => p.failure_probability) : asset?.riskHistory?.map(p => p.value) ?? [];
  const current = detail ? detail.risk.current : asset?.failureProbability;
  const coords = values.map((n,i) => `${values.length === 1 ? 50 : i * 100 / (values.length - 1)},${100 - Math.max(0, Math.min(1,n)) * 100}`);
  return <section className="prb-risk"><header><div><strong>위험 점수 추세 · 최근 관측</strong><span>{name}</span></div><b>{numeric(current) ? Math.round(current * 100) + "%" : "정보 없음"}</b></header>
    {values.length ? <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={name + " 위험 점수 추세"}><rect width="100" height="38" className="risk-zone"/><rect y="38" width="100" height="20" className="attention-zone"/><rect y="58" width="100" height="42" className="normal-zone"/><line x2="100" y1="38" y2="38"/><line x2="100" y1="58" y2="58"/>{values.length > 1 ? <polyline points={coords.join(" ")}/> : <circle cx="50" cy={100-values[0]*100} r="1"/>}</svg> : <p>연결된 위험 관측 이력이 없습니다.</p>}
    <footer><span>이전 관측</span><small>{detail ? when(detail.asset.observed_at) : "현재 설비 관측 · 요청 시점과 다를 수 있음"}</small><span>현재</span></footer>
  </section>;
}
function ApprovalPanel({ item, name, projectId, workspaceId, requestedLoss, cost, connected, onImpact, onSaved }: {
  item: ProductionQueueItem; name: string; projectId: string; workspaceId: string; requestedLoss: number | null;
  cost: MaintenanceCostAnalysisReadModel | null; connected: boolean; onImpact: () => void; onSaved: (value: InspectionCoordination) => void;
}) {
  const c = item.coordination;
  const [schedule, setSchedule] = useState("");
  const [response, setResponse] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const locked = useRef(false);
  const retry = useRef<{ fingerprint: string; key: string } | null>(null);
  const canApprove = connected && c?.status === "pending" && item.status === "approved";
  const totals = cost?.options.filter(option => option.calculation_status === "calculated").map(option => option.total_expected_cost?.base_minor).filter(numeric) ?? [];
  const costSummary = cost && totals.length ? amount(Math.min(...totals), cost) + " ~ " + amount(Math.max(...totals), cost) : "미산정";
  async function submit(decision: "confirmed" | "changes_requested") {
    if (!c || !canApprove || locked.current || !schedule.trim() || !response.trim()) return;
    const payload = { request_id: c.request_id, decision, scheduled_window: schedule.trim(), production_response: response.trim() };
    const fingerprint = JSON.stringify(payload);
    if (retry.current?.fingerprint !== fingerprint) retry.current = { fingerprint, key: Array.from(crypto.getRandomValues(new Uint32Array(4)), v => v.toString(16).padStart(8,"0")).join("") };
    locked.current = true; setBusy(true); setMessage("");
    try {
      const result = await respondInspectionCoordination({ projectId, workspaceId, workOrderId: item.id, payload, idempotencyKey: retry.current.key });
      onSaved(result as unknown as InspectionCoordination); setMessage(decision === "confirmed" ? "작업 승인을 저장했습니다. 보전팀에서 착수 조건 확인 후 작업을 시작할 수 있습니다." : "재협의 요청을 저장했습니다.");
    } catch { setMessage("저장하지 못했습니다. 입력 내용은 유지됩니다. 연결과 최신 요청 상태를 확인해 주세요."); }
    finally { locked.current = false; setBusy(false); }
  }
  return <><div className="prb-scroll prb-action-summary"><h3>{name}</h3><p>#{item.id.slice(-8)} · {queueStatus(item)}</p><p>담당: {item.assignee}</p>
    <dl><dt>협의 작업</dt><dd>{c?.request.work_summary ?? "보전팀 협의 요청 대기"}</dd><dt>정지 시간 / 영향 품목</dt><dd>{number(c?.request.downtime_minutes, "분")} / {c?.request.affected_items ?? "미작성"}</dd><dt>요청 정지 예상 손실</dt><dd>{number(requestedLoss, "개")} (생산능력 가정)</dd><dt>시나리오별 총비용 범위</dt><dd>{costSummary} (각 시나리오 기준값 비교)</dd><dt>손익 근거</dt><dd>{cost ? "동일 요청의 비용 비교 " + when(cost.calculated_at) : "비용 미산정 · 확정 손익 판단 불가"}</dd></dl>
    {c?.response ? <section className="prb-saved"><b>{c.status === "confirmed" ? "작업 승인 완료" : "재협의 요청"}</b><p>{c.responded_by_name} · {when(c.responded_at)}</p><p>{c.response.scheduled_window}</p><p>{c.response.production_response}</p></section> : null}
    {c?.inspection_result ? <section className="prb-saved"><b>점검 결과: {outcome[c.inspection_result.outcome]}</b>{c.inspection_result.findings.map((text,i) => <p key={i}>{text}</p>)}<p>{c.inspection_result.note}</p></section> : null}
    {c?.history?.length ? <details><summary>협의·승인 이력 {c.history.length}건</summary>{c.history.map((h,i) => <p key={i}>{when(h.responded_at || h.requested_at)} · {h.responded_by_name || h.requested_by_name} · {h.response?.scheduled_window || h.request.work_summary} · {h.response?.production_response || h.request.note}</p>)}</details> : null}
    {canApprove ? <><label>작업·정지 일정<input maxLength={1000} value={schedule} onChange={e=>setSchedule(e.target.value)} disabled={busy} placeholder="날짜·시각 또는 무정지 작업"/></label><label>생산 대응·승인 근거<textarea maxLength={4000} value={response} onChange={e=>setResponse(e.target.value)} disabled={busy} placeholder="대체 생산, 납기 대응 또는 재협의 사유"/></label></> : <p>{connected ? "생산 협의 요청이 접수된 항목만 승인할 수 있습니다." : "요청 연결 확인 후 승인할 수 있습니다."}</p>}
    <p role="status">{message}</p>
  </div><div className="prb-action-buttons"><button type="button" onClick={onImpact}>선택 설비 영향 확인</button>
    <button type="button" className="prb-approve" disabled={!canApprove || busy || !schedule.trim() || !response.trim()} onClick={() => void submit("confirmed")}>{busy ? "저장 중…" : c?.status === "confirmed" ? "작업 승인 완료" : "작업 승인"}</button>
    {canApprove ? <button type="button" disabled={busy || !schedule.trim() || !response.trim()} onClick={() => void submit("changes_requested")}>재협의 요청</button> : null}
    <small>작업 승인은 생산 일정 확인입니다. 보전팀의 착수 조건 확인을 대체하지 않습니다.</small></div></>;
}

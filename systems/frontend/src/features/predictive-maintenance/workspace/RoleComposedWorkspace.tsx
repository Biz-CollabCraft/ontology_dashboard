import {
  Activity,
  AlertTriangle,
  Boxes,
  BriefcaseBusiness,
  Building2,
  ChartNoAxesCombined,
  CircleDollarSign,
  ClipboardCheck,
  FileClock,
  FileText,
  Gauge,
  GitBranch,
  History,
  ListChecks,
  PackageSearch,
  RadioTower,
  ShieldAlert,
  TimerReset,
  TrendingDown,
  Wrench,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import {
  createOperationsAgentReviewSummary,
  getOperationsAgentReviewSummary,
} from "../../../api";
import type {
  OperationsAgentReviewSummaryResponse,
  OperationsAsset,
  OperationsBootstrapModel,
  OperationsCompanyContext,
  OperationsEvent,
  OperationsEventDetailModel,
  OperationsReportTab,
  OperationsRoleLens,
  OperationsView,
} from "../../operations/api/operationsContracts";
import { MaintenanceWorkflowActionPanel } from "../../operations/maintenance/MaintenanceWorkflowActionPanel";
import type { ReliabilityExperienceKind } from "./roleExperience";
import { resolveReliabilityComposition, type ReliabilityBlockId } from "./roleComposition";
import "./role-composed-workspace.css";

interface RoleComposedWorkspaceProps {
  experienceKind: ReliabilityExperienceKind;
  view: OperationsView;
  surfaceId: string | null;
  model: OperationsBootstrapModel;
  selectedEvent: OperationsEvent | null;
  detail: OperationsEventDetailModel | null;
  companyContext: OperationsCompanyContext | null;
  role: OperationsRoleLens;
  canManageWorkflow: boolean;
  canExecuteFieldWorkflow: boolean;
  canMaterializeAgentSummary: boolean;
  onSelectEvent: (event: OperationsEvent) => void;
  onOpenAsset: (assetId: string, eventId: string | null) => void;
  onOpenReport: (eventId: string | null, assetId: string | null, reportTab?: OperationsReportTab) => void;
  onWorkflowChanged: () => void;
}

function Block({ title, eyebrow, icon, className = "", children }: {
  title: string;
  eyebrow?: string;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return <section className={`rw-composed-block ${className}`}>
    <header>{icon}<div>{eyebrow ? <span>{eyebrow}</span> : null}<strong>{title}</strong></div></header>
    <div className="rw-composed-block__body">{children}</div>
  </section>;
}

function probability(value: number | null | undefined) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function money(value: number | null | undefined) {
  return typeof value === "number" ? `${Math.round(value).toLocaleString("ko-KR")}원` : "—";
}

function compactMoney(value: number | null | undefined) {
  if (typeof value !== "number") return "—";
  if (Math.abs(value) >= 100_000_000) return `${(value / 100_000_000).toFixed(1)}억원`;
  if (Math.abs(value) >= 10_000) return `${Math.round(value / 10_000).toLocaleString("ko-KR")}만원`;
  return money(value);
}

function dateTime(value: string | null | undefined) {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}

function minutesBetween(start: string | null | undefined, end: string | null | undefined): number | null {
  if (!start || !end) return null;
  const startMs = new Date(start).getTime();
  const endMs = new Date(end).getTime();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) return null;
  return Math.round((endMs - startMs) / 60_000);
}

function duration(value: number | null | undefined) {
  if (typeof value !== "number") return "근거 없음";
  if (value < 60) return `${value}분`;
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return minutes ? `${hours}시간 ${minutes}분` : `${hours}시간`;
}

function average(values: Array<number | null | undefined>): number | null {
  const numeric = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (!numeric.length) return null;
  return numeric.reduce((sum, value) => sum + value, 0) / numeric.length;
}

function maintenanceCompletedAt(detail: OperationsEventDetailModel | null): string | null {
  const eventTimes = detail?.closedLoop?.maintenanceEvents
    .map((item) => item.completedAt)
    .filter((value): value is string => Boolean(value)) ?? [];
  const actionTimes = detail?.closedLoop?.maintenanceActions
    .filter((item) => item.status === "completed")
    .map((item) => item.completedAt)
    .filter((value): value is string => Boolean(value)) ?? [];
  return [...eventTimes, ...actionTimes].sort().at(-1) ?? null;
}

function selectedAsset(model: OperationsBootstrapModel, selectedEvent: OperationsEvent | null): OperationsAsset | null {
  if (!selectedEvent) return null;
  return model.assets.find((asset) => asset.assetId === selectedEvent.assetId) ?? null;
}

function relevantMaterials(companyContext: OperationsCompanyContext | null, assetId: string | null | undefined) {
  if (!companyContext || !assetId) return [];
  return companyContext.materials.filter((item) => item.related_asset_ids.includes(assetId));
}

function exposure(input: {
  companyContext: OperationsCompanyContext | null;
  detail: OperationsEventDetailModel | null;
}) {
  const variant = input.detail?.operationContext?.eventImpact?.productVariant ?? null;
  const product = input.companyContext?.products.find((item) => item.variant === variant) ?? null;
  const lostUnits = input.detail?.operationContext?.eventImpact?.estimatedLostUnits ?? null;
  const contributionExposure = product && typeof lostUnits === "number"
    ? product.unit_contribution_margin_krw * lostUnits
    : null;
  const revenueExposure = product && typeof lostUnits === "number"
    ? product.unit_sales_price_krw * lostUnits
    : null;
  return { product, lostUnits, contributionExposure, revenueExposure };
}

function RiskMetricsBlock({ model, detail }: { model: OperationsBootstrapModel; detail: OperationsEventDetailModel | null }) {
  const activeWork = detail?.closedLoop?.workOrders.some((item) => ["approved", "in_progress"].includes(item.status)) ? 1 : 0;
  const metrics = [
    ["가동 설비", model.metrics.totalAssets.toLocaleString("ko-KR")],
    ["주의 설비", (model.metrics.attention + model.metrics.warning).toLocaleString("ko-KR")],
    ["긴급 설비", model.metrics.critical.toLocaleString("ko-KR")],
    ["점검·정비 중", activeWork.toLocaleString("ko-KR")],
    ["판단 대기", model.metrics.pendingDecisions.toLocaleString("ko-KR")],
    ["예상 정지", model.metrics.estimatedDowntimeMinutes !== null ? `${model.metrics.estimatedDowntimeMinutes}분` : "—"],
    ["마지막 수신", dateTime(model.context.observedAt ?? model.context.refreshedAt)],
  ];
  return <Block title="현재 운영 신호" eyebrow="LIVE STATUS" icon={<Gauge size={15} />} className="span-12">
    <div className="rw-composed-metrics">{metrics.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
  </Block>;
}

function FactoryMapBlock({ model, selectedEvent, onSelectEvent }: {
  model: OperationsBootstrapModel;
  selectedEvent: OperationsEvent | null;
  onSelectEvent: (event: OperationsEvent) => void;
}) {
  const eventByAsset = new Map(model.events.map((event) => [event.assetId, event]));
  const lines = [...new Set(model.assets.map((asset) => asset.line))].sort();
  return <Block title="공장 설비 상태맵" eyebrow="REAL-TIME FACTORY STATUS" icon={<Building2 size={15} />} className="span-12">
    <div className="rw-factory-map">{lines.map((line) => {
      const assets = model.assets.filter((asset) => asset.line === line);
      return <section key={line}><header><strong>{line}</strong><span>{assets.length} assets</span></header><div>{assets.map((asset) => {
        const event = eventByAsset.get(asset.assetId) ?? null;
        return <button
          key={asset.assetId}
          type="button"
          className={`status-${asset.status} ${selectedEvent?.assetId === asset.assetId ? "is-selected" : ""}`}
          onClick={() => event && onSelectEvent(event)}
          title={`${asset.displayName} · ${asset.status} · ${probability(asset.failureProbability)}`}
        ><span>{asset.displayName}</span><i>{probability(asset.failureProbability)}</i>{asset.status !== "normal" ? <b /> : null}</button>;
      })}</div></section>;
    })}</div>
  </Block>;
}

function chartPath(points: Array<{ value: number | null }>, width = 260, height = 70): string {
  const values = points.map((item) => item.value).filter((value): value is number => typeof value === "number");
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const filtered = points.filter((item): item is { value: number } => typeof item.value === "number");
  return filtered.map((item, index) => {
    const x = filtered.length === 1 ? width : (index / (filtered.length - 1)) * width;
    const y = height - ((item.value - min) / range) * (height - 8) - 4;
    return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function FeatureTrendBlock({ detail }: { detail: OperationsEventDetailModel | null }) {
  const sensors = detail?.sensors.filter((sensor) => (sensor.historyPoints?.length ?? 0) > 1).slice(0, 4) ?? [];
  return <Block title="실시간 피쳐 그래프" eyebrow="FEATURE TREND" icon={<RadioTower size={15} />} className="span-12">
    {sensors.length ? <div className="rw-feature-trends">{sensors.map((sensor) => {
      const points = sensor.historyPoints ?? [];
      const path = chartPath(points);
      return <article key={sensor.id}><header><div><strong>{sensor.label}</strong><span>{sensor.historyWindow?.requested ?? "recent"} · {sensor.qualityStatus ?? "unknown"}</span></div><b>{String(sensor.value ?? "—")}{sensor.unit ? ` ${sensor.unit}` : ""}</b></header><svg viewBox="0 0 260 70" role="img" aria-label={`${sensor.label} 최근 추세`} preserveAspectRatio="none"><path d={path} /><circle cx="258" cy="35" r="2.5" /></svg><small>{sensor.historyPoints?.length ?? 0} points · 마지막 관측 {dateTime(sensor.observedAt)}</small></article>;
    })}</div> : <Empty text="선택 설비의 시계열 관측이 준비되면 핵심 피쳐 2~4개를 표시합니다." />}
  </Block>;
}

function BusinessKpisBlock({ context }: { context: OperationsCompanyContext | null }) {
  return <Block title="경영 KPI 기준" eyebrow="BUSINESS CONTEXT" icon={<BriefcaseBusiness size={15} />} className="span-6">
    {context?.business_metrics.length ? <div className="rw-composed-list">{context.business_metrics.slice(0, 4).map((item) => <article key={item.id}><div><strong>{item.name}</strong><small>{item.period} · {item.source_label}</small></div><b>{item.unit === "KRW" ? compactMoney(item.value) : `${item.value.toLocaleString("ko-KR")} ${item.unit}`}</b></article>)}</div> : <Empty text="경영 KPI 문맥을 불러오는 중입니다." />}
  </Block>;
}

function OperationalKpisBlock({
  model,
  detail,
  companyContext,
}: {
  model: OperationsBootstrapModel;
  detail: OperationsEventDetailModel | null;
  companyContext: OperationsCompanyContext | null;
}) {
  const firstDecision = detail?.activity
    .filter((item) => item.kind === "decision")
    .sort((left, right) => left.createdAt.localeCompare(right.createdAt))[0] ?? null;
  const workOrder = detail?.closedLoop?.workOrders
    .filter((item) => item.createdAt)
    .sort((left, right) => String(left.createdAt).localeCompare(String(right.createdAt)))[0] ?? null;
  const maintenanceAction = detail?.closedLoop?.maintenanceActions
    .filter((item) => item.startedAt)
    .sort((left, right) => String(left.startedAt).localeCompare(String(right.startedAt)))[0] ?? null;
  const value = exposure({ detail, companyContext });
  const decisionLeadTime = minutesBetween(detail?.event.observedAt, firstDecision?.createdAt);
  const reportLeadTime = minutesBetween(detail?.event.observedAt, detail?.report.generatedAt);
  const inspectionLeadTime = minutesBetween(workOrder?.createdAt, workOrder?.updatedAt);
  const maintenanceLeadTime = minutesBetween(workOrder?.updatedAt, maintenanceAction?.startedAt);
  const repeatedMaintenance = detail?.event.assetId
    ? companyContext?.maintenance_records.filter((item) => item.asset_id === detail.event.assetId).length ?? 0
    : 0;
  const metrics = [
    ["Decision Lead Time", duration(decisionLeadTime)],
    ["Report Lead Time", duration(reportLeadTime)],
    ["점검 처리 시간", duration(inspectionLeadTime)],
    ["승인→정비 착수", duration(maintenanceLeadTime)],
    ["판단 Backlog", `${model.metrics.pendingDecisions.toLocaleString("ko-KR")}건`],
    ["생산 손실 노출", value.lostUnits !== null ? `${value.lostUnits.toLocaleString("ko-KR")}개` : "근거 없음"],
    ["공헌이익 노출", compactMoney(value.contributionExposure)],
    ["동일 설비 과거 정비", `${repeatedMaintenance.toLocaleString("ko-KR")}건`],
  ];
  return <Block title="운영 의사결정 KPI" eyebrow="CASE OPERATING KPI" icon={<TimerReset size={15} />} className="span-12">
    <div className="rw-operational-kpis">{metrics.map(([label, valueLabel]) => <article key={label}><span>{label}</span><strong>{valueLabel}</strong></article>)}</div>
  </Block>;
}

function RiskPortfolioBlock({ model, onSelectEvent }: { model: OperationsBootstrapModel; onSelectEvent: (event: OperationsEvent) => void }) {
  const ranked = [...model.events].sort((a, b) => (b.failureProbability ?? -1) - (a.failureProbability ?? -1)).slice(0, 6);
  return <Block title="운영 리스크 포트폴리오" eyebrow="RISK PORTFOLIO" icon={<ChartNoAxesCombined size={15} />} className="span-6">
    <div className="rw-composed-list">{ranked.map((event) => <button type="button" key={event.eventId} onClick={() => onSelectEvent(event)}><div><strong>{event.assetName}</strong><small>{event.line} · {event.status}</small></div><b>{probability(event.failureProbability)}</b></button>)}</div>
  </Block>;
}

function LineRiskBlock({ model }: { model: OperationsBootstrapModel }) {
  return <Block title="라인별 위험" eyebrow="LINE RISK" icon={<Activity size={15} />} className="span-6">
    <div className="rw-composed-bars">{model.lineRisk.slice(0, 8).map((line) => <div key={line.line}><span>{line.line}</span><i><b style={{ width: `${Math.max(3, (line.averageRisk ?? 0) * 100)}%` }} /></i><strong>{probability(line.averageRisk)}</strong></div>)}</div>
  </Block>;
}

function RiskQueueBlock({ model, onSelectEvent }: { model: OperationsBootstrapModel; onSelectEvent: (event: OperationsEvent) => void }) {
  const ranked = [...model.events].sort((a, b) => (b.failureProbability ?? -1) - (a.failureProbability ?? -1)).slice(0, 7);
  return <Block title="우선 확인 큐" eyebrow="PRIORITY QUEUE" icon={<ShieldAlert size={15} />} className="span-6">
    <div className="rw-composed-list">{ranked.map((event) => <button type="button" key={event.eventId} onClick={() => onSelectEvent(event)}><div><strong>{event.assetName}</strong><small>{event.predictedFailureType} · {event.assignedEngineer ?? "담당 확인 중"}</small></div><b>{probability(event.failureProbability)}</b></button>)}</div>
  </Block>;
}

function AssetBriefBlock({ model, event, onOpenAsset }: { model: OperationsBootstrapModel; event: OperationsEvent | null; onOpenAsset: (assetId: string, eventId: string | null) => void }) {
  const asset = selectedAsset(model, event);
  return <Block title="선택 설비" eyebrow="ASSET CONTEXT" icon={<Boxes size={15} />} className="span-6">
    {asset ? <div className="rw-composed-kv"><div><span>설비</span><strong>{asset.displayName}</strong></div><div><span>라인</span><strong>{asset.line}</strong></div><div><span>중요도</span><strong>{asset.criticality ?? "—"}</strong></div><div><span>담당</span><strong>{asset.assignedEngineer ?? "—"}</strong></div><div><span>위험</span><strong>{probability(asset.failureProbability)}</strong></div><div><span>예상 정지</span><strong>{asset.estimatedDowntimeMinutes ?? "—"}분</strong></div><button type="button" onClick={() => onOpenAsset(asset.assetId, asset.eventId)}>설비 근거 중심으로 보기</button></div> : <Empty text="설비를 선택하면 역할에 맞는 상세 근거를 구성합니다." />}
  </Block>;
}

function ProductionExposureBlock({ detail, companyContext }: { detail: OperationsEventDetailModel | null; companyContext: OperationsCompanyContext | null }) {
  const value = exposure({ detail, companyContext });
  return <Block title="생산 · 재무 영향" eyebrow="PRODUCTION EXPOSURE" icon={<CircleDollarSign size={15} />} className="span-6">
    {detail?.operationContext ? <div className="rw-composed-kv"><div><span>생산 영향</span><strong>{detail.operationContext.productionImpact ?? "—"}</strong></div><div><span>예상 손실 수량</span><strong>{value.lostUnits !== null ? `${value.lostUnits.toLocaleString("ko-KR")}개` : "—"}</strong></div><div><span>제품</span><strong>{value.product?.name ?? detail.operationContext.eventImpact?.productVariant ?? "—"}</strong></div><div><span>매출 노출액</span><strong>{compactMoney(value.revenueExposure)}</strong></div><div><span>공헌이익 노출액</span><strong>{compactMoney(value.contributionExposure)}</strong></div><div><span>산정 기준</span><strong>{detail.operationContext.eventImpact?.basis.formula ?? "—"}</strong></div></div> : <Empty text="선택 이벤트의 생산 영향 문맥이 없습니다." />}
  </Block>;
}

function DecisionQueueBlock({ model, selectedEvent, onSelectEvent }: { model: OperationsBootstrapModel; selectedEvent: OperationsEvent | null; onSelectEvent: (event: OperationsEvent) => void }) {
  const queue = model.events.filter((event) => event.recommendedDecision !== "continue_monitoring").slice(0, 7);
  return <Block title="Decision Case" eyebrow="DECISION QUEUE" icon={<ListChecks size={15} />} className="span-6">
    <div className="rw-composed-list">{queue.map((event) => <button type="button" key={event.eventId} className={selectedEvent?.eventId === event.eventId ? "is-active" : ""} onClick={() => onSelectEvent(event)}><div><strong>{event.assetName}</strong><small>{event.recommendedDecision.replaceAll("_", " ")} · {event.assignedEngineer ?? "owner pending"}</small></div><b>{event.status}</b></button>)}</div>
  </Block>;
}

function WorkflowLifecycleBlock({ detail }: { detail: OperationsEventDetailModel | null }) {
  const lifecycle = detail?.closedLoop?.lifecycleSummary ?? null;
  return <Block title="현재 Workflow 단계" eyebrow="CLOSED LOOP" icon={<ClipboardCheck size={15} />} className="span-6">
    {lifecycle ? <div className="rw-composed-lifecycle"><strong>{lifecycle.currentStepLabel}</strong><div>{lifecycle.completedSteps.map((step) => <span key={step}>{step.replaceAll("_", " ")}</span>)}</div><p>다음 단계: {lifecycle.nextStep?.replaceAll("_", " ") ?? "완료 또는 재평가"}</p></div> : <Empty text="현재 연결된 closed-loop 작업이 없습니다." />}
  </Block>;
}

function CaseLineageBlock({ props }: { props: RoleComposedWorkspaceProps }) {
  const event = props.selectedEvent;
  const detail = props.detail;
  const firstDecision = detail?.activity
    .filter((item) => item.kind === "decision")
    .sort((left, right) => left.createdAt.localeCompare(right.createdAt))[0] ?? null;
  const latestWork = detail?.closedLoop?.workOrders
    .slice()
    .sort((left, right) => String(right.updatedAt ?? right.createdAt ?? "").localeCompare(String(left.updatedAt ?? left.createdAt ?? "")))[0] ?? null;
  const completedAt = maintenanceCompletedAt(detail);
  const steps = [
    {
      id: "event",
      label: "Event",
      state: event ? "done" : "pending",
      headline: event ? `${event.assetName} · ${probability(event.failureProbability)}` : "이벤트 선택 필요",
      detail: event ? `${event.status} · ${dateTime(event.observedAt)}` : "공장 상태맵에서 설비를 선택하세요.",
    },
    {
      id: "evidence",
      label: "Evidence",
      state: detail?.topFactors.length ? "done" : "pending",
      headline: detail?.topFactors.length ? `${detail.topFactors.length}개 모델 근거` : "근거 조회 중",
      detail: detail?.inspectionTargets[0]?.componentLabel
        ? `점검 대상 ${detail.inspectionTargets[0].componentLabel}`
        : "센서·모델·SOP 근거 연결",
    },
    {
      id: "decision",
      label: "Decision",
      state: firstDecision ? "done" : event ? "active" : "pending",
      headline: firstDecision?.title ?? event?.recommendedDecision.replaceAll("_", " ") ?? "판단 대기",
      detail: firstDecision ? `${firstDecision.actor} · ${dateTime(firstDecision.createdAt)}` : "운영 판단과 Owner가 기록됩니다.",
    },
    {
      id: "action",
      label: "Action",
      state: latestWork ? (latestWork.status === "completed" ? "done" : "active") : "pending",
      headline: latestWork ? `${latestWork.workType} · ${latestWork.status}` : detail?.closedLoop?.primaryAction?.label ?? "작업 미생성",
      detail: latestWork ? `${latestWork.workOrderId} · ${latestWork.actorDisplayName ?? latestWork.assignedTo ?? "담당 미정"}` : "승인된 점검·정비 작업이 연결됩니다.",
    },
    {
      id: "outcome",
      label: "Outcome",
      state: completedAt || detail?.closedLoop?.runtimeStatus === "predicted" ? "done" : "pending",
      headline: completedAt ? `정비 완료 · ${dateTime(completedAt)}` : detail?.closedLoop?.runtimeStatus?.replaceAll("_", " ") ?? "결과 대기",
      detail: detail?.report.snapshotId ? `Report snapshot ${detail.report.snapshotId}` : "정비 후 관측과 보고 snapshot이 연결됩니다.",
    },
  ];
  return <Block title="Event → Outcome lineage" eyebrow="CASE LINEAGE" icon={<GitBranch size={15} />} className="span-12">
    <div className="rw-case-lineage">{steps.map((step) => <article key={step.id} className={`is-${step.state}`}><i>{step.label}</i><strong>{step.headline}</strong><small>{step.detail}</small></article>)}</div>
    {event ? <div className="rw-case-lineage-actions"><button type="button" onClick={() => props.onOpenAsset(event.assetId, event.eventId)}>설비 근거 열기</button><button type="button" onClick={() => props.onOpenReport(event.eventId, event.assetId, "executive-brief")}>보고 산출물 보기</button></div> : null}
  </Block>;
}

function WorkflowActionsBlock({ props }: { props: RoleComposedWorkspaceProps }) {
  const asset = selectedAsset(props.model, props.selectedEvent);
  if (!props.selectedEvent || !asset) return <Block title="업무 실행" eyebrow="ACTION" icon={<Wrench size={15} />} className="span-12"><Empty text="작업할 이벤트를 선택하세요." /></Block>;
  return <Block title="업무 실행" eyebrow="GOVERNED ACTION" icon={<Wrench size={15} />} className="span-12">
    <MaintenanceWorkflowActionPanel
      projectId={props.model.context.projectId}
      workspaceId={props.model.context.workspaceId}
      datasetVersionId={props.model.context.datasetVersionId}
      eventId={props.selectedEvent.eventId}
      assetId={asset.assetId}
      assetType={asset.assetType}
      role={props.role}
      snapshotBasis={props.detail?.snapshotBasis ?? null}
      canManage={props.canManageWorkflow}
      canFieldExecute={props.canExecuteFieldWorkflow}
      onChanged={props.onWorkflowChanged}
    />
  </Block>;
}

function SensorSignalsBlock({ detail }: { detail: OperationsEventDetailModel | null }) {
  return <Block title="센서 · 피쳐" eyebrow="OBSERVED SIGNALS" icon={<RadioTower size={15} />} className="span-6">
    {detail?.sensors.length ? <div className="rw-composed-list static">{detail.sensors.slice(0, 8).map((sensor) => <article key={sensor.id}><div><strong>{sensor.label}</strong><small>{sensor.observedAt ? dateTime(sensor.observedAt) : sensor.qualityStatus ?? ""}</small></div><b>{String(sensor.value ?? "—")}{sensor.unit ? ` ${sensor.unit}` : ""}</b></article>)}</div> : <Empty text="선택 설비의 센서 근거를 불러오는 중입니다." />}
  </Block>;
}

function EvidenceFactorsBlock({ detail }: { detail: OperationsEventDetailModel | null }) {
  return <Block title="위험 기여 근거" eyebrow="MODEL EVIDENCE" icon={<ChartNoAxesCombined size={15} />} className="span-6">
    {detail?.topFactors.length ? <div className="rw-composed-list static">{detail.topFactors.slice(0, 7).map((factor) => <article key={factor.id}><div><strong>{factor.label}</strong><small>{factor.direction} · {factor.explanationMethod ?? "model evidence"}</small></div><b>{Math.round(Math.abs(factor.contribution) * 100)}%</b></article>)}</div> : <Empty text="모델 기여 근거가 없습니다." />}
  </Block>;
}

function InspectionTargetsBlock({ detail }: { detail: OperationsEventDetailModel | null }) {
  return <Block title="점검 대상" eyebrow="INSPECTION PLAN" icon={<ClipboardCheck size={15} />} className="span-6">
    {detail?.inspectionTargets.length ? <div className="rw-composed-cards">{detail.inspectionTargets.slice(0, 5).map((target) => <article key={target.targetId}><strong>{target.componentLabel}</strong><span>{target.locationLabel ?? "위치 확인 필요"}</span><p>{target.inspectionMethod ?? target.association}</p></article>)}</div> : <Empty text="현재 근거에서 특정된 점검 대상이 없습니다." />}
  </Block>;
}

function MaintenanceHistoryBlock({ detail, companyContext, assetId }: { detail: OperationsEventDetailModel | null; companyContext: OperationsCompanyContext | null; assetId: string | null | undefined }) {
  const records = companyContext?.maintenance_records.filter((item) => item.asset_id === assetId) ?? [];
  const runtime = detail?.equipmentHistory ?? [];
  return <Block title="정비 · 설비 이력" eyebrow="MAINTENANCE HISTORY" icon={<History size={15} />} className="span-6">
    {records.length || runtime.length ? <div className="rw-composed-timeline">{records.slice(0, 4).map((item) => <article key={item.id}><time>{dateTime(item.occurred_at)}</time><strong>{item.component}</strong><p>{item.symptom}</p><small>{item.action} · 결과: {item.result}</small></article>)}{runtime.slice(0, 4).map((item, index) => <article key={`${item.occurredAt}-${index}`}><time>{dateTime(item.occurredAt)}</time><strong>{item.kind}</strong><p>{item.description}</p><small>{item.source}</small></article>)}</div> : <Empty text="연결된 과거 정비 기록이 없습니다." />}
  </Block>;
}

function MaintenanceEffectBlock({ detail, companyContext, assetId }: { detail: OperationsEventDetailModel | null; companyContext: OperationsCompanyContext | null; assetId: string | null | undefined }) {
  const completedAt = maintenanceCompletedAt(detail);
  const boundary = completedAt ? new Date(completedAt).getTime() : null;
  const riskPoints = [...(detail?.riskSeries ?? [])].sort((left, right) => left.observedAt.localeCompare(right.observedAt));
  const beforeRisk = boundary === null ? [] : riskPoints.filter((item) => new Date(item.observedAt).getTime() <= boundary).slice(-6);
  const afterRisk = boundary === null ? [] : riskPoints.filter((item) => new Date(item.observedAt).getTime() > boundary).slice(0, 6);
  const beforeAverage = average(beforeRisk.map((item) => item.failureProbability));
  const afterAverage = average(afterRisk.map((item) => item.failureProbability));
  const riskDelta = beforeAverage !== null && afterAverage !== null ? afterAverage - beforeAverage : null;
  const beforeAlerts = beforeRisk.filter((item) => item.status && item.status !== "normal").length;
  const afterAlerts = afterRisk.filter((item) => item.status && item.status !== "normal").length;
  const sensorEffects = (detail?.sensors ?? []).map((sensor) => {
    const points = sensor.historyPoints ?? [];
    if (boundary === null) return null;
    const before = average(points.filter((item) => new Date(item.observedAt).getTime() <= boundary).slice(-6).map((item) => item.value));
    const after = average(points.filter((item) => new Date(item.observedAt).getTime() > boundary).slice(0, 6).map((item) => item.value));
    if (before === null || after === null) return null;
    return { id: sensor.id, label: sensor.label, unit: sensor.unit, before, after, delta: after - before };
  }).filter((item): item is NonNullable<typeof item> => Boolean(item)).slice(0, 3);
  const historical = assetId ? companyContext?.maintenance_records.filter((item) => item.asset_id === assetId).at(-1) ?? null : null;
  return <Block title="정비 효과 Before / After" eyebrow="MAINTENANCE OUTCOME" icon={<TrendingDown size={15} />} className="span-12">
    {completedAt ? <div className="rw-maintenance-effect">
      <header><div><span>정비 완료 기준</span><strong>{dateTime(completedAt)}</strong></div><b className={riskDelta !== null && riskDelta < 0 ? "is-improved" : ""}>{riskDelta === null ? "후속 관측 수집 중" : `위험도 ${riskDelta > 0 ? "+" : ""}${Math.round(riskDelta * 100)}%p`}</b></header>
      <div className="rw-maintenance-effect-grid"><article><span>정비 전 위험</span><strong>{probability(beforeAverage)}</strong><small>{beforeRisk.length} observations</small></article><article><span>정비 후 위험</span><strong>{probability(afterAverage)}</strong><small>{afterRisk.length} observations</small></article><article><span>알림 빈도</span><strong>{beforeRisk.length && afterRisk.length ? `${beforeAlerts} → ${afterAlerts}` : "관측 대기"}</strong><small>비정상 risk points</small></article></div>
      {sensorEffects.length ? <div className="rw-maintenance-sensor-effect">{sensorEffects.map((item) => <article key={item.id}><span>{item.label}</span><strong>{item.before.toLocaleString("ko-KR", { maximumFractionDigits: 1 })} → {item.after.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}{item.unit ? ` ${item.unit}` : ""}</strong><small>{item.delta > 0 ? "+" : ""}{item.delta.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}</small></article>)}</div> : <p>센서 before/after window가 충분해지면 핵심 feature의 정규화 여부를 함께 표시합니다.</p>}
    </div> : historical ? <div className="rw-maintenance-history-fallback"><strong>최근 기록된 정비 결과</strong><p>{historical.action}</p><span>{historical.result}</span><small>{dateTime(historical.occurred_at)} · runtime 정비 후 관측이 생기면 before/after로 전환됩니다.</small></div> : <Empty text="정비 완료 및 정비 후 관측 데이터가 연결되면 before/after 효과를 표시합니다." />}
  </Block>;
}

function MaterialContextBlock({ companyContext, assetId }: { companyContext: OperationsCompanyContext | null; assetId: string | null | undefined }) {
  const materials = relevantMaterials(companyContext, assetId);
  return <Block title="자재 · 예비품" eyebrow="MATERIAL CONTEXT" icon={<PackageSearch size={15} />} className="span-6">
    {materials.length ? <div className="rw-composed-list static">{materials.map((item) => <article key={item.id}><div><strong>{item.name}</strong><small>{item.category} · 리드타임 {item.lead_time_days}일</small></div><b className={item.on_hand_quantity <= item.reorder_point ? "is-warning" : ""}>{item.on_hand_quantity}개</b></article>)}</div> : <Empty text="선택 설비에 연결된 자재 master가 없습니다." />}
  </Block>;
}

function DecisionHistoryBlock({ detail, context, assetId }: { detail: OperationsEventDetailModel | null; context: OperationsCompanyContext | null; assetId: string | null | undefined }) {
  const decisions = context?.decisions.filter((item) => !item.related_asset_ids.length || (assetId ? item.related_asset_ids.includes(assetId) : false)).slice(0, 5) ?? [];
  return <Block title="판단 이력" eyebrow="DECISION LINEAGE" icon={<FileClock size={15} />} className="span-6">
    {decisions.length || detail?.activity.length ? <div className="rw-composed-timeline">{decisions.map((item) => <article key={item.id}><time>{dateTime(item.decided_at)}</time><strong>{item.title}</strong><p>{item.decision}</p><small>{item.source_ref}</small></article>)}{detail?.activity.slice(0, 4).map((item) => <article key={item.id}><time>{dateTime(item.createdAt)}</time><strong>{item.title}</strong><p>{item.detail}</p><small>{item.actor}</small></article>)}</div> : <Empty text="연결된 판단 이력이 없습니다." />}
  </Block>;
}

function ReportSummaryBlock({
  detail,
  event,
  model,
  experienceKind,
  canMaterializeAgentSummary,
  onOpenReport,
}: {
  detail: OperationsEventDetailModel | null;
  event: OperationsEvent | null;
  model: OperationsBootstrapModel;
  experienceKind: ReliabilityExperienceKind;
  canMaterializeAgentSummary: boolean;
  onOpenReport: RoleComposedWorkspaceProps["onOpenReport"];
}) {
  const [brief, setBrief] = useState<OperationsAgentReviewSummaryResponse | null>(null);
  const [reportType, setReportType] = useState("executive-brief");

  useEffect(() => {
    if (experienceKind !== "executive" || !event?.assetId) {
      setBrief(null);
      return;
    }
    let cancelled = false;
    const request = {
      assetId: event.assetId,
      projectId: model.context.projectId,
      datasetVersionId: model.context.datasetVersionId,
      eventId: event.eventId,
      historyWindow: "24h",
    };
    void getOperationsAgentReviewSummary(request)
      .then(async (payload) => {
        if (payload.summary || !canMaterializeAgentSummary) return payload;
        return createOperationsAgentReviewSummary({ ...request, trigger: "ui_manual_regeneration" });
      })
      .then((payload) => { if (!cancelled) setBrief(payload); })
      .catch(() => { if (!cancelled) setBrief(null); });
    return () => { cancelled = true; };
  }, [canMaterializeAgentSummary, event?.assetId, event?.eventId, experienceKind, model.context.datasetVersionId, model.context.projectId]);

  const roleSummary = brief?.summary?.summary ?? detail?.report.summary ?? null;
  const headline = brief?.summary?.title ?? detail?.report.headline ?? null;
  const evidenceRefs = brief?.summary?.source_refs ?? detail?.report.sections.flatMap((section) => section.evidenceFieldIds) ?? [];
  return <Block title="역할별 보고 요약" eyebrow="GROUNDED REPORT" icon={<FileText size={15} />} className="span-12">
    {roleSummary && headline ? <div className="rw-composed-report">
      <div className="rw-report-controls"><label><span>보고 유형</span><select value={reportType} onChange={(event) => setReportType(event.target.value)}><option value="inspection-summary">현장 점검 요약</option><option value="operations-decision">운영 판단 보고</option><option value="executive-brief">경영진 Executive Brief</option><option value="maintenance-effect">정비 효과 before-after</option><option value="weekly-risk">주간 리스크 요약</option></select></label><span>{brief?.summary?.mode === "llm" || detail?.report.mode === "llm" ? "LLM grounded" : "grounded fallback"}</span></div>
      {detail?.report ? <div className="rw-report-artifact-meta"><span>CASE ARTIFACT</span><strong>rev {detail.report.revision}</strong><small>snapshot {detail.report.snapshotId ?? "pending"}</small><small>as-of {dateTime(detail.report.asOf)}</small><small>generated {dateTime(detail.report.generatedAt)}</small></div> : null}
      <div><strong>{headline}</strong><p>{roleSummary}</p></div>
      {detail?.report ? <div className="rw-composed-report-sections">{detail.report.sections.slice(0, 4).map((section) => <article key={section.id}><span>{section.title}</span><p>{section.body}</p></article>)}</div> : null}
      <details className="rw-report-evidence"><summary>근거 데이터 확인 · {new Set(evidenceRefs).size} refs</summary><ul>{[...new Set(evidenceRefs)].slice(0, 12).map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul></details>
      <div className="rw-report-actions"><button type="button" onClick={() => onOpenReport(event?.eventId ?? null, event?.assetId ?? null, reportType === "inspection-summary" ? "inspection-request" : "executive-brief")}>내용 미리보기</button><button type="button" onClick={() => window.print()}>출력 전 확인</button></div>
    </div> : <Empty text="선택 이벤트의 grounded report를 불러오는 중입니다." />}
  </Block>;
}

function ContextEvidenceBlock({ context, assetId }: { context: OperationsCompanyContext | null; assetId: string | null | undefined }) {
  const decisions = context?.decisions.filter((item) => !item.related_asset_ids.length || (assetId ? item.related_asset_ids.includes(assetId) : false)).slice(0, 3) ?? [];
  return <Block title="조직 · 회의 · 의사결정 문맥" eyebrow="ONTOLOGY CONTEXT" icon={<Building2 size={15} />} className="span-12">
    {context ? <div className="rw-composed-context"><div><div className="rw-context-source-row"><strong>{context.company.name}</strong><span className={context.context_storage?.mode === "team_db_overlay" ? "is-db" : ""}>{context.context_storage?.mode === "team_db_overlay" ? `Team DB · ${context.context_storage.persisted_record_count} records` : "Reference bootstrap"}</span></div><p>{context.company.operating_principle}</p><small>{context.company.industry} · {context.company.headquarters}</small></div><div className="rw-composed-context-grid">{context.organization_units.slice(0, 5).map((unit) => <article key={unit.id}><span>{unit.name}</span><strong>{unit.leader}</strong><small>{unit.responsibilities.slice(0, 2).join(" · ")}</small></article>)}</div>{context.meeting_minutes.slice(0, 2).map((meeting) => <article className="rw-composed-meeting" key={meeting.id}><span>{dateTime(meeting.occurred_at)}</span><strong>{meeting.title}</strong><p>{meeting.summary}</p></article>)}{decisions.map((decision) => <article className="rw-composed-decision" key={decision.id}><strong>{decision.title}</strong><p>{decision.decision}</p><small>{decision.source_ref}</small></article>)}</div> : <Empty text="회사 및 조직 문맥을 불러오는 중입니다." />}
  </Block>;
}

function DataQualityBlock({ detail, model }: { detail: OperationsEventDetailModel | null; model: OperationsBootstrapModel }) {
  const warnings = detail?.dataQualityWarnings ?? [];
  return <Block title="데이터 품질 확인 필요" eyebrow="DATA QUALITY HOLD" icon={<AlertTriangle size={15} />} className="span-12 is-warning-block">
    <p>현재 데이터 품질 보류 항목이 {model.metrics.dataQualityHold}건 있습니다. 품질 문제가 해소되기 전에는 고장 위험·생산 영향·정비 필요성을 확정하지 않습니다.</p>
    {warnings.length ? <ul>{warnings.map((warning) => <li key={`${warning.code}-${warning.field}`}>{warning.field}: {warning.message}</li>)}</ul> : null}
  </Block>;
}

function Empty({ text }: { text: string }) {
  return <div className="rw-composed-empty">{text}</div>;
}

function renderBlock(id: ReliabilityBlockId, props: RoleComposedWorkspaceProps) {
  const assetId = props.selectedEvent?.assetId ?? null;
  switch (id) {
    case "risk-metrics": return <RiskMetricsBlock key={id} model={props.model} detail={props.detail} />;
    case "factory-map": return <FactoryMapBlock key={id} model={props.model} selectedEvent={props.selectedEvent} onSelectEvent={props.onSelectEvent} />;
    case "business-kpis": return <BusinessKpisBlock key={id} context={props.companyContext} />;
    case "operational-kpis": return <OperationalKpisBlock key={id} model={props.model} detail={props.detail} companyContext={props.companyContext} />;
    case "risk-portfolio": return <RiskPortfolioBlock key={id} model={props.model} onSelectEvent={props.onSelectEvent} />;
    case "line-risk": return <LineRiskBlock key={id} model={props.model} />;
    case "risk-queue": return <RiskQueueBlock key={id} model={props.model} onSelectEvent={props.onSelectEvent} />;
    case "asset-brief": return <AssetBriefBlock key={id} model={props.model} event={props.selectedEvent} onOpenAsset={props.onOpenAsset} />;
    case "production-exposure": return <ProductionExposureBlock key={id} detail={props.detail} companyContext={props.companyContext} />;
    case "decision-queue": return <DecisionQueueBlock key={id} model={props.model} selectedEvent={props.selectedEvent} onSelectEvent={props.onSelectEvent} />;
    case "workflow-lifecycle": return <WorkflowLifecycleBlock key={id} detail={props.detail} />;
    case "case-lineage": return <CaseLineageBlock key={id} props={props} />;
    case "workflow-actions": return <WorkflowActionsBlock key={id} props={props} />;
    case "sensor-signals": return <SensorSignalsBlock key={id} detail={props.detail} />;
    case "feature-trend": return <FeatureTrendBlock key={id} detail={props.detail} />;
    case "evidence-factors": return <EvidenceFactorsBlock key={id} detail={props.detail} />;
    case "inspection-targets": return <InspectionTargetsBlock key={id} detail={props.detail} />;
    case "maintenance-history": return <MaintenanceHistoryBlock key={id} detail={props.detail} companyContext={props.companyContext} assetId={assetId} />;
    case "maintenance-effect": return <MaintenanceEffectBlock key={id} detail={props.detail} companyContext={props.companyContext} assetId={assetId} />;
    case "material-context": return <MaterialContextBlock key={id} companyContext={props.companyContext} assetId={assetId} />;
    case "decision-history": return <DecisionHistoryBlock key={id} detail={props.detail} context={props.companyContext} assetId={assetId} />;
    case "report-summary": return <ReportSummaryBlock key={id} detail={props.detail} event={props.selectedEvent} model={props.model} experienceKind={props.experienceKind} canMaterializeAgentSummary={props.canMaterializeAgentSummary} onOpenReport={props.onOpenReport} />;
    case "context-evidence": return <ContextEvidenceBlock key={id} context={props.companyContext} assetId={assetId} />;
    case "data-quality": return <DataQualityBlock key={id} detail={props.detail} model={props.model} />;
  }
}

export function RoleComposedWorkspace(props: RoleComposedWorkspaceProps) {
  const materials = relevantMaterials(props.companyContext, props.selectedEvent?.assetId);
  const exposureValue = exposure({ detail: props.detail, companyContext: props.companyContext });
  const hasMaintenanceOutcome = Boolean(
    props.detail?.closedLoop?.maintenanceEvents.length
    || props.detail?.closedLoop?.maintenanceActions.some((item) => item.status === "completed"),
  );
  const blocks = resolveReliabilityComposition(props.experienceKind, props.view, {
    hasCriticalRisk: props.model.metrics.critical > 0,
    hasDataQualityHold: props.model.metrics.dataQualityHold > 0 || Boolean(props.detail?.dataQualityWarnings.length),
    hasOpenWorkflow: Boolean(props.detail?.closedLoop?.workOrders.length || props.detail?.closedLoop?.maintenanceActions.length),
    hasMaterialConstraint: materials.some((item) => item.on_hand_quantity <= item.reorder_point),
    hasDecisionBacklog: props.model.metrics.pendingDecisions >= 3,
    hasHighProductionExposure: typeof exposureValue.revenueExposure === "number" && exposureValue.revenueExposure >= 10_000_000,
    hasMaintenanceOutcome,
  }, props.surfaceId);

  return <div
    className={`rw-composed-grid composition-${props.experienceKind}`}
    data-testid={`role-composed-${props.experienceKind}`}
    data-surface={props.surfaceId ?? "default"}
    data-composition={blocks.join(",")}
  >
    {blocks.map((id) => renderBlock(id, props))}
  </div>;
}

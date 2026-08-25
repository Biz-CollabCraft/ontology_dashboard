import {
  Activity,
  ArrowRight,
  ClipboardCheck,
  ClipboardList,
  FileText,
  LineChart,
  RefreshCw,
  RotateCcw,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";
import type {
  MvpAsset,
  MvpBootstrapModel,
  MvpEvent,
  MvpEventDetailModel,
  MvpRoleLens,
} from "../api/mvpContracts";
import {
  DECISION_LABEL,
  MvpConfidenceBadge,
  MvpPanel,
  MvpState,
  MvpStatusBadge,
  formatMinutes,
  formatProbability,
  formatTimestamp,
} from "../components/MvpUi";

const DECISION_ORDER: MvpEvent["recommendedDecision"][] = [
  "review_shutdown",
  "request_inspection",
  "hold_for_data_check",
  "continue_monitoring",
];

interface WorkOrderCandidate {
  event: MvpEvent;
  asset: MvpAsset | null;
  suspectedPart: string;
}

interface CellSummary {
  cell: string;
  line: string;
  assets: MvpAsset[];
  representative: MvpAsset;
  averageRisk: number | null;
  critical: number;
  warning: number;
  hold: number;
}

type DrawerTab = "status" | "action";

interface PlanningImpactRow {
  assetId: string;
  eventId: string;
  line: string;
  productLabel: string;
  estimatedLossUnits: number | null;
  status: "plan_at_risk" | "shift_inspection" | "inspection_priority" | "data_quality_hold";
  nextAction: string;
  sparePartAvailable: boolean | null;
}

const TODAY_PLAN_UNITS = 16200;
const PLANNING_MODEL_BASIS = "80 assets, 16h/day, OEE 0.846, cycle 4.0min 기준";
const PLANNING_IMPACT_ROWS: PlanningImpactRow[] = [
  { assetId: "M-033", eventId: "EVT-GS-004", line: "프레스 1라인", productLabel: "금속 성형 부품 L", estimatedLossUnits: 51, status: "plan_at_risk", nextAction: "부품 재고 확인", sparePartAvailable: false },
  { assetId: "M-021", eventId: "EVT-GS-003", line: "성형 1라인", productLabel: "성형 공정", estimatedLossUnits: 32, status: "shift_inspection", nextAction: "교대 내 점검 예약", sparePartAvailable: null },
  { assetId: "M-014", eventId: "EVT-GS-002", line: "가공 2라인", productLabel: "가공 공정", estimatedLossUnits: 25, status: "inspection_priority", nextAction: "점검 우선", sparePartAvailable: null },
  { assetId: "M-063", eventId: "EVT-GS-007", line: "검사 1라인", productLabel: "검사 공정", estimatedLossUnits: null, status: "data_quality_hold", nextAction: "데이터 품질 확인 필요", sparePartAvailable: true },
];

const PLANNING_STATUS_LABEL: Record<PlanningImpactRow["status"], string> = {
  plan_at_risk: "계획 위험",
  shift_inspection: "교대 내 점검",
  inspection_priority: "점검 우선",
  data_quality_hold: "데이터 품질 확인 필요",
};

function partLabel(value: boolean | null): string {
  if (value === true) return "확보";
  if (value === false) return "미확보";
  return "확인 필요";
}

function planningImpactForAsset(assetId: string | null | undefined): PlanningImpactRow | null {
  if (!assetId) return null;
  return PLANNING_IMPACT_ROWS.find((row) => row.assetId === assetId) ?? null;
}

function productionLossLabel(value: number | null): string {
  return value === null ? "생산 영향 미산정" : `${value.toLocaleString()} units 예상`;
}

function displayPartLabel(assetId: string | null | undefined, value: boolean | null): string {
  const planning = planningImpactForAsset(assetId);
  return partLabel(planning?.sparePartAvailable ?? value);
}

function riskTone(summary: Pick<CellSummary, "critical" | "warning" | "hold"> & { attention?: number }): "critical" | "warning" | "hold" | "attention" | "normal" {
  if (summary.critical > 0) return "critical";
  if (summary.warning > 0) return "warning";
  if (summary.hold > 0) return "hold";
  if ((summary.attention ?? 0) > 0) return "attention";
  return "normal";
}

function suspectedPartLabel(event: MvpEvent, asset: MvpAsset | null): string {
  const factorLabel = asset?.topFactors[0]?.label;
  if (factorLabel) return factorLabel;
  if (event.predictedFailureType && event.predictedFailureType !== "unavailable") return event.predictedFailureType;
  return "부품 근거 없음";
}

function buildCellSummaries(assets: MvpAsset[]): CellSummary[] {
  const groups = new Map<string, MvpAsset[]>();
  assets.forEach((asset) => {
    const key = asset.cell || asset.line || "셀 근거 없음";
    groups.set(key, [...(groups.get(key) ?? []), asset]);
  });
  return Array.from(groups.entries()).map(([cell, group]) => {
    const riskValues = group.map((asset) => asset.failureProbability).filter((value): value is number => value !== null);
    const representative = [...group].sort((a, b) => (b.failureProbability ?? -1) - (a.failureProbability ?? -1))[0];
    return {
      cell,
      line: representative.line,
      assets: group,
      representative,
      averageRisk: riskValues.length ? riskValues.reduce((sum, value) => sum + value, 0) / riskValues.length : null,
      critical: group.filter((asset) => asset.status === "critical").length,
      warning: group.filter((asset) => asset.status === "warning").length,
      hold: group.filter((asset) => asset.status === "data_quality_hold").length,
    };
  }).sort((a, b) => {
    const toneWeight = { critical: 4, warning: 3, hold: 2, attention: 1, normal: 0 };
    return toneWeight[riskTone(b)] - toneWeight[riskTone(a)] || (b.averageRisk ?? -1) - (a.averageRisk ?? -1);
  });
}

function statusText(asset: MvpAsset | null): string {
  if (!asset) return "선택된 설비 없음";
  return `${asset.displayName} · ${asset.line}`;
}

function factorValueLabel(factor: MvpAsset["topFactors"][number]): string {
  if (factor.value === null) return "근거 부족";
  return `${factor.value.toLocaleString()}${factor.unit ? ` ${factor.unit}` : ""}`;
}

interface SeriesDatum {
  observedAt: string;
  value: number;
}

function formatSeriesTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function featureSeries(detail: MvpEventDetailModel | null, factors: MvpAsset["topFactors"]): { label: string; unit: string | null; points: SeriesDatum[] } | null {
  if (!detail) return null;
  const preferredFeatureId = factors[0]?.feature;
  const sensor = detail.sensors.find((item) => item.id === preferredFeatureId && (item.historyPoints?.length ?? 0) > 0)
    ?? detail.sensors.find((item) => (item.historyPoints?.length ?? 0) > 0)
    ?? null;
  if (!sensor) return null;
  const points = (sensor.historyPoints ?? [])
    .filter((point): point is typeof point & { value: number } => typeof point.value === "number" && Number.isFinite(point.value))
    .map((point) => ({
      observedAt: point.observedAt,
      value: point.value,
    }));
  if (!points.length) return null;
  return { label: sensor.label, unit: sensor.unit, points };
}

function inspectionLocationForFeature(feature: string): { range: string; note: string; className: string } {
  const key = feature.toLowerCase();
  if (key.includes("vibration")) return { range: "모터-축/벨트-압축부", note: "간헐적 떨림과 체결 풀림 확인", className: "loc-drive-zone" };
  if (key.includes("pressure")) return { range: "압축부-배관/밸브", note: "압력 변동과 누설 확인", className: "loc-pump-valve" };
  if (key.includes("voltage") || key.includes("power")) return { range: "모터 전원부", note: "전원 공급과 전압 저하 확인", className: "loc-motor-power" };
  if (key.includes("torque") || key.includes("rotation")) return { range: "모터-축/벨트", note: "회전 힘 전달과 속도 저하 확인", className: "loc-motor-drive" };
  if (key.includes("strain") || key.includes("load")) return { range: "축/벨트-압축부", note: "부하 변동과 과부하 흔적 확인", className: "loc-drive-pump" };
  if (key.includes("temperature")) return { range: "압축부 고정부", note: "열 상승과 베이스 상태 확인", className: "loc-pump-base" };
  return { range: "설비 주요 연결부", note: "현장 점검 위치 확인", className: "loc-pump-base" };
}

export function MvpOverviewPage({
  model,
  role,
  selectedAssetId,
  detail,
  detailLoading,
  detailError,
  onPreviewAsset,
  onOpenAsset,
  onOpenEvent,
  onOpenReport,
  onRefresh,
}: {
  model: MvpBootstrapModel;
  role: MvpRoleLens;
  selectedAssetId: string | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  onPreviewAsset: (assetId: string, eventId: string | null) => void;
  onOpenAsset: (assetId: string, eventId: string | null) => void;
  onOpenEvent: (eventId: string, assetId: string) => void;
  onOpenReport: (eventId: string | null, assetId: string | null) => void;
  onRefresh: () => void;
}) {
  const { metrics } = model;
  const topAssets = model.assets.slice(0, 6);
  const anomalyEvents = model.events
    .filter((item) => item.recommendedDecision !== "continue_monitoring")
    .slice(0, 8);
  const workOrderCandidates: WorkOrderCandidate[] = anomalyEvents.map((event) => {
    const asset = model.assets.find((item) => item.assetId === event.assetId) ?? null;
    return { event, asset, suspectedPart: suspectedPartLabel(event, asset) };
  });
  const cellSummaries = buildCellSummaries(model.assets);
  const selectedAsset = model.assets.find((asset) => asset.assetId === selectedAssetId)
    ?? topAssets[0]
    ?? null;
  const selectedEvent = selectedAsset?.eventId
    ? model.events.find((event) => event.eventId === selectedAsset.eventId) ?? null
    : null;
  const selectedFactors = detail?.event.assetId === selectedAsset?.assetId && detail.topFactors.length
    ? detail.topFactors
    : selectedAsset?.topFactors ?? [];
  const needsPartCheck = anomalyEvents.filter((event) => event.sparePartAvailable !== true).length;
  const decisionCounts = DECISION_ORDER.map((decision) => ({
    decision,
    count: model.events.filter((event) => event.recommendedDecision === decision).length,
  }));
  const riskyLines = model.lineRisk.filter((line) => line.critical + line.warning + line.dataQualityHold > 0).length;
  const selectedCell = selectedAsset
    ? cellSummaries.find((summary) => summary.cell === (selectedAsset.cell || selectedAsset.line || "셀 근거 없음")) ?? null
    : null;
  const selectedCandidate = selectedEvent
    ? workOrderCandidates.find((candidate) => candidate.event.eventId === selectedEvent.eventId) ?? null
    : null;
  const selectedRiskPercent = selectedAsset?.failureProbability === null || selectedAsset?.failureProbability === undefined
    ? null
    : Math.round(selectedAsset.failureProbability * 100);
  const selectedPredictionWindow = detail?.event.assetId === selectedAsset?.assetId
    ? detail.predictionHorizonHours
    : null;
  const selectedPlanningImpact = planningImpactForAsset(selectedAsset?.assetId);
  const maxPlanningImpact = PLANNING_IMPACT_ROWS.find((row) => row.eventId === "EVT-GS-004") ?? PLANNING_IMPACT_ROWS[0];
  const agentSummaryLine = role === "field_operator"
    ? `오더 후보 ${workOrderCandidates.length}건 · 부품 확인 ${needsPartCheck}건 · 실제 WorkOrder ID는 생성하지 않음`
    : `위험 라인 ${riskyLines}개 · 셀 ${cellSummaries.length}개 · 평균 위험도 ${formatProbability(metrics.averageRisk)}`;
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [detailDrawerTab, setDetailDrawerTab] = useState<DrawerTab>("status");

  useEffect(() => {
    if (!detailDrawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetailDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detailDrawerOpen]);

  const previewInDrawer = (assetId: string, eventId: string | null) => {
    onPreviewAsset(assetId, eventId);
    setDetailDrawerOpen(true);
    setDetailDrawerTab("status");
  };

  return (
    <div className="mvp-page mvp-overview-page" data-testid="mvp-overview">
      <section className="mvp-agent-summary" aria-label="에이전트 요약">
        <div>
          <span>AGENT SUMMARY</span>
          <strong>
            {selectedAsset
              ? role === "field_operator"
                ? `${selectedAsset.displayName} 기준으로 점검 후보를 먼저 봅니다`
                : `생산 리스크 요약 · ${selectedAsset.displayName} 우선 관리`
              : "선택된 설비가 없습니다"}
          </strong>
          <p>
            {role === "field_operator"
              ? "자동 WorkOrder 생성이나 승인 실행은 하지 않고, 현재 snapshot의 점검 근거만 다음 클릭으로 이어줍니다."
              : `${agentSummaryLine} · 계획 영향은 synthetic_capacity_model 기반 추정이며 생산계획 ViewModel 연결 전 표시입니다.`}
          </p>
        </div>
        {role === "process_manager" ? (
          <div className="mvp-agent-sample-strip" aria-label="생산 관리 관련 데이터">
            <span>오늘 계획 {TODAY_PLAN_UNITS.toLocaleString()} units/day</span>
            <span>생산계획 ViewModel 미연결</span>
            <span>실제 MES 실적 아님</span>
          </div>
        ) : null}
        <button type="button" className="mvp-button ghost" onClick={onRefresh}><RefreshCw size={15} />새로고침</button>
      </section>

      <section className="mvp-overview-topline" aria-label="운영 상단 지표">
        <article className="mvp-plan-impact-card">
          <span>오늘 계획</span>
          <strong>{TODAY_PLAN_UNITS.toLocaleString()} units/day</strong>
          <small>계획 기준 · 생산계획 ViewModel 미연결</small>
        </article>
        <article className="mvp-plan-impact-card is-critical">
          <span>최대 생산 영향 이벤트</span>
          <strong>{productionLossLabel(maxPlanningImpact.estimatedLossUnits)}</strong>
          <small>{maxPlanningImpact.eventId} / {maxPlanningImpact.assetId} / {maxPlanningImpact.line}</small>
        </article>
        <article className="mvp-plan-impact-card">
          <span>즉시 판단 필요</span>
          <strong>1건</strong>
          <small>계획 위험 이벤트 기준</small>
        </article>
        <article className="mvp-plan-impact-card is-hold">
          <span>데이터 품질 확인 필요</span>
          <strong>1건</strong>
          <small>생산 영향 미산정 포함</small>
        </article>
        <DonutMetric
          label={`${selectedPredictionWindow ?? 24}시간 이내 고장 발생률`}
          value={selectedAsset?.failureProbability ?? null}
          detail={selectedPredictionWindow ? "AssetDetail 예측 기간 기준" : "예측 기간 근거 없음"}
          tone="risk"
        />
      </section>

      {role === "field_operator" ? (
        <div className="mvp-role-overview mvp-role-overview-wide">
          <MvpPanel title="우선순위" eyebrow="FROM INSPECTION REQUEST" className="mvp-today-panel">
            <div className="mvp-order-board">
              <header><ClipboardList size={15} /><strong>작업 오더 후보 · 의심 부품</strong><span>{workOrderCandidates.length}건</span></header>
              <div className="mvp-work-card-list">
                {workOrderCandidates.length ? workOrderCandidates.map((candidate, index) => (
                  <button type="button" key={candidate.event.eventId} className={selectedAsset?.assetId === candidate.event.assetId ? "mvp-work-card is-selected" : "mvp-work-card"} onClick={() => previewInDrawer(candidate.event.assetId, candidate.event.eventId)}>
                    <div><MvpStatusBadge status={candidate.event.status} /><strong>{candidate.suspectedPart}</strong><small>제안 #{String(index + 1).padStart(2, "0")} · {candidate.event.assetName}</small></div>
                    <dl>
                      <div><dt>설비</dt><dd>{candidate.event.assetId}</dd></div>
                      <div><dt>부품</dt><dd>{partLabel(candidate.event.sparePartAvailable)}</dd></div>
                      <div><dt>담당</dt><dd>{candidate.event.assignedEngineer ?? "미배정"}</dd></div>
                      <div><dt>권고</dt><dd>{DECISION_LABEL[candidate.event.recommendedDecision]}</dd></div>
                    </dl>
                    <span>선택<ArrowRight size={14} /></span>
                  </button>
                )) : <MvpState kind="empty" title="작업 오더 후보 없음" detail="점검 요청 리포트 기준으로 즉시 제안할 후보가 없습니다." />}
              </div>
            </div>
          </MvpPanel>
        </div>
      ) : (
        <div className="mvp-role-overview">
          <MvpPanel title="우선순위" eyebrow="FROM STATUS SUMMARY" className="mvp-process-panel">
            <div className="mvp-plan-impact-note">synthetic_capacity_model 기반 계획 영향 추정 · 실제 MES 실적 아님</div>
            {PLANNING_IMPACT_ROWS.length ? (
              <div className="mvp-cell-map mvp-plan-impact-list">
                {PLANNING_IMPACT_ROWS.map((impact) => {
                  const asset = model.assets.find((item) => item.assetId === impact.assetId) ?? null;
                  const tone = impact.status === "data_quality_hold" ? "hold" : impact.status === "plan_at_risk" ? "critical" : "warning";
                  return (
                    <button type="button" key={impact.eventId} className={`mvp-cell-block tone-${tone} ${selectedAsset?.assetId === impact.assetId ? "is-selected" : ""}`} onClick={() => previewInDrawer(impact.assetId, impact.eventId)}>
                      <span>{impact.line} · {impact.productLabel}</span>
                      <strong>{impact.assetId}{asset ? ` · ${asset.displayName}` : ""}</strong>
                      <b>{productionLossLabel(impact.estimatedLossUnits)}</b>
                      <small>{impact.status} · {PLANNING_STATUS_LABEL[impact.status]} · 부품 {displayPartLabel(impact.assetId, asset?.sparePartAvailable ?? null)}</small>
                    </button>
                  );
                })}
              </div>
            ) : <MvpState kind="empty" title="라인 데이터가 없습니다" detail="연결된 설비 판단에 라인 또는 위치 정보가 없습니다." />}
          </MvpPanel>

          <div className="mvp-manager-column">
            <MvpPanel title="진행 현황" eyebrow="DECISION QUEUE">
              <div className="mvp-progress-grid">
                {decisionCounts.map((item) => (
                  <article key={item.decision}>
                    <span>{DECISION_LABEL[item.decision]}</span>
                    <strong>{item.count}</strong>
                  </article>
                ))}
              </div>
            </MvpPanel>
          </div>
        </div>
      )}

      {selectedAsset && detailDrawerOpen ? (
        <div className="mvp-detail-drawer-layer" role="presentation">
          <button
            type="button"
            className="mvp-detail-drawer-scrim"
            aria-label="상세 패널 닫기"
            onClick={() => setDetailDrawerOpen(false)}
          />
          <aside className="mvp-detail-drawer" role="dialog" aria-modal="true" aria-label="선택 설비 상세">
            <button type="button" className="mvp-icon-button mvp-drawer-close" aria-label="상세 닫기" onClick={() => setDetailDrawerOpen(false)}>
              <X size={16} />
            </button>
            <AssetPreviewPanel asset={selectedAsset} event={selectedEvent} candidate={selectedCandidate} cell={selectedCell} factors={selectedFactors} riskPercent={selectedRiskPercent} planningImpact={selectedPlanningImpact} detail={detail} detailLoading={detailLoading} detailError={detailError} role={role} activeTab={detailDrawerTab} onTabChange={setDetailDrawerTab} onOpenAsset={onOpenAsset} onOpenEvent={onOpenEvent} onOpenReport={onOpenReport} />
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function DonutMetric({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: number | null;
  detail: string;
  tone: "risk" | "hold";
}) {
  const percent = value === null ? null : Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <article className={`mvp-donut-card tone-${tone}`}>
      <div
        className={percent === null ? "mvp-donut is-empty" : "mvp-donut"}
        style={{ "--mvp-donut-value": `${percent ?? 0}%` } as CSSProperties}
        aria-label={`${label} ${percent === null ? "근거 없음" : `${percent}%`}`}
      >
        <strong>{percent === null ? "-" : `${percent}%`}</strong>
      </div>
      <div>
        <span><Activity size={13} />{label}</span>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function MapReportFeatureSeries({
  title,
  unit,
  points,
  emptyTitle,
  emptyDetail,
}: {
  title: string;
  unit: string | null;
  points: SeriesDatum[];
  emptyTitle: string;
  emptyDetail: string;
}) {
  const color = title.includes("진동") || title.includes("토크") ? "#a7630c" : "#285fcb";
  if (!points.length) {
    return (
      <section className="asset-series-block">
        <header className="asset-series-heading">
          <div><LineChart size={17} /><strong>{title}</strong></div>
          <span>시계열 없음</span>
        </header>
        <div className="asset-chart-empty"><strong>{emptyTitle}</strong><span>{emptyDetail}</span></div>
      </section>
    );
  }
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  const chartWidth = 720;
  const chartHeight = 250;
  const frame = { left: 64, right: 690, top: 22, bottom: 210 };
  const width = frame.right - frame.left;
  const height = frame.bottom - frame.top;
  const coords = points.map((point, index) => {
    const x = points.length === 1 ? (frame.left + frame.right) / 2 : frame.left + (width * index) / (points.length - 1);
    const y = frame.bottom - ((point.value - min) / range) * height;
    return { ...point, x, y };
  });
  const path = coords.map((point) => `${point.x},${point.y}`).join(" ");
  const latest = points[points.length - 1];
  const ticks = [max, (min + max) / 2, min];
  return (
    <section className="asset-series-block">
      <header className="asset-series-heading">
        <div><RotateCcw size={17} /><strong>{title}</strong></div>
        <span className="asset-baseline-key"><i style={{ background: color }} />현재 {latest.value.toLocaleString()}{unit ? ` ${unit}` : ""}</span>
      </header>
      <svg className="asset-series-chart" viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`${title} 시계열`}>
        <rect className="asset-chart-frame" x={frame.left} y={frame.top} width={width} height={height} />
        {ticks.map((tick) => {
          const y = frame.bottom - ((tick - min) / range) * height;
          return <g key={tick}><line className="asset-chart-grid" x1={frame.left} x2={frame.right} y1={y} y2={y} /><text className="asset-chart-axis" x="58" y={y + 4} textAnchor="end">{tick.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}</text></g>;
        })}
        <polyline className="asset-series-line" points={path} style={{ stroke: color }} />
        {coords.map((point) => <circle key={`${point.observedAt}-${point.value}`} className="asset-current-marker" cx={point.x} cy={point.y} r="4.4" style={{ fill: color }} />)}
        <text className="asset-chart-axis" x={frame.left} y="234" textAnchor="start">{formatSeriesTime(points[0].observedAt)}</text>
        <text className="asset-chart-axis" x={frame.right} y="234" textAnchor="end">{formatSeriesTime(latest.observedAt)}</text>
      </svg>
    </section>
  );
}

function DerivedMetricSlots() {
  const slots = ["온도 차이", "기계 출력", "복합 과부하 지표"];
  return (
    <section className="mvp-derived-metric-slots" aria-label="파생 지표 시계열 준비">
      <header><LineChart size={14} /><strong>파생 지표 시계열</strong><span>Backend ViewModel 연결 전</span></header>
      <div>
        {slots.map((slot) => <article key={slot}><span>{slot}</span><strong>대기</strong></article>)}
      </div>
      <p>파생 지표 시계열은 Backend ViewModel 연결 후 features[].series로 표시됩니다.</p>
    </section>
  );
}

function AssetPreviewPanel({
  asset,
  event,
  candidate,
  cell,
  factors,
  riskPercent,
  planningImpact,
  detail,
  detailLoading,
  detailError,
  role,
  activeTab,
  onTabChange,
  onOpenAsset,
  onOpenEvent,
  onOpenReport,
}: {
  asset: MvpAsset | null;
  event: MvpEvent | null;
  candidate: WorkOrderCandidate | null;
  cell: CellSummary | null;
  factors: MvpAsset["topFactors"];
  riskPercent: number | null;
  planningImpact: PlanningImpactRow | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  role: MvpRoleLens;
  activeTab: DrawerTab;
  onTabChange: (tab: DrawerTab) => void;
  onOpenAsset: (assetId: string, eventId: string | null) => void;
  onOpenEvent: (eventId: string, assetId: string) => void;
  onOpenReport: (eventId: string | null, assetId: string | null) => void;
}) {
  const featureSnapshot = detail?.event.assetId === asset?.assetId ? featureSeries(detail, factors) : null;
  const inspectionTargets = factors.slice(0, 3).map((factor, index) => ({
    factor,
    rank: index + 1,
    location: inspectionLocationForFeature(factor.feature),
  }));
  const fallbackInspectionLocation = inspectionLocationForFeature(asset?.predictedFailureType ?? "");
  return (
    <MvpPanel
      title="선택 항목"
      eyebrow="SIDE TASK VIEW"
      className="mvp-asset-preview-panel"
    >
      {asset ? (
        <div className="mvp-asset-preview">
          <div className="mvp-drawer-tabs" role="tablist" aria-label="사이드뷰 탭">
            <button type="button" role="tab" aria-selected={activeTab === "status"} className={activeTab === "status" ? "is-active" : ""} onClick={() => onTabChange("status")}>상태</button>
            <button type="button" role="tab" aria-selected={activeTab === "action"} className={activeTab === "action" ? "is-active" : ""} onClick={() => onTabChange("action")}>처리</button>
          </div>
          <header>
            <MvpStatusBadge status={asset.status} />
            <div><strong>{statusText(asset)}</strong><small>{asset.assetId} · 관측 {formatTimestamp(asset.observedAt)}</small></div>
          </header>
          {role === "process_manager" && activeTab === "status" ? (
            <>
              <dl>
                <div><dt>위험도</dt><dd>{formatProbability(asset.failureProbability)}</dd></div>
                <div><dt>권고</dt><dd>{DECISION_LABEL[asset.recommendedDecision]}</dd></div>
                <div><dt>부품</dt><dd>{displayPartLabel(asset.assetId, asset.sparePartAvailable)}</dd></div>
                <div><dt>담당</dt><dd>{asset.assignedEngineer ?? "미배정"}</dd></div>
                <div><dt>영향</dt><dd>{formatMinutes(asset.estimatedDowntimeMinutes)}</dd></div>
                <div><dt>신뢰도</dt><dd><MvpConfidenceBadge confidence={asset.confidence} /></dd></div>
                {candidate ? <div><dt>오더 후보</dt><dd>{candidate.suspectedPart}</dd></div> : null}
                {cell ? <div><dt>셀</dt><dd>{cell.cell} · {cell.assets.length}대</dd></div> : null}
              </dl>

              <section className="mvp-production-impact-block" aria-label="생산 영향">
                <header><Activity size={14} /><strong>생산 영향</strong><span>계획 기준 추정</span></header>
                <dl>
                  <div><dt>계획 영향</dt><dd>{productionLossLabel(planningImpact?.estimatedLossUnits ?? null)}</dd></div>
                  <div><dt>상태</dt><dd>{planningImpact ? PLANNING_STATUS_LABEL[planningImpact.status] : "생산 영향 미산정"}</dd></div>
                  <div className="is-wide"><dt>근거</dt><dd>{PLANNING_MODEL_BASIS}</dd></div>
                  <div className="is-wide"><dt>다음 액션</dt><dd>{planningImpact ? `${planningImpact.nextAction}, 현장 점검 요청` : "데이터 품질 확인 필요"}</dd></div>
                </dl>
                <p>synthetic_capacity_model 기반 계획 영향 추정 · 고장확률, 위험도, top factor, 권고 판단을 변경하지 않습니다.</p>
              </section>
            </>
          ) : null}

          {role === "process_manager" && activeTab === "action" ? (
            <>
              <section className="mvp-overview-action-panel" aria-label="생산 관리자 처리">
                <header><ClipboardCheck size={14} /><strong>처리</strong><span>오더 후보</span></header>
                <div className="mvp-action-summary-card">
                  <MvpStatusBadge status={asset.status} />
                  <div>
                    <strong>{candidate?.suspectedPart ?? factors[0]?.label ?? asset.predictedFailureType}</strong>
                    <small>WO ID 미생성 · 권고 {DECISION_LABEL[asset.recommendedDecision]}</small>
                  </div>
                </div>
                <dl className="mvp-action-facts">
                  <div><dt>대상 설비</dt><dd>{asset.displayName}</dd></div>
                  <div><dt>계획 영향</dt><dd>{productionLossLabel(planningImpact?.estimatedLossUnits ?? null)}</dd></div>
                  <div><dt>담당</dt><dd>{asset.assignedEngineer ?? "미배정"}</dd></div>
                  <div><dt>부품</dt><dd>{displayPartLabel(asset.assetId, asset.sparePartAvailable)}</dd></div>
                  <div><dt>처리 상태</dt><dd>후보 검토</dd></div>
                  <div><dt>권한 액션</dt><dd>Work Orders에서 처리</dd></div>
                </dl>
                <div className="mvp-side-action-flow">
                  <button type="button" className="mvp-button secondary" onClick={() => onTabChange("status")}><LineChart size={14} />상태 다시 보기</button>
                  <button type="button" className="mvp-button primary" onClick={() => event && onOpenEvent(event.eventId, event.assetId)} disabled={!event}><ClipboardCheck size={14} />Work Orders에서 처리</button>
                  <button type="button" className="mvp-button ghost" onClick={() => onOpenReport(event?.eventId ?? null, asset.assetId)}><FileText size={14} />보고서 보기</button>
                </div>
                <p className="mvp-action-note">
                  승인, 보류, 반려, 메모 저장은 자동 실행하지 않고 Work Orders의 governed action에서 처리합니다.
                </p>
              </section>
            </>
          ) : null}

          {role === "field_operator" && activeTab === "status" ? (
            <>
              <section className="mvp-overview-report-graph mvp-side-map-report" aria-label="요약 리포트 피쳐 그래프">
                <header><LineChart size={14} /><strong>요약 리포트 시계열</strong><span>{detailLoading ? "불러오는 중" : detailError ? "상세 연결 실패" : "동일 snapshot"}</span></header>
                <div className="mvp-overview-risk-meter">
                  <div><span>위험 예측 확률</span><strong>{riskPercent === null ? "-" : `${riskPercent}%`}</strong></div>
                  <i aria-hidden="true"><b style={{ width: `${riskPercent ?? 0}%` }} /></i>
                  <small>고장 확정이 아니라 점검 우선순위 판단 근거입니다.</small>
                </div>
                <MapReportFeatureSeries
                  title={featureSnapshot?.label ?? "피쳐값 추이"}
                  unit={featureSnapshot?.unit ?? null}
                  points={featureSnapshot?.points ?? []}
                  emptyTitle="피쳐 이력 없음"
                  emptyDetail="현재 snapshot에는 피쳐 이력이 없어 임의 그래프를 표시하지 않습니다."
                />
                <DerivedMetricSlots />
              </section>

              <section className="mvp-overview-inspection-panel mvp-side-map-report" aria-label="점검할 설비 부품">
                <header><Wrench size={14} /><strong>점검할 설비 · 부품</strong><span>점검 요청 블록</span></header>
                <div className="equipment-sketch" aria-label="점검 위치 안내">
                  <div className="compressor-visual" aria-hidden="true">
                    <span className="vibration-zone" /><span className="pipe pipe-1" /><span className="pipe pipe-2" /><span className="pipe pipe-3" /><span className="pipe pipe-4" />
                    <span className="motor">모터</span><span className="shaft drive">축/벨트</span><span className="pump">압축부</span><span className="valve">배관/밸브<br />압력계</span><span className="tank">압력 탱크</span><span className="power-unit">전원부</span>
                    {inspectionTargets.length
                      ? inspectionTargets.map((target) => <mark key={target.factor.id} className={`callout ${target.location.className}`}>{target.rank}</mark>)
                      : <mark className={`callout ${fallbackInspectionLocation.className}`}>!</mark>}
                  </div>
                  <div>
                    <strong>{candidate?.suspectedPart ?? factors[0]?.label ?? asset.predictedFailureType}</strong>
                    <ul className="sketch-legend">
                      {inspectionTargets.length ? inspectionTargets.map((target) => (
                        <li key={target.factor.id}><b>{target.rank}</b>{target.location.range}: {target.location.note}</li>
                      )) : <li><b>!</b>점검 위치: 부품 근거 없음</li>}
                    </ul>
                  </div>
                </div>
                <div className="target-list">
                  {inspectionTargets.length ? (
                    inspectionTargets.map((target) => (
                      <article key={target.factor.id}>
                        <b>{target.rank}</b><i><Wrench size={18} /></i>
                        <div><strong>{target.factor.label} 확인</strong><p>{target.factor.direction === "risk_up" ? "위험 판단을 올린 주요 피쳐입니다." : "위험 판단을 낮춘 보조 피쳐입니다."}</p></div>
                        <span className="target-severity high">{factorValueLabel(target.factor)}</span>
                      </article>
                    ))
                  ) : (
                    <article>
                      <b>!</b><i><Wrench size={18} /></i>
                      <div><strong>{candidate?.suspectedPart ?? asset.predictedFailureType}</strong><p>상위 피쳐 근거가 없어 현장 점검 위치 확인이 필요합니다.</p></div>
                      <span className="target-severity high">근거 부족</span>
                    </article>
                  )}
                </div>
              </section>
            </>
          ) : null}

          {role === "field_operator" && activeTab === "action" ? (
            <section className="mvp-overview-action-panel" aria-label="현장 관리자 처리">
              <header><Wrench size={14} /><strong>현장 처리</strong><span>점검 후보</span></header>
              <div className="mvp-action-summary-card">
                <MvpStatusBadge status={asset.status} />
                <div>
                  <strong>{candidate?.suspectedPart ?? factors[0]?.label ?? asset.predictedFailureType}</strong>
                  <small>WO ID 미생성 · {planningImpact?.nextAction ?? "현장 점검 요청"}</small>
                </div>
              </div>
              <dl className="mvp-action-facts">
                <div><dt>대상 설비</dt><dd>{asset.displayName}</dd></div>
                <div><dt>의심 부품</dt><dd>{candidate?.suspectedPart ?? factors[0]?.label ?? "근거 부족"}</dd></div>
                <div><dt>점검 위치</dt><dd>{planningImpact?.line ?? asset.cell ?? asset.line}</dd></div>
                <div><dt>부품</dt><dd>{displayPartLabel(asset.assetId, asset.sparePartAvailable)}</dd></div>
                <div><dt>데이터 품질</dt><dd>{asset.status === "data_quality_hold" ? "데이터 품질 확인 필요" : "확인 가능"}</dd></div>
                <div><dt>다음 액션</dt><dd>{planningImpact?.nextAction ?? "현장 점검 요청"}</dd></div>
              </dl>
              <div className="mvp-side-action-flow">
                <button type="button" className="mvp-button secondary" onClick={() => onTabChange("status")}><LineChart size={14} />상태 다시 보기</button>
                <button type="button" className="mvp-button primary" onClick={() => event && onOpenEvent(event.eventId, event.assetId)} disabled={!event}><ClipboardCheck size={14} />Work Orders에서 처리</button>
                <button type="button" className="mvp-button ghost" onClick={() => onOpenReport(event?.eventId ?? null, asset.assetId)}><FileText size={14} />보고서 보기</button>
              </div>
              <p className="mvp-action-note">
                점검 요청 후보이며 WorkOrder/MaintenanceAction은 실제 생성하지 않습니다.
              </p>
            </section>
          ) : null}
        </div>
      ) : <MvpState kind="empty" title="선택된 설비가 없습니다" detail="왼쪽의 설비 또는 라인을 선택하세요." />}
    </MvpPanel>
  );
}

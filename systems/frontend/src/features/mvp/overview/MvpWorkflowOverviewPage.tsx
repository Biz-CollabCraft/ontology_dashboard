import {
  Activity,
  AlertTriangle,
  Bot,
  Clock3,
  ClipboardCheck,
  ClipboardList,
  DatabaseZap,
  Gauge,
  LineChart,
  Printer,
  RefreshCw,
  RotateCcw,
  Wrench,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  createMvpAgentReviewSummary,
  getMvpAgentReviewSummary,
  getOpenInspectionWorkOrders,
  type OpenInspectionWorkOrderReadModel,
} from "../../../api";
import type {
  MvpAgentReviewSummary,
  MvpAgentReviewSummaryResponse,
  MvpAsset,
  MvpBootstrapModel,
  MvpClosedLoopAvailableAction,
  MvpClosedLoopLifecycleStep,
  MvpClosedLoopLifecycleSummary,
  MvpClosedLoopPrimaryAction,
  MvpClosedLoopSummary,
  MvpClosedLoopTimelineItem,
  MvpEvent,
  MvpEventDetailModel,
  MvpFeatureHistoryWindow,
  MvpInspectionTarget,
  MvpReportTab,
  MvpRoleLens,
  MvpSensorWindowId,
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
import {
  displayAssetName,
  displayAssetShortName,
  displayAssetType,
  displayEventAssetName,
  displayEventLabel,
  displayProductionImpact,
  displayReviewPriority,
  displaySensorLabel,
  fieldFactorItem,
  fieldFactorSymptom,
  fieldFailureLabel,
} from "../displayLabels";
import { MaintenanceCostDecisionPanel } from "../maintenance/MaintenanceCostDecisionPanel";
import {
  MaintenanceWorkflowActionPanel,
  type MaintenanceWorkflowDisplayStatus,
  type PostMaintenancePredictionSummary,
} from "../maintenance/MaintenanceWorkflowActionPanel";

export interface WorkOrderCandidate {
  event: MvpEvent;
  asset: MvpAsset | null;
  suspectedPart: string;
}

interface LineImpactSummary {
  line: string;
  assets: MvpAsset[];
  highestRiskAsset: MvpAsset;
  averageRisk: number | null;
  critical: number;
  warning: number;
  hold: number;
  attention: number;
}

type DrawerTab = "status" | "action";
type FactorySlotKind = "cnc" | "compressor";
type WorkStatus =
  | "candidate_recommended"
  | "work_requested"
  | "assigned"
  | "inspection_started"
  | "inspection_completed"
  | "maintenance_started"
  | "maintenance_completed"
  | "observation_pending"
  | "prediction_blocked"
  | "ready_for_reprediction";

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

interface InspectionTargetView {
  target: MvpInspectionTarget | null;
  factor: MvpAsset["topFactors"][number] | null;
  rank: number;
}

function EquipmentSketchVisual({
  assetType,
  inspectionTargets,
}: {
  assetType: string;
  inspectionTargets: InspectionTargetView[];
}) {
  if (assetType.toLowerCase() === "cnc") {
    const toolingTarget = inspectionTargets.find((item) => (
      item.target?.componentId.includes("tool")
      || item.target?.componentLabel.includes("공구")
      || item.factor?.feature.includes("tool")
    ));
    const driveTarget = inspectionTargets.find((item) => (
      item.target?.componentId.includes("drive")
      || item.target?.componentLabel.includes("동력")
      || item.factor?.feature.includes("power")
      || item.factor?.feature.includes("torque")
    ));
    return (
      <div className="cnc-visual" aria-hidden="true">
        <span className="cnc-risk-zone" />
        <span className="cnc-base">베드</span>
        <span className="cnc-column">컬럼</span>
        <span className="cnc-head">스핀들</span>
        <span className="cnc-tool">공구대</span>
        <span className="cnc-table">테이블</span>
        <span className="cnc-workpiece">가공물</span>
        <span className="cnc-axis x-axis">X축</span>
        <span className="cnc-axis z-axis">Z축</span>
        <span className="cnc-servo">서보/구동</span>
        <span className="cnc-coolant">냉각</span>
        <span className="cnc-control">제어반</span>
        {toolingTarget ? <span className="callout cnc-tool-callout">{toolingTarget.rank}</span> : null}
        {driveTarget ? <span className="callout cnc-drive-callout">{driveTarget.rank}</span> : null}
      </div>
    );
  }
  return (
    <div className="compressor-visual" aria-hidden="true">
      <span className="vibration-zone" /><span className="pipe pipe-1" /><span className="pipe pipe-2" /><span className="pipe pipe-3" /><span className="pipe pipe-4" />
      <span className="motor">모터</span><span className="shaft drive">축/벨트</span><span className="pump">압축부</span><span className="valve">배관/밸브<br />압력계</span><span className="tank">압력 탱크</span><span className="power-unit">전원부</span>
    </div>
  );
}

interface FactoryCellSlot {
  id: string;
  assetId: string;
  label: string;
  kind: FactorySlotKind;
  asset: MvpAsset | null;
}

interface FactoryCellLayout {
  id: string;
  site: string;
  cell: string;
  label: string;
  slots: FactoryCellSlot[];
  summary: LineImpactSummary | null;
  planUnits: number | null;
}

interface FactorySlotPreview {
  slot: FactoryCellSlot;
  cell: FactoryCellLayout;
}

const MISSING_PLANNING_BASIS = "생산계획 ViewModel 미연결";
const FACTORY_SITE_IDS = ["S01", "S02", "S03", "S04"];
const FACTORY_CELL_IDS = ["L01", "L02", "L03", "L04", "L05"];
const FACTORY_LAYOUT_NOTICE = "데모 배치 화면 · 상태와 위험도는 연결된 설비 데이터만 표시";
const FACTORY_SITE_LABELS: Record<string, string> = {
  S01: "1구역",
  S02: "2구역",
  S03: "3구역",
  S04: "4구역",
};

const PLANNING_STATUS_LABEL: Record<PlanningImpactRow["status"], string> = {
  plan_at_risk: "계획 위험",
  shift_inspection: "교대 내 점검",
  inspection_priority: "점검 우선",
  data_quality_hold: "데이터 품질 확인 필요",
};

const WORK_STATUS_LABEL: Record<WorkStatus, string> = {
  candidate_recommended: "후보 추천됨",
  work_requested: "작업 요청됨",
  assigned: "담당자 배정됨",
  inspection_started: "점검 중",
  inspection_completed: "점검 완료·정비 검토",
  maintenance_started: "정비 중",
  maintenance_completed: "정비 완료",
  observation_pending: "정비 후 관측 대기",
  prediction_blocked: "정비 후 예측 중단",
  ready_for_reprediction: "정비 후 예측 완료",
};

const WORK_STATUS_ACTION: Record<WorkStatus, { label: string; disabled: boolean }> = {
  candidate_recommended: { label: "작업 요청", disabled: false },
  work_requested: { label: "요청 수락·내게 배정", disabled: false },
  assigned: { label: "점검 시작", disabled: false },
  inspection_started: { label: "점검 결과 기록", disabled: false },
  inspection_completed: { label: "비용 확인·정비 판단", disabled: true },
  maintenance_started: { label: "정비 완료", disabled: false },
  maintenance_completed: { label: "정비 후 관측 대기", disabled: true },
  observation_pending: { label: "관측 데이터 대기", disabled: true },
  prediction_blocked: { label: "예측 상태 확인 필요", disabled: true },
  ready_for_reprediction: { label: "정비 효과 확인", disabled: false },
};

const CLOSED_LOOP_LIFECYCLE_LABEL: Record<MvpClosedLoopLifecycleStep, string> = {
  prediction: "예측",
  evidence: "근거 확인",
  decision: "판단",
  inspection_requested: "점검 요청",
  inspection_approved: "담당 배정",
  inspection_in_progress: "점검 중",
  inspection_completed: "점검 완료",
  recommendation_proposed: "정비안 제안",
  maintenance_requested: "정비 요청",
  maintenance_approved: "정비 승인",
  maintenance_in_progress: "정비 중",
  maintenance_completed: "정비 완료",
  post_maintenance_observation_pending: "정비 후 관측 대기",
  ready_for_reprediction: "재예측 가능",
};

const REPORT_OUTPUT_OPTIONS: Array<{ id: MvpReportTab; label: string; detail: string }> = [
  { id: "status-map", label: "상태 요약", detail: "설비 맵과 위험 상태" },
  { id: "inspection-request", label: "점검 요청", detail: "현장 확인 항목" },
  { id: "summary-report", label: "요약 보고서", detail: "관리자 공유본" },
  { id: "executive-brief", label: "Executive Brief", detail: "선택 이벤트 보고서" },
];

type WorkQueueColumnId = "candidate" | "requested" | "inspection" | "observe" | "repredict";

const WORK_QUEUE_COLUMNS: Array<{ id: WorkQueueColumnId; label: string; detail: string }> = [
  { id: "candidate", label: "후보", detail: "추천됨" },
  { id: "requested", label: "요청", detail: "요청·배정" },
  { id: "inspection", label: "점검 중", detail: "현장 진행" },
  { id: "observe", label: "관측 대기", detail: "완료 후 확인" },
  { id: "repredict", label: "재예측", detail: "다음 판단" },
];

const SENSOR_WINDOW_OPTIONS: Array<{ id: MvpSensorWindowId; label: string; hours: number }> = [
  { id: "24h", label: "24시간", hours: 24 },
  { id: "7d", label: "7일", hours: 24 * 7 },
  { id: "30d", label: "30일", hours: 24 * 30 },
];

const DERIVED_FEATURE_KEYS = new Set(["temperature_difference_k", "mechanical_power_w", "overstrain_index"]);
const PRIMARY_FIELD_SENSOR_KEYS = new Set(["torque_nm", "tool_wear_min", "rotational_speed_rpm"]);

function partLabel(value: boolean | null): string {
  if (value === true) return "확보";
  if (value === false) return "미확보";
  return "확인 필요";
}

function productionLossLabel(value: number | null): string {
  return value === null ? "생산 영향 미산정" : `${value.toLocaleString()}개 예상`;
}

function displayPartLabel(value: boolean | null): string {
  return partLabel(value);
}

function agentSummaryStatusLabel(trace: MvpAgentReviewSummaryResponse["trace"] | null, summary: MvpAgentReviewSummary | null): string {
  if (trace?.materialization?.reused) return "저장본 재사용";
  const status = trace?.materialization?.status;
  if (status === "pending") return "생성 대기";
  if (status === "ready") return "검증 완료";
  if (status === "fallback") return "검증 fallback";
  if (status === "failed") return "생성 실패";
  if (status === "stale") return "갱신 필요";
  if (summary?.mode === "llm") return "LLM 검증 완료";
  if (summary?.mode === "deterministic_fallback") return "규칙 기반 요약";
  return "조회 대기";
}

function agentSummaryModeLabel(summary: MvpAgentReviewSummary | null): string {
  if (summary?.mode === "llm") return "LLM 요약";
  if (summary?.mode === "deterministic_fallback") return "규칙 기반 fallback";
  return "미생성";
}

function agentSummaryWorkflowRunLabel(trace: MvpAgentReviewSummaryResponse["trace"] | null): string {
  const run = trace?.workflow_run;
  if (!run) return trace?.materialization?.workflow_run_id ? "저장 run" : "미연결";
  const triggerLabel = run.trigger === "polling_watcher"
    ? "watcher"
    : run.trigger === "ui_manual_regeneration"
      ? "수동 갱신"
      : "수동 생성";
  const statusLabel = run.status === "completed"
    ? "완료"
    : run.status === "partial"
      ? "부분 완료"
      : run.status === "failed"
        ? "실패"
        : "진행 중";
  return `${triggerLabel} · ${statusLabel}`;
}

function agentSummaryWorkflowRunTime(trace: MvpAgentReviewSummaryResponse["trace"] | null): string | null {
  const completedAt = trace?.workflow_run?.completed_at;
  if (!completedAt) return null;
  return formatTimestamp(completedAt);
}

function formatAgentHistoryItem(value: string): string {
  return value.replace(
    /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g,
    (match) => formatCompactHistoryTimestamp(match),
  );
}

function formatCompactHistoryTimestamp(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  const source = value.match(/^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (source && source[3] === "00" && source[4] === "00") {
    return `${source[1]}.${source[2]} 오전 9시`;
  }
  const date = new Date(timestamp);
  const parts = new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: "2-digit",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "";
  const minute = part("minute");
  const minuteLabel = minute === "00" ? "" : ` ${Number(minute)}분`;
  return `${part("month")}.${part("day")} ${part("dayPeriod")} ${Number(part("hour"))}시${minuteLabel}`;
}

function extractPartCandidateFromQuote(quote: string | null | undefined): string | null {
  if (!quote) return null;
  const match = quote.match(/참고 부품 후보는\s+(.+?)입니다/);
  return match?.[1] ?? null;
}

function closedLoopWorkOrderStatusLabel(status: string | null | undefined): string {
  if (status === "requested") return "요청 접수";
  if (status === "approved") return "승인됨";
  if (status === "in_progress") return "점검 중";
  if (status === "completed") return "완료";
  if (status === "blocked") return "보류";
  if (status === "failed") return "실패";
  if (status === "cancelled") return "취소";
  return "상태 확인 필요";
}

function agentQuoteStatusLabel(value: string): string {
  if (value === "critical") return "위험";
  if (value === "warning") return "경고";
  return value;
}

const AGENT_QUOTE_KEYWORD_PATTERN = /(critical|warning|생산 영향이 [^,이며.]+|약 [0-9,]+건 손실 가능성|[0-9]+분 기준|공구\/마모 계통|동력 전달 계통|공구 매거진 및 스핀들 공구 체결부|주축 모터, 커플링, 동력 전달 하우징|기계 동력|공구 마모|과부하 지표|토크|알람|사진|관측값|기록|전달|정비\/생산 관리자|점검 요청|요청됨 상태|참고 부품 후보는 [^.]+|최근 유사 이력은 [^.]+|승인|우선순위|셀 작업 순서 조정)/g;
const AGENT_QUOTE_KEYWORD_EXACT_PATTERN = /^(critical|warning|생산 영향이 [^,이며.]+|약 [0-9,]+건 손실 가능성|[0-9]+분 기준|공구\/마모 계통|동력 전달 계통|공구 매거진 및 스핀들 공구 체결부|주축 모터, 커플링, 동력 전달 하우징|기계 동력|공구 마모|과부하 지표|토크|알람|사진|관측값|기록|전달|정비\/생산 관리자|점검 요청|요청됨 상태|참고 부품 후보는 [^.]+|최근 유사 이력은 [^.]+|승인|우선순위|셀 작업 순서 조정)$/;

function renderHighlightedAgentQuote(quote: string) {
  return quote.split(AGENT_QUOTE_KEYWORD_PATTERN).map((part, index) => {
    if (!part) return null;
    return AGENT_QUOTE_KEYWORD_EXACT_PATTERN.test(part)
      ? <strong key={`${part}-${index}`}>{agentQuoteStatusLabel(part)}</strong>
      : <span key={`${part}-${index}`}>{part}</span>;
  });
}

function agentRoleSummaryCaption(role: MvpRoleLens, label: string): string {
  return role === "field_operator"
    ? `${label} · 확인/기록/전달`
    : `${label} · 영향/승인/순서`;
}

function agentRoleSummaryHint(role: MvpRoleLens): string {
  return role === "field_operator"
    ? "현장 위치에서 이상 근거를 기록하고 정비/생산 관리자에게 넘기는 범위입니다."
    : "생산 영향, 승인 판단, 셀 작업 순서를 검토하는 범위입니다.";
}

function displayFactorySite(site: string): string {
  return FACTORY_SITE_LABELS[site] ?? site;
}

function displayFactoryCell(cell: string): string {
  const suffix = cell.match(/-L(\d+)$/)?.[1];
  return suffix ? `${Number(suffix)}셀` : cell;
}

function factorySlotLabel(kind: FactorySlotKind, slotIndex: number): string {
  if (kind === "compressor") return "공기압축기";
  return `CNC 가공기 ${slotIndex}`;
}

function displayFactoryAssetName(assetId: string): string | null {
  const match = assetId.match(/^(CNC|CMP)-(S\d+)-L(\d+)-(\d+)$/);
  if (!match) return null;
  const [, prefix, site, line, slot] = match;
  const cell = `${site}-L${line}`;
  const kind: "cnc" | "compressor" = prefix === "CMP" ? "compressor" : "cnc";
  return `${displayFactorySite(site)} · ${displayFactoryCell(cell)} · ${factorySlotLabel(kind, Number(slot))}`;
}

function canonicalSlotAssetId(site: string, cell: string, kind: FactorySlotKind, slotIndex: number): string {
  const line = cell.match(/^L\d+$/) ? cell : cell.match(/-L(\d+)$/)?.[1] ? `L${cell.match(/-L(\d+)$/)?.[1]}` : cell;
  const prefix = kind === "compressor" ? "CMP" : "CNC";
  return `${prefix}-${site}-${line}-${String(slotIndex).padStart(2, "0")}`;
}

function displayFactorySlotName(slot: FactoryCellSlot, cell: FactoryCellLayout): string {
  return `${displayFactorySite(cell.site)} · ${displayFactoryCell(cell.cell)} · ${slot.label}`;
}

function canonicalCellKeyFromAsset(asset: Pick<MvpAsset, "assetId" | "site" | "line" | "cell">): string | null {
  const fromAssetId = asset.assetId.match(/^[A-Z]+-(S\d+-L\d+)-/)?.[1];
  if (fromAssetId) return fromAssetId;
  if (/^S\d+-L\d+$/.test(asset.cell)) return asset.cell;
  if (/^S\d+-L\d+$/.test(asset.line)) return asset.line;
  if (/^L\d+$/.test(asset.cell) && /^S\d+$/.test(asset.site)) return `${asset.site}-${asset.cell}`;
  if (/^L\d+$/.test(asset.line) && /^S\d+$/.test(asset.site)) return `${asset.site}-${asset.line}`;
  return null;
}

function riskTone(summary: Pick<LineImpactSummary, "critical" | "warning" | "hold"> & { attention?: number }): "critical" | "warning" | "hold" | "attention" | "normal" {
  if (summary.critical > 0) return "critical";
  if (summary.warning > 0) return "warning";
  if (summary.hold > 0) return "hold";
  if ((summary.attention ?? 0) > 0) return "attention";
  return "normal";
}

function mapTone(status: MvpAsset["status"]): "critical" | "warning" | "attention" | "normal" | "hold" {
  return status === "data_quality_hold" ? "hold" : status;
}

function suspectedPartLabel(event: MvpEvent, asset: MvpAsset | null): string {
  const factor = asset?.topFactors[0];
  if (factor?.feature) return fieldFactorItem(factor);
  if (event.predictedFailureType && event.predictedFailureType !== "unavailable") return fieldFailureLabel(event.predictedFailureType);
  return "부품 근거 없음";
}

function inspectionBasisLabel(ref: string): string {
  const normalized = ref
    .replace(/^factor\.\d+\./, "")
    .replace(/^sensor_evidence\.sensors\./, "");
  const label = displaySensorLabel(normalized);
  if (ref.startsWith("sensor_evidence.sensors.")) return `${label} 센서값`;
  if (ref.startsWith("factor.")) return `${label} 이상 기여`;
  return label;
}

function inspectionBasisSummary(target: MvpInspectionTarget): string {
  const labels = target.basisRefs.map(inspectionBasisLabel);
  const uniqueLabels = [...new Set(labels)];
  return uniqueLabels.length ? uniqueLabels.join(", ") : "Evidence 근거 요약 미제공";
}

function inspectionTopFactorBundleSummary(target: MvpInspectionTarget): string | null {
  const factorLabels = target.basisRefs
    .filter((ref) => ref.startsWith("factor."))
    .map((ref) => inspectionBasisLabel(ref).replace(/ 이상 기여$/, ""));
  const uniqueLabels = [...new Set(factorLabels)];
  if (!uniqueLabels.length) return null;
  return `위험 판단에 반영된 지표 ${uniqueLabels.length}개: ${uniqueLabels.join(", ")}`;
}

function inspectionLocationLabel(target: MvpInspectionTarget | null): string {
  if (!target) return "위치 근거 미제공";
  return target.locationLabel ?? target.inspectionGuidance?.referenceLocationLabel ?? "점검 위치 근거 미제공";
}

function inspectionMethodLabel(target: MvpInspectionTarget | null): string {
  if (!target) return "Backend 점검 위치 계약 연결 후 표시됩니다.";
  return target.inspectionMethod
    ?? target.inspectionGuidance?.suggestedCheckMethod
    ?? "Backend 점검 위치 계약 연결 후 표시됩니다.";
}

function inspectionGuidanceSourceLabel(target: MvpInspectionTarget | null): string {
  if (!target?.inspectionGuidance) return "점검 위치 계약 미연결";
  return target.inspectionGuidance.sourceType === "demo_sop_fixture"
    ? "데모 SOP"
    : "SOP";
}

function replacementReviewTitle(target: MvpInspectionTarget): string {
  return target.inspectionGuidance?.maintenanceReviewPrerequisites?.label
    ?? "AI 근거 요약: 교체 시기 검토";
}

function maintenanceReviewPrerequisitePreview(target: MvpInspectionTarget | null): string[] {
  const guidance = target?.inspectionGuidance?.maintenanceReviewPrerequisites;
  if (!guidance) return [];
  return [
    ...guidance.reviewConditions.slice(0, 2).map(replacementReviewEvidenceLabel),
    ...guidance.requiredMeasurements.slice(0, 1).map(replacementReviewEvidenceLabel),
  ];
}

function replacementReviewEvidenceLabel(value: string): string {
  const normalized = value.toLowerCase();
  if (value.includes("동일 부품 후보") || normalized.includes("same part")) {
    return "동일 부품 후보가 반복해서 상위 위험 근거와 연결됩니다.";
  }
  if (value.includes("마모") || value.includes("진동") || value.includes("토크") || value.includes("온도")) {
    return "마모, 진동, 토크, 온도 관측값이 최근 이력 대비 나빠지는지 확인합니다.";
  }
  if (value.includes("현재 센서") || value.includes("최근 이력") || normalized.includes("current sensor")) {
    return "현재 센서값과 최근 이력을 비교해 실제 악화 흐름인지 확인합니다.";
  }
  if (value.includes("현장") || value.includes("체결") || value.includes("열화")) {
    return "현장 점검 결과와 센서 근거가 같은 계통을 가리키는지 대조합니다.";
  }
  return value;
}

function replacementReviewBoundaryLabel(target: MvpInspectionTarget): string {
  const boundary = target.inspectionGuidance?.maintenanceReviewPrerequisites?.decisionBoundary;
  if (!boundary) return "";
  return "AI가 읽은 근거 요약이며, 교체 확정이나 작업요청 생성은 담당자 검토 후 진행합니다.";
}

function buildLineImpactSummaries(assets: MvpAsset[]): LineImpactSummary[] {
  const groups = new Map<string, MvpAsset[]>();
  assets.forEach((asset) => {
    // Factory layout identity comes from the canonical equipment id. Event
    // projections can carry a site-level or display-oriented `line`, which is
    // useful in reports but must not override the Sxx-Lxx cell identity used
    // to color the live equipment map.
    const key = canonicalCellKeyFromAsset(asset) ?? asset.line ?? asset.cell ?? "라인 근거 없음";
    groups.set(key, [...(groups.get(key) ?? []), asset]);
  });
  return Array.from(groups.entries()).map(([line, group]) => {
    const riskValues = group.map((asset) => asset.failureProbability).filter((value): value is number => value !== null);
    const highestRiskAsset = [...group].sort((a, b) => (b.failureProbability ?? -1) - (a.failureProbability ?? -1))[0];
    return {
      line,
      assets: group,
      highestRiskAsset,
      averageRisk: riskValues.length ? riskValues.reduce((sum, value) => sum + value, 0) / riskValues.length : null,
      critical: group.filter((asset) => asset.status === "critical").length,
      warning: group.filter((asset) => asset.status === "warning").length,
      hold: group.filter((asset) => asset.status === "data_quality_hold").length,
      attention: group.filter((asset) => asset.status === "attention").length,
    };
  }).sort((a, b) => {
    const toneWeight = { critical: 4, warning: 3, hold: 2, attention: 1, normal: 0 };
    return toneWeight[riskTone(b)] - toneWeight[riskTone(a)] || (b.averageRisk ?? -1) - (a.averageRisk ?? -1);
  });
}

function factorValueLabel(factor: MvpAsset["topFactors"][number]): string {
  if (factor.value === null) return "근거 부족";
  return `${factor.value.toLocaleString()}${factor.unit ? ` ${factor.unit}` : ""}`;
}

interface SeriesDatum {
  observedAt: string;
  value: number | null;
  qualityStatus?: "good" | "bad" | "unknown";
}

function formatSeriesTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function timestampMillis(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : time;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function filterSeriesPoints(points: SeriesDatum[], currentObservedAt: string | null | undefined, windowId: MvpSensorWindowId): SeriesDatum[] {
  const selected = SENSOR_WINDOW_OPTIONS.find((option) => option.id === windowId) ?? SENSOR_WINDOW_OPTIONS[0];
  const anchor = timestampMillis(currentObservedAt)
    ?? points.map((point) => timestampMillis(point.observedAt)).filter((time): time is number => time !== null).sort((left, right) => right - left)[0]
    ?? null;
  if (anchor === null) return points;
  const start = anchor - selected.hours * 60 * 60 * 1000;
  return points.filter((point) => {
    const observedAt = timestampMillis(point.observedAt);
    return observedAt === null || observedAt >= start;
  });
}

function seriesRangeLabel(points: SeriesDatum[], windowId: MvpSensorWindowId, window: MvpFeatureHistoryWindow | null | undefined): string {
  const selected = SENSOR_WINDOW_OPTIONS.find((option) => option.id === windowId) ?? SENSOR_WINDOW_OPTIONS[0];
  if (window?.requested === windowId) {
    if (window.coverageStatus === "empty" || window.pointCount === 0) return `${selected.label} 선택 · 관측 없음`;
    if (window.coverageStatus === "partial") return `${selected.label} 선택 · 관측 이력 일부만 제공`;
    if (window.coverageStatus === "unknown") return `${selected.label} 선택 · 관측 범위 검증 전`;
    return `${selected.label} 선택 · 관측 이력 제공`;
  }
  const timestamps = points.map((point) => timestampMillis(point.observedAt)).filter((time): time is number => time !== null).sort((left, right) => left - right);
  if (timestamps.length < 2) return `${selected.label} 선택 · 제공된 관측 이력 분포`;
  const hours = Math.max(1, Math.round((timestamps[timestamps.length - 1] - timestamps[0]) / (60 * 60 * 1000)));
  const provided = hours < 48 ? `${hours}시간` : `${Math.round(hours / 24)}일`;
  return `${selected.label} 선택 · 제공 ${provided} 이력 분포`;
}

function percentile(sortedValues: number[], ratio: number): number {
  if (!sortedValues.length) return 0;
  const position = (sortedValues.length - 1) * ratio;
  const lowerIndex = Math.floor(position);
  const upperIndex = Math.ceil(position);
  const lowerValue = sortedValues[lowerIndex] ?? sortedValues[0];
  const upperValue = sortedValues[upperIndex] ?? sortedValues[sortedValues.length - 1];
  return lowerValue + (upperValue - lowerValue) * (position - lowerIndex);
}

function distributionScale(values: number[]) {
  const sortedValues = [...values].sort((left, right) => left - right);
  const minimum = sortedValues[0] ?? 0;
  const maximum = sortedValues[sortedValues.length - 1] ?? 1;
  const p10 = percentile(sortedValues, 0.1);
  const p25 = percentile(sortedValues, 0.25);
  const p75 = percentile(sortedValues, 0.75);
  const p90 = percentile(sortedValues, 0.9);
  const absoluteScale = Math.max(Math.abs(maximum), Math.abs(minimum), 1);
  const spread = Math.max(maximum - minimum, absoluteScale * 0.02, Number.EPSILON);
  const iqr = Math.max(p75 - p25, spread);
  const domainMinimum = Math.min(minimum, p25 - iqr * 0.65);
  const domainMaximum = Math.max(maximum, p75 + iqr * 0.65);
  const domainSpan = Math.max(domainMaximum - domainMinimum, spread, Number.EPSILON);
  return {
    minimum: domainMinimum - domainSpan * 0.08,
    maximum: domainMaximum + domainSpan * 0.08,
    bandLower: p10,
    bandUpper: p90,
  };
}

function sensorSeries(detail: MvpEventDetailModel | null, asset: MvpAsset | null) {
  if (!detail || detail.event.assetId !== asset?.assetId) return [];
  return detail.sensors.map((sensor) => ({
    id: sensor.id,
    label: displaySensorLabel(sensor.id, sensor.label),
    unit: sensor.unit,
    currentValue: sensor.value,
    currentObservedAt: sensor.observedAt,
    currentQuality: sensor.qualityStatus ?? "unknown",
    window: sensor.historyWindow ?? null,
    points: (sensor.historyPoints ?? []).map((point) => ({
      observedAt: point.observedAt,
      value: typeof point.value === "number" && Number.isFinite(point.value) ? point.value : null,
      qualityStatus: point.qualityStatus,
    })),
  }));
}

function productionImpactLevelLabel(summary: LineImpactSummary, detail: MvpEventDetailModel | null): string {
  const hasSelectedAsset = detail ? summary.assets.some((asset) => asset.assetId === detail.event.assetId) : false;
  return hasSelectedAsset
    ? displayProductionImpact(detail?.operationContext?.productionImpact)
    : "생산 영향 수준 미연결";
}

function planningImpactFromOperationContext(detail: MvpEventDetailModel | null): PlanningImpactRow | null {
  const impact = detail?.operationContext?.eventImpact;
  if (!impact) return null;
  const status: PlanningImpactRow["status"] =
    impact.screenPriority === "plan_at_risk"
      ? "plan_at_risk"
      : impact.screenPriority === "shift_inspection"
        ? "shift_inspection"
        : impact.screenPriority === "data_check_required" || impact.impactStatus === "withheld_data_quality_hold"
          ? "data_quality_hold"
          : "inspection_priority";
  return {
    assetId: impact.equipmentId,
    eventId: impact.eventId,
    line: impact.line,
    productLabel: impact.productVariant,
    estimatedLossUnits: impact.estimatedLostUnits,
    status,
    nextAction: status === "data_quality_hold" ? "데이터 품질 확인 필요" : "처리 탭에서 검토",
    sparePartAvailable: null,
  };
}

function plannedUnitsFromDetail(detail: MvpEventDetailModel | null): { value: number | null; fallback: boolean } {
  const plannedUnits = detail?.operationContext?.productionPlan?.plannedUnits;
  return typeof plannedUnits === "number"
    ? { value: plannedUnits, fallback: false }
    : { value: null, fallback: true };
}

function planningBasisFromDetail(detail: MvpEventDetailModel | null): { value: string; fallback: boolean } {
  const basis = detail?.operationContext?.capacityModel?.basis;
  return basis
    ? { value: basis, fallback: false }
    : { value: MISSING_PLANNING_BASIS, fallback: true };
}

function latestClosedLoopWorkOrder(closedLoop: MvpClosedLoopSummary | null | undefined) {
  return [...(closedLoop?.workOrders ?? [])].sort((left, right) => String(right.updatedAt ?? right.createdAt ?? "").localeCompare(String(left.updatedAt ?? left.createdAt ?? "")))[0] ?? null;
}

function latestClosedLoopMaintenanceAction(closedLoop: MvpClosedLoopSummary | null | undefined) {
  return [...(closedLoop?.maintenanceActions ?? [])].sort((left, right) => String(right.completedAt ?? right.startedAt ?? "").localeCompare(String(left.completedAt ?? left.startedAt ?? "")))[0] ?? null;
}

function latestClosedLoopMaintenanceEvent(closedLoop: MvpClosedLoopSummary | null | undefined) {
  return [...(closedLoop?.maintenanceEvents ?? [])].sort((left, right) => String(right.completedAt ?? "").localeCompare(String(left.completedAt ?? "")))[0] ?? null;
}

export function workStatusFromLifecycleStep(step: MvpClosedLoopLifecycleStep | null | undefined): WorkStatus | null {
  switch (step) {
    case "prediction":
    case "evidence":
    case "decision":
      return "candidate_recommended";
    case "inspection_requested":
      return "work_requested";
    case "inspection_approved":
      return "assigned";
    case "inspection_in_progress":
      return "inspection_started";
    case "inspection_completed":
    case "recommendation_proposed":
    case "maintenance_requested":
    case "maintenance_approved":
      return "inspection_completed";
    case "maintenance_in_progress":
      return "maintenance_started";
    case "maintenance_completed":
      return "maintenance_completed";
    case "post_maintenance_observation_pending":
      return "observation_pending";
    case "ready_for_reprediction":
      return "ready_for_reprediction";
    default:
      return null;
  }
}

function workStatusFromLifecycleSummary(summary: MvpClosedLoopLifecycleSummary | null | undefined): WorkStatus | null {
  return workStatusFromLifecycleStep(summary?.currentStep);
}

function workStatusFromInspectionWorkflow(
  workOrder: OpenInspectionWorkOrderReadModel | null | undefined,
): WorkStatus | null {
  if (!workOrder) return null;
  if (workOrder.current_step === "post_maintenance_prediction_blocked") {
    return "prediction_blocked";
  }
  const lifecycleStatus = workStatusFromLifecycleStep(workOrder.current_step);
  if (lifecycleStatus) return lifecycleStatus;
  if (workOrder.status === "requested") return "work_requested";
  if (workOrder.status === "approved") return "assigned";
  if (workOrder.status === "in_progress") return "inspection_started";
  if (workOrder.status === "completed") return "inspection_completed";
  return null;
}

export function prioritizeActiveWorkflowCandidates(
  candidates: WorkOrderCandidate[],
  workOrders: OpenInspectionWorkOrderReadModel[],
): WorkOrderCandidate[] {
  const candidatesByAsset = new Map<string, WorkOrderCandidate>();
  for (const workOrder of workOrders) {
    const candidate = candidates.find((item) => item.event.eventId === workOrder.event_id)
      ?? candidates.find((item) => item.event.assetId === workOrder.asset_id);
    if (candidate && !candidatesByAsset.has(workOrder.asset_id)) {
      candidatesByAsset.set(workOrder.asset_id, candidate);
    }
  }
  for (const candidate of candidates) {
    if (!candidatesByAsset.has(candidate.event.assetId)) {
      candidatesByAsset.set(candidate.event.assetId, candidate);
    }
  }
  return [...candidatesByAsset.values()];
}

function workStatusFromClosedLoop(closedLoop: MvpClosedLoopSummary | null | undefined): WorkStatus | null {
  const lifecycleStatus = workStatusFromLifecycleSummary(closedLoop?.lifecycleSummary);
  if (lifecycleStatus) return lifecycleStatus;
  const runtimeStatus = closedLoop?.runtimeStatus;
  if (runtimeStatus === "predicted" || runtimeStatus === "ready") return "ready_for_reprediction";
  if (runtimeStatus === "warming_up" || runtimeStatus === "history_insufficient") return "observation_pending";
  if (latestClosedLoopMaintenanceEvent(closedLoop)) return "maintenance_completed";
  const action = latestClosedLoopMaintenanceAction(closedLoop);
  if (action?.status === "completed") return "maintenance_completed";
  if (action?.status === "in_progress") return "maintenance_started";
  if (action?.status === "planned") return "assigned";
  const workOrder = latestClosedLoopWorkOrder(closedLoop);
  if (workOrder?.status === "completed") {
    return workOrder.workType === "inspection" ? "inspection_completed" : "maintenance_completed";
  }
  if (workOrder?.status === "in_progress") {
    return workOrder.workType === "inspection" ? "inspection_started" : "maintenance_started";
  }
  if (workOrder?.status === "approved") return "assigned";
  if (workOrder?.status === "requested") return "work_requested";
  return null;
}

function closedLoopActionForStatus(closedLoop: MvpClosedLoopSummary | null | undefined, status: WorkStatus) {
  const actionIdsByStatus: Record<WorkStatus, string[]> = {
    candidate_recommended: ["create_inspection_work_order", "request_inspection_work_order", "request_inspection"],
    work_requested: ["accept_inspection_work_order"],
    assigned: ["start_inspection_work_order", "start_inspection"],
    inspection_started: ["complete_inspection_work_order", "complete_inspection", "complete_work_order"],
    inspection_completed: [],
    maintenance_started: ["complete_maintenance_work_order", "complete_maintenance", "complete_work_order"],
    maintenance_completed: [],
    observation_pending: [],
    prediction_blocked: [],
    ready_for_reprediction: ["view_reprediction", "request_reprediction"],
  };
  const actionIds = actionIdsByStatus[status];
  return (closedLoop?.availableActions ?? []).find((action) => actionIds.includes(action.actionId)) ?? null;
}

function primaryClosedLoopAction(
  closedLoop: MvpClosedLoopSummary | null | undefined,
  status: WorkStatus | null,
): MvpClosedLoopPrimaryAction | MvpClosedLoopAvailableAction | null {
  if (closedLoop?.primaryAction) return closedLoop.primaryAction;
  return status ? closedLoopActionForStatus(closedLoop, status) : null;
}

function closedLoopAssignee(closedLoop: MvpClosedLoopSummary | null | undefined): string | null {
  const workOrder = latestClosedLoopWorkOrder(closedLoop);
  const action = latestClosedLoopMaintenanceAction(closedLoop);
  const activity = [...(closedLoop?.activities ?? [])].reverse().find((item) => item.actorDisplayName);
  return workOrder?.actorDisplayName ?? workOrder?.assignedTo ?? action?.actorDisplayName ?? activity?.actorDisplayName ?? null;
}

function closedLoopWorkIdLabel(closedLoop: MvpClosedLoopSummary | null | undefined): string {
  const workOrder = latestClosedLoopWorkOrder(closedLoop);
  if (workOrder) return workOrder.workOrderId;
  return "작업요청 미생성";
}

function workStatusForAsset(_asset: MvpAsset | null, _event: MvpEvent | null): WorkStatus {
  return "candidate_recommended";
}

function workQueueColumn(status: WorkStatus): WorkQueueColumnId {
  if (status === "candidate_recommended") return "candidate";
  if (status === "work_requested" || status === "assigned") return "requested";
  if (status === "inspection_started" || status === "inspection_completed" || status === "maintenance_started") return "inspection";
  if (
    status === "maintenance_completed"
    || status === "observation_pending"
    || status === "prediction_blocked"
  ) return "observe";
  return "repredict";
}

function WorkStatusFixedBar({
  status,
  actionLabel,
  statusSource,
  disabled = false,
  loading = false,
  onAction,
}: {
  status: WorkStatus;
  actionLabel?: string | null;
  statusSource?: string;
  disabled?: boolean;
  loading?: boolean;
  onAction?: () => void;
}) {
  const action = WORK_STATUS_ACTION[status];
  const nextActionLabel = actionLabel ?? action.label;
  const actionDisabled = disabled || action.disabled || loading;
  return (
    <section className="mvp-work-status-bar" aria-label="작업 상태">
      <div><span>현재 상태{statusSource ? ` · ${statusSource}` : ""}</span><strong>{WORK_STATUS_LABEL[status]}</strong></div>
      <div><span>다음 권장 액션</span><strong>{nextActionLabel}</strong></div>
      <button
        type="button"
        className="mvp-button primary"
        disabled={actionDisabled}
        onClick={onAction}
      >
        {loading ? <RefreshCw className="mvp-action-spinner" size={14} /> : <ClipboardCheck size={14} />}
        {loading ? "처리 중" : nextActionLabel}
      </button>
    </section>
  );
}

function WorkStatusPrimaryAction({
  status,
  actionLabel,
  helperText,
  disabled = false,
  loading = false,
  onAction,
}: {
  status: WorkStatus;
  actionLabel?: string | null;
  helperText?: string;
  disabled?: boolean;
  loading?: boolean;
  onAction?: () => void;
}) {
  const action = WORK_STATUS_ACTION[status];
  const nextActionLabel = actionLabel ?? action.label;
  const actionDisabled = disabled || action.disabled || loading;
  return (
    <div className="mvp-work-primary-action">
      <button type="button" className="mvp-button primary" disabled={actionDisabled} onClick={onAction}>
        {loading ? <RefreshCw className="mvp-action-spinner" size={14} /> : <ClipboardCheck size={14} />}
        {loading ? "처리 중" : nextActionLabel}
      </button>
      <small>{helperText ?? "Closed-loop API 연결 전에는 화면에서 작업 상태를 변경하지 않습니다."}</small>
    </div>
  );
}

function lifecycleTimelineItems(summary: MvpClosedLoopLifecycleSummary | null | undefined): Array<{
  id: string;
  label: string;
  state: "is-done" | "is-active" | "";
}> | null {
  if (!summary) return null;
  const completed = summary.completedSteps.map((step) => ({
    id: step,
    label: CLOSED_LOOP_LIFECYCLE_LABEL[step] ?? step,
    state: "is-done" as const,
  }));
  const active = {
    id: summary.currentStep,
    label: summary.currentStepLabel || CLOSED_LOOP_LIFECYCLE_LABEL[summary.currentStep],
    state: "is-active" as const,
  };
  const next = summary.nextStep
    ? [{
      id: summary.nextStep,
      label: CLOSED_LOOP_LIFECYCLE_LABEL[summary.nextStep] ?? summary.nextStep,
      state: "" as const,
    }]
    : [];
  return [...completed, active, ...next].slice(-7);
}

function WorkStatusTimeline({
  status,
  lifecycleSummary,
}: {
  status: WorkStatus;
  lifecycleSummary?: MvpClosedLoopLifecycleSummary | null;
}) {
  const order: WorkStatus[] = [
    "candidate_recommended",
    "work_requested",
    "assigned",
    "inspection_started",
    "inspection_completed",
    "maintenance_started",
    "maintenance_completed",
    "observation_pending",
    "prediction_blocked",
    "ready_for_reprediction",
  ];
  const activeIndex = order.indexOf(status);
  const lifecycleItems = lifecycleTimelineItems(lifecycleSummary);
  if (lifecycleItems) {
    return (
      <ol className="mvp-work-status-timeline" aria-label="작업 상태 타임라인">
        {lifecycleItems.map((item) => (
          <li key={item.id} className={item.state}>
            <i aria-hidden="true" />
            <span>{item.label}</span>
          </li>
        ))}
      </ol>
    );
  }
  return (
    <ol className="mvp-work-status-timeline" aria-label="작업 상태 타임라인">
      {order.map((item, index) => (
        <li key={item} className={index < activeIndex ? "is-done" : index === activeIndex ? "is-active" : ""}>
          <i aria-hidden="true" />
          <span>{WORK_STATUS_LABEL[item]}</span>
        </li>
      ))}
    </ol>
  );
}

function ClosedLoopActivityTimeline({ timeline }: { timeline: MvpClosedLoopTimelineItem[] }) {
  if (!timeline.length) return null;
  return (
    <ol className="mvp-closed-loop-activity-timeline" aria-label="Closed-loop 작업 이력">
      {timeline.slice(0, 4).map((item) => (
        <li key={item.timelineId}>
          <i aria-hidden="true" />
          <div>
            <strong>{item.label}</strong>
            <small>{[item.actorDisplayName, item.occurredAt ? formatTimestamp(item.occurredAt) : null].filter(Boolean).join(" · ")}</small>
          </div>
        </li>
      ))}
    </ol>
  );
}

function WorkStatusQueueBoard({
  candidates,
  role,
  selectedAssetId,
  workOrders,
  loadError,
  onPreview,
}: {
  candidates: WorkOrderCandidate[];
  role: MvpRoleLens;
  selectedAssetId: string | null;
  workOrders: OpenInspectionWorkOrderReadModel[];
  loadError: string | null;
  onPreview: (assetId: string, eventId: string | null) => void;
}) {
  const items = candidates.map((candidate) => {
    const workOrder = workOrders.find((item) => item.asset_id === candidate.event.assetId) ?? null;
    const status: WorkStatus = workStatusFromInspectionWorkflow(workOrder)
      ?? workStatusForAsset(candidate.asset, candidate.event);
    return { candidate, workOrder, status, column: workQueueColumn(status) };
  });
  return (
    <section className="mvp-work-queue-board" aria-label="작업 상태 큐">
      <header>
        <div>
          <span>{role === "field_operator" ? "현장 작업 큐" : "생산 판단 큐"}</span>
          <strong>작업 상태 큐</strong>
        </div>
        <small>{loadError ?? "실제 전이 상태는 열린 점검 WorkOrder 기준으로 반영됩니다."}</small>
      </header>
      <div className="mvp-work-kanban" role="list">
        {WORK_QUEUE_COLUMNS.map((column) => {
          const columnItems = items.filter((item) => item.column === column.id);
          return (
            <section key={column.id} className="mvp-work-kanban-column" aria-label={column.label}>
              <header>
                <div><strong>{column.label}</strong><span>{column.detail}</span></div>
                <b>{columnItems.length}</b>
              </header>
              <div>
                {columnItems.length ? columnItems.map(({ candidate, workOrder, status }) => {
                  const assetName = candidate.asset ? displayAssetName(candidate.asset) : displayEventAssetName(candidate.event);
                  const lineLabel = candidate.asset?.line || candidate.asset?.cell || candidate.event.line || "라인 미지정";
                  const assignee = workOrder?.assigned_to
                    ?? candidate.event.assignedEngineer
                    ?? candidate.asset?.assignedEngineer
                    ?? "미배정";
                  const secondary = role === "field_operator"
                    ? `${candidate.suspectedPart} · ${displayPartLabel(candidate.event.sparePartAvailable)}`
                    : `${lineLabel} · ${DECISION_LABEL[candidate.event.recommendedDecision]}`;
                  return (
                    <button
                      type="button"
                      key={candidate.event.eventId}
                      className={selectedAssetId === candidate.event.assetId ? "mvp-work-kanban-card is-selected" : "mvp-work-kanban-card"}
                      onClick={() => onPreview(
                        candidate.event.assetId,
                        workOrder?.event_id ?? candidate.event.eventId,
                      )}
                    >
                      <MvpStatusBadge status={candidate.event.status} />
                      <strong>{assetName}</strong>
                      <small>{secondary}</small>
                      <span>{WORK_STATUS_LABEL[status]} · 담당 {assignee}</span>
                    </button>
                  );
                }) : <p>대기 없음</p>}
              </div>
            </section>
          );
        })}
      </div>
    </section>
  );
}

function ReportOutputDialog({
  onSelect,
  onClose,
}: {
  onSelect: (reportTab: MvpReportTab) => void;
  onClose: () => void;
}) {
  return (
    <div className="mvp-assignment-popover" role="dialog" aria-modal="true" aria-label="보고서 출력 유형 선택" onClick={onClose}>
      <div className="mvp-assignment-card mvp-report-output-card" onClick={(event) => event.stopPropagation()}>
        <header>
          <div><span>보고서 출력</span><strong>출력할 보고서 유형을 선택합니다</strong></div>
        </header>
        <div className="mvp-report-output-options" role="list">
          {REPORT_OUTPUT_OPTIONS.map((option) => (
            <button type="button" key={option.id} onClick={() => onSelect(option.id)}>
              <ClipboardList size={14} />
              <span>{option.label}</span>
              <small>{option.detail}</small>
            </button>
          ))}
        </div>
        <footer>
          <button type="button" className="mvp-button ghost" onClick={onClose}>취소</button>
        </footer>
        <small>현재 사이드뷰 맥락에서 브라우저 출력 창을 엽니다.</small>
      </div>
    </div>
  );
}

function WorkflowPrintReport({
  reportTab,
  asset,
  detail,
  factors,
  inspectionTargets,
  planningImpact,
  workStatus,
  assignee,
  workId,
}: {
  reportTab: MvpReportTab;
  asset: MvpAsset;
  detail: MvpEventDetailModel | null;
  factors: MvpAsset["topFactors"];
  inspectionTargets: InspectionTargetView[];
  planningImpact: ReturnType<typeof planningImpactFromOperationContext>;
  workStatus: WorkStatus;
  assignee: string;
  workId: string;
}) {
  const option = REPORT_OUTPUT_OPTIONS.find((item) => item.id === reportTab);
  const reportTitle = option?.label ?? "보고서";
  const riskPercent = asset.failureProbability === null || asset.failureProbability === undefined
    ? "-"
    : formatProbability(asset.failureProbability);
  return (
    <section className="mvp-workflow-print-report" aria-label={`${reportTitle} 출력`}>
      <header>
        <span>{reportTitle}</span>
        <strong>{displayAssetName(asset)}</strong>
        <small>{asset.line || asset.cell || asset.assetId} · 관측 {formatTimestamp(asset.observedAt)} · 고장 확정 아님</small>
      </header>
      <dl>
        <div><dt>위험 상태</dt><dd><MvpStatusBadge status={asset.status} /></dd></div>
        <div><dt>24시간 위험 예측</dt><dd>{riskPercent}</dd></div>
        <div><dt>작업 상태</dt><dd>{WORK_STATUS_LABEL[workStatus]}</dd></div>
        <div><dt>작업 ID</dt><dd>{workId}</dd></div>
        <div><dt>담당자</dt><dd>{assignee}</dd></div>
        <div><dt>부품</dt><dd>{displayPartLabel(asset.sparePartAvailable)}</dd></div>
        <div><dt>계획 영향</dt><dd>{productionLossLabel(planningImpact?.estimatedLossUnits ?? null)}</dd></div>
        <div><dt>판단</dt><dd>{DECISION_LABEL[asset.recommendedDecision]}</dd></div>
      </dl>
      {reportTab === "inspection-request" ? (
        <section>
          <h2>점검 요청 항목</h2>
          {inspectionTargets.length ? inspectionTargets.map((target) => (
            <article key={target.target?.targetId ?? target.factor?.id ?? `inspection-target-${target.rank}`}>
              <b>{target.rank}. {target.target?.componentLabel ?? (target.factor ? fieldFactorItem(target.factor) : "점검 후보")}</b>
              <p>{inspectionMethodLabel(target.target)}</p>
            </article>
          )) : <p>점검 위치 근거는 Backend ViewModel 연결 후 표시됩니다.</p>}
        </section>
      ) : null}
      {reportTab !== "inspection-request" ? (
        <section>
          <h2>판단 근거</h2>
          {factors.length ? factors.slice(0, 5).map((factor) => (
            <article key={factor.id}>
              <b>{fieldFactorItem(factor)}</b>
              <p>{fieldFactorSymptom(factor)} · {factorValueLabel(factor)}</p>
            </article>
          )) : <p>Top factor 근거가 제공되지 않았습니다.</p>}
        </section>
      ) : null}
      <section>
        <h2>데이터 경계</h2>
        <p>{detail ? "AssetDetailViewModel 기준 출력입니다." : "상세 ViewModel 미연결 상태의 요약 출력입니다."} 이 화면은 작업 생성이나 정비 효과를 확정하지 않습니다.</p>
      </section>
    </section>
  );
}

function buildFactoryCellLayout(assets: MvpAsset[], summaries: LineImpactSummary[]): FactoryCellLayout[] {
  const assetsById = new Map(assets.map((asset) => [asset.assetId, asset]));
  const summaryByLine = new Map(summaries.map((summary) => [summary.line, summary]));
  return FACTORY_SITE_IDS.flatMap((site) => FACTORY_CELL_IDS.map((cell) => {
    const line = `${site}-${cell}`;
    const slotSeeds: Array<{ kind: FactorySlotKind; slotIndex: number }> = [
      { kind: "compressor", slotIndex: 1 },
      { kind: "cnc", slotIndex: 1 },
      { kind: "cnc", slotIndex: 2 },
      { kind: "cnc", slotIndex: 3 },
      { kind: "cnc", slotIndex: 4 },
    ];
    const slots: FactoryCellSlot[] = slotSeeds.map(({ kind, slotIndex }) => {
      const assetId = canonicalSlotAssetId(site, cell, kind, slotIndex);
      return {
        id: `${line}-${kind}-${slotIndex}`,
        assetId,
        label: factorySlotLabel(kind, slotIndex),
        kind,
        asset: assetsById.get(assetId) ?? null,
      };
    });
    return {
      id: line,
      site,
      cell: line,
      label: `${displayFactorySite(site)} · ${displayFactoryCell(line)}`,
      slots,
      summary: summaryByLine.get(line) ?? null,
      planUnits: null,
    };
  }));
}

function reviewPriorityLabel(summary: LineImpactSummary, detail: MvpEventDetailModel | null): string {
  const hasSelectedAsset = detail ? summary.assets.some((asset) => asset.assetId === detail.event.assetId) : false;
  return hasSelectedAsset ? displayReviewPriority(detail?.reviewPriority?.level) : "검토 우선순위 미제공";
}

export function MvpWorkflowOverviewPage({
  model,
  role,
  selectedAssetId,
  detail,
  detailLoading,
  detailError,
  sensorWindow,
  canMaterializeAgentSummary,
  canManageWorkflow,
  canExecuteFieldWorkflow,
  currentUserId,
  onSensorWindowChange,
  onPreviewAsset,
  onRefresh,
}: {
  model: MvpBootstrapModel;
  role: MvpRoleLens;
  selectedAssetId: string | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  sensorWindow: MvpSensorWindowId;
  canMaterializeAgentSummary: boolean;
  canManageWorkflow: boolean;
  canExecuteFieldWorkflow: boolean;
  currentUserId: string;
  onSensorWindowChange: (windowId: MvpSensorWindowId) => void;
  onPreviewAsset: (assetId: string, eventId: string | null) => void;
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
  const [openInspectionWorkOrders, setOpenInspectionWorkOrders] = useState<OpenInspectionWorkOrderReadModel[]>([]);
  const [openInspectionWorkOrdersError, setOpenInspectionWorkOrdersError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void getOpenInspectionWorkOrders(
      model.context.projectId,
      model.context.workspaceId,
      controller.signal,
    ).then((response) => {
      setOpenInspectionWorkOrders(response.items);
      setOpenInspectionWorkOrdersError(null);
    }).catch((reason) => {
      if (!controller.signal.aborted) {
        setOpenInspectionWorkOrders([]);
        setOpenInspectionWorkOrdersError(
          reason instanceof Error ? reason.message : "열린 점검 요청을 불러오지 못했습니다.",
        );
      }
    });
    return () => controller.abort();
  }, [model.context.projectId, model.context.refreshedAt, model.context.workspaceId]);
  const queueCandidatePool = [...workOrderCandidates];
  for (const workOrder of openInspectionWorkOrders) {
    if (queueCandidatePool.some((candidate) => candidate.event.eventId === workOrder.event_id)) continue;
    const event = model.events.find((item) => item.eventId === workOrder.event_id)
      ?? model.events.find((item) => item.assetId === workOrder.asset_id);
    if (!event) continue;
    const asset = model.assets.find((item) => item.assetId === workOrder.asset_id) ?? null;
    queueCandidatePool.push({ event, asset, suspectedPart: suspectedPartLabel(event, asset) });
  }
  const queueCandidates = prioritizeActiveWorkflowCandidates(
    queueCandidatePool,
    openInspectionWorkOrders,
  );
  const lineImpactSummaries = buildLineImpactSummaries(model.assets);
  const factoryCells = buildFactoryCellLayout(model.assets, lineImpactSummaries);
  const selectedAsset = model.assets.find((asset) => asset.assetId === selectedAssetId)
    ?? topAssets[0]
    ?? null;
  const selectedEvent = selectedAsset?.eventId
    ? model.events.find((event) => event.eventId === selectedAsset.eventId) ?? null
    : null;
  const selectedFactors = selectedAsset && detail?.event.assetId === selectedAsset.assetId && Array.isArray(detail.topFactors) && detail.topFactors.length
    ? detail.topFactors
    : selectedAsset?.topFactors ?? [];
  const needsPartCheck = anomalyEvents.filter((event) => displayPartLabel(event.sparePartAvailable) !== "확보").length;
  const dataQualityEvent = model.events.find((event) => event.status === "data_quality_hold") ?? null;
  const dataQualityCount = model.events.filter((event) => event.status === "data_quality_hold").length;
  const spareMissingCount = model.events.filter((event) => event.sparePartAvailable === false).length;
  const immediateDecisionCount = model.events.filter((event) => event.recommendedDecision === "review_shutdown").length;
  const riskyLines = model.lineRisk.filter((line) => line.critical + line.warning + line.dataQualityHold > 0).length;
  const selectedCandidate = selectedEvent
    ? workOrderCandidates.find((candidate) => candidate.event.eventId === selectedEvent.eventId) ?? null
    : null;
  const selectedDetail = detail?.event.assetId === selectedAsset?.assetId ? detail : null;
  const plannedUnits = plannedUnitsFromDetail(selectedDetail);
  const planningBasis = planningBasisFromDetail(selectedDetail);
  const maxPlanningImpact = planningImpactFromOperationContext(selectedDetail);
  const selectedClosedLoopStatus = workStatusFromClosedLoop(selectedDetail?.closedLoop);
  const selectedClosedLoopWorkId = closedLoopWorkIdLabel(selectedDetail?.closedLoop);
  const selectedLifecycleSummary = selectedDetail?.closedLoop?.lifecycleSummary ?? null;
  const selectedWorkStatusLabel = selectedLifecycleSummary?.currentStepLabel ?? (selectedClosedLoopStatus ? WORK_STATUS_LABEL[selectedClosedLoopStatus] : "미생성");
  const selectedWorkStatusDetail = selectedClosedLoopStatus
    ? `${selectedClosedLoopWorkId} · 담당 ${closedLoopAssignee(selectedDetail?.closedLoop) ?? selectedEvent?.assignedEngineer ?? "미배정"}`
    : "작업요청 ID 미생성 · 점검 후보";
  const agentSummaryLine = role === "field_operator"
    ? `점검 후보 ${workOrderCandidates.length}건 · 부품 확인 ${needsPartCheck}건 · ${selectedWorkStatusLabel}`
    : `위험 라인 ${riskyLines}개 · 라인 ${lineImpactSummaries.length}개 · 평균 위험도 ${formatProbability(metrics.averageRisk)}`;
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [detailDrawerTab, setDetailDrawerTab] = useState<DrawerTab>("status");
  const [factorySlotPreview, setFactorySlotPreview] = useState<FactorySlotPreview | null>(null);
  const [postMaintenancePredictions, setPostMaintenancePredictions] = useState<Record<string, PostMaintenancePredictionSummary>>({});
  const handlePostMaintenancePrediction = useCallback((assetId: string, prediction: PostMaintenancePredictionSummary) => {
    setPostMaintenancePredictions((current) => {
      const previous = current[assetId];
      if (
        previous?.failureProbability === prediction.failureProbability
        && previous.statusGrade === prediction.statusGrade
        && previous.observedAt === prediction.observedAt
      ) return current;
      return { ...current, [assetId]: prediction };
    });
  }, []);
  const drawerAssetSource = factorySlotPreview?.slot.asset ?? (factorySlotPreview ? null : selectedAsset);
  const drawerPrediction = drawerAssetSource ? postMaintenancePredictions[drawerAssetSource.assetId] : null;
  const drawerAsset = drawerAssetSource && drawerPrediction
    ? {
      ...drawerAssetSource,
      status: drawerPrediction.statusGrade,
      failureProbability: drawerPrediction.failureProbability,
      observedAt: drawerPrediction.observedAt,
    }
    : drawerAssetSource;
  const drawerEvent = drawerAsset?.eventId
    ? model.events.find((event) => event.eventId === drawerAsset.eventId) ?? null
    : null;
  const drawerCandidate = drawerEvent
    ? workOrderCandidates.find((candidate) => candidate.event.eventId === drawerEvent.eventId) ?? null
    : null;
  const drawerLineSummary = drawerAsset
    ? lineImpactSummaries.find((summary) => summary.line === (drawerAsset.line || drawerAsset.cell || "라인 근거 없음")) ?? null
    : null;
  const drawerFactors = drawerAsset && detail?.event.assetId === drawerAsset.assetId && Array.isArray(detail.topFactors) && detail.topFactors.length
    ? detail.topFactors
    : drawerAsset?.topFactors ?? [];
  const drawerRiskPercent = drawerAsset?.failureProbability === null || drawerAsset?.failureProbability === undefined
    ? null
    : Math.round(drawerAsset.failureProbability * 100);
  const drawerDetail = drawerAsset && detail?.event.assetId === drawerAsset.assetId ? detail : null;
  const drawerOpenInspectionWorkOrder = drawerAsset
    ? openInspectionWorkOrders.find((item) => item.asset_id === drawerAsset.assetId) ?? null
    : null;
  const drawerEventId = drawerOpenInspectionWorkOrder?.event_id
    ?? drawerDetail?.snapshotBasis?.eventId
    ?? drawerDetail?.event.eventId
    ?? drawerEvent?.eventId
    ?? drawerAsset?.eventId
    ?? null;
  const drawerDetailEventId = drawerDetail?.snapshotBasis?.eventId
    ?? drawerDetail?.event.eventId
    ?? null;
  const drawerClosedLoop = drawerOpenInspectionWorkOrder
    && drawerDetailEventId !== drawerOpenInspectionWorkOrder.event_id
    ? null
    : drawerDetail?.closedLoop ?? null;
  const drawerClosedLoopStatus = workStatusFromInspectionWorkflow(drawerOpenInspectionWorkOrder)
    ?? workStatusFromClosedLoop(drawerClosedLoop);
  const drawerLifecycleSummary = drawerClosedLoop?.lifecycleSummary ?? null;
  const drawerClosedLoopAction = primaryClosedLoopAction(drawerClosedLoop, drawerClosedLoopStatus);
  const drawerPlanningImpact = planningImpactFromOperationContext(drawerDetail);
  const drawerWorkStatus = drawerAsset
    ? drawerClosedLoopStatus ?? workStatusForAsset(drawerAsset, drawerEvent)
    : "candidate_recommended";
  const drawerAssignee = drawerAsset
    ? drawerOpenInspectionWorkOrder?.assigned_to
      ?? closedLoopAssignee(drawerClosedLoop)
      ?? drawerAsset.assignedEngineer
      ?? drawerEvent?.assignedEngineer
      ?? "미배정"
    : "미배정";
  const drawerWorkId = drawerOpenInspectionWorkOrder?.work_order_id
    ?? closedLoopWorkIdLabel(drawerClosedLoop);
  const drawerActionLabel = drawerClosedLoopAction?.label ?? null;
  const drawerWorkActionDisabled = true;
  const drawerActionHelper = drawerClosedLoop
    ? drawerClosedLoopAction?.disabledReason ?? (drawerClosedLoop.primaryAction ? `담당: ${drawerClosedLoop.primaryAction.ownerLabel} · Closed-loop read model 기준으로 표시합니다.` : "Closed-loop read model 기준으로 표시합니다. 실제 실행은 API mutation 연결 후 처리합니다.")
    : "Closed-loop API 미연결 상태입니다. 현재 화면에서는 상태를 변경하지 않습니다.";
  const fieldSummaryPart = selectedCandidate?.suspectedPart
    ?? (selectedFactors[0] ? fieldFactorItem(selectedFactors[0]) : "의심 부품 확인 필요");
  const fieldSummaryPartStatus = selectedEvent ? displayPartLabel(selectedEvent.sparePartAvailable) : "확인 필요";
  const fieldSummaryQuality = selectedAsset?.status === "data_quality_hold" ? "데이터 품질 확인이 먼저 필요합니다" : "관측 데이터로 바로 확인할 수 있습니다";
  const fieldSummary = selectedAsset
    ? `${fieldSummaryPart}을 위치에서 확인하고 알람·사진·관측값을 기록해 전달하세요. 부품 상태는 ${fieldSummaryPartStatus}, 작업요청 ID는 아직 없고, ${fieldSummaryQuality}.`
    : "선택된 설비가 없어 점검 후보를 만들 수 없습니다.";

  useEffect(() => {
    if (!detailDrawerOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDetailDrawerOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [detailDrawerOpen]);

  const previewInDrawer = (assetId: string, eventId: string | null) => {
    setFactorySlotPreview(null);
    onPreviewAsset(assetId, eventId);
    setDetailDrawerOpen(true);
    setDetailDrawerTab("status");
  };

  const previewFactorySlot = (slot: FactoryCellSlot, cell: FactoryCellLayout) => {
    setFactorySlotPreview({ slot, cell });
    setDetailDrawerOpen(true);
    setDetailDrawerTab("status");
  };

  const previewFactoryAssetSlot = (asset: MvpAsset, slot: FactoryCellSlot, cell: FactoryCellLayout) => {
    setFactorySlotPreview({ slot, cell });
    onPreviewAsset(asset.assetId, asset.eventId);
    setDetailDrawerOpen(true);
    setDetailDrawerTab("status");
  };

  return (
    <div className="mvp-page mvp-overview-page" data-testid="mvp-overview">
      <section className="mvp-agent-summary" aria-label="에이전트 요약">
        <div>
          <span>작업 요약</span>
          <strong>
            {selectedAsset
              ? role === "field_operator"
                ? `${displayAssetName(selectedAsset)} 기준으로 확인·기록·전달 항목을 봅니다`
                : `생산 리스크 요약 · ${displayFactoryAssetName(selectedAsset.assetId) ?? displayAssetName(selectedAsset)} 우선 관리`
              : "선택된 설비가 없습니다"}
          </strong>
          <p>
            {role === "field_operator"
              ? fieldSummary
              : `${agentSummaryLine} · 계획 영향은 합성 용량 모델 기반 추정이며 생산계획 화면 데이터 연결 전 표시입니다.`}
          </p>
        </div>
        {role === "process_manager" ? (
          <div className="mvp-agent-sample-strip" aria-label="생산 관리 관련 데이터">
            <span>오늘 계획 {plannedUnits.value ? `${plannedUnits.value.toLocaleString()}개/일` : "미연결"}</span>
            <span>{plannedUnits.fallback ? "생산계획 데이터 미연결" : "생산계획 데이터 기준"}</span>
            <span>실제 생산관리 실적 아님</span>
          </div>
        ) : null}
        <button type="button" className="mvp-button ghost" onClick={onRefresh}><RefreshCw size={15} />새로고침</button>
      </section>

      {role === "process_manager" ? (
        <section className="mvp-overview-topline" aria-label="생산 관리자 상단 지표">
          <article className="mvp-plan-impact-card">
            <Gauge className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>오늘 계획</span>
            <strong>{plannedUnits.value ? plannedUnits.value.toLocaleString() : "-"}개/일</strong>
            <small>{plannedUnits.fallback ? "생산계획 데이터 연결 전 임시값" : "생산계획 데이터 기준"}</small>
          </article>
          <article className="mvp-plan-impact-card is-critical">
            <AlertTriangle className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>최대 계획 영향</span>
            <strong>{productionLossLabel(maxPlanningImpact?.estimatedLossUnits ?? null)}</strong>
            <small>{maxPlanningImpact ? `${displayEventLabel(maxPlanningImpact.eventId)} / ${displayFactoryAssetName(maxPlanningImpact.assetId) ?? displayAssetName({ assetId: maxPlanningImpact.assetId })}` : "계획 영향 미산정"}</small>
          </article>
          <article className="mvp-plan-impact-card">
            <ClipboardCheck className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>즉시 판단 필요</span>
            <strong>{immediateDecisionCount.toLocaleString()}건</strong>
            <small>계획 위험 이벤트 기준</small>
          </article>
          <article className="mvp-plan-impact-card is-hold">
            <DatabaseZap className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>데이터 품질 보류</span>
            <strong>{dataQualityCount.toLocaleString()}건</strong>
            <small>생산 영향 미산정 포함</small>
          </article>
          <article className="mvp-plan-impact-card is-hold">
            <Wrench className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>부품 미확보</span>
            <strong>{spareMissingCount.toLocaleString()}건</strong>
            <small>조치 제약 확인 필요</small>
          </article>
        </section>
      ) : (
        <section className="mvp-overview-topline" aria-label="현장 관리자 상단 지표">
          <article className="mvp-plan-impact-card">
            <ClipboardList className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>점검 후보</span>
            <strong>{workOrderCandidates.length.toLocaleString()}건</strong>
            <small>전체 점검 후보</small>
          </article>
          <article className="mvp-plan-impact-card is-critical">
            <AlertTriangle className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>최우선 설비</span>
            <strong>{displayAssetName(selectedAsset)}</strong>
            <small>최우선 점검 대상</small>
          </article>
          <article className="mvp-plan-impact-card">
            <Wrench className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>부품 확인 필요</span>
            <strong>{needsPartCheck.toLocaleString()}건</strong>
            <small>미확보 또는 확인 필요 후보</small>
          </article>
          <article className="mvp-plan-impact-card is-hold">
            <DatabaseZap className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>데이터 품질 확인</span>
            <strong>{dataQualityCount.toLocaleString()}건</strong>
            <small>{dataQualityEvent ? `${displayEventAssetName(dataQualityEvent)} / ${displayEventLabel(dataQualityEvent)}` : "품질 보류 없음"}</small>
          </article>
          <article className="mvp-plan-impact-card">
            <Clock3 className="mvp-plan-impact-icon" size={15} aria-hidden="true" />
            <span>작업 상태</span>
            <strong>{selectedWorkStatusLabel}</strong>
            <small>{selectedWorkStatusDetail}</small>
          </article>
        </section>
      )}

      {role === "field_operator" ? (
        <div className="mvp-role-overview mvp-role-overview-wide">
          <MvpPanel title="우선순위" eyebrow="점검 요청 기준" className="mvp-today-panel">
            <div className="mvp-order-board">
              <div className="mvp-work-card-list">
                {workOrderCandidates.length ? workOrderCandidates.map((candidate, index) => (
                  <button type="button" key={candidate.event.eventId} className={selectedAsset?.assetId === candidate.event.assetId ? "mvp-work-card is-selected" : "mvp-work-card"} onClick={() => previewInDrawer(candidate.event.assetId, candidate.event.eventId)}>
                    <div><MvpStatusBadge status={candidate.event.status} /><strong>{candidate.suspectedPart}</strong><small>제안 #{String(index + 1).padStart(2, "0")} · {displayEventAssetName(candidate.event)}</small></div>
                    <dl>
                      <div><dt>설비</dt><dd>{displayEventAssetName(candidate.event)}</dd></div>
                      <div><dt>부품</dt><dd>{displayPartLabel(candidate.event.sparePartAvailable)}</dd></div>
                      <div><dt>담당</dt><dd>{candidate.event.assignedEngineer ?? "미배정"}</dd></div>
                      <div><dt>권고</dt><dd>{DECISION_LABEL[candidate.event.recommendedDecision]}</dd></div>
                    </dl>
                  </button>
                )) : <MvpState kind="empty" title="점검 후보 없음" detail="점검 요청 리포트 기준으로 즉시 제안할 후보가 없습니다." />}
              </div>
            </div>
          </MvpPanel>
        </div>
      ) : (
        <div className="mvp-role-overview">
          <MvpPanel title="라인별 설비 영향 맵" eyebrow="데모 설비 배치" className="mvp-process-panel mvp-factory-map-panel">
            <div className="mvp-plan-impact-note">{FACTORY_LAYOUT_NOTICE} · {planningBasis.fallback ? "생산계획 데이터 미연결" : "생산계획 데이터 기준"} · {planningBasis.value}</div>
            {factoryCells.length ? (
              <div className="mvp-factory-map">
                <div className="mvp-factory-map-legend" aria-label="설비 상태 범례">
                  <i className="critical">위험</i><i className="warning">경고</i><i className="attention">주의</i><i className="normal">정상</i><i className="hold">데이터 확인</i><i className="slot">상태 미연결</i>
                </div>
                <div className="mvp-factory-line-map">
                  {FACTORY_SITE_IDS.map((site) => {
                    const siteCells = factoryCells.filter((cell) => cell.site === site);
                    const siteAssets = siteCells.flatMap((cell) => cell.slots.map((slot) => slot.asset).filter((asset): asset is MvpAsset => Boolean(asset)));
                    const siteTone = siteCells.some((cell) => cell.summary?.critical)
                      ? "critical"
                      : siteCells.some((cell) => cell.summary?.warning)
                        ? "warning"
                        : siteCells.some((cell) => cell.summary?.hold)
                          ? "hold"
                          : siteCells.some((cell) => cell.summary?.attention)
                            ? "attention"
                            : "normal";
                    return (
                      <article key={site} className={`mvp-factory-line-row tone-${siteTone}`}>
                        <header>
                          <strong>{displayFactorySite(site)}</strong>
                          <small>{siteCells.length}개 라인 · 데모 배치 슬롯 · 연결 설비 {siteAssets.length}대</small>
                        </header>
                        <div className="mvp-factory-cell-grid" aria-label={`${site} 셀별 설비 상태`}>
                          {siteCells.map((cell) => (
                            <section key={cell.id} className={`mvp-factory-cell-card tone-${cell.summary ? riskTone(cell.summary) : "empty"} ${cell.slots.some((slot) => slot.asset?.assetId === selectedAsset?.assetId) ? "is-selected" : ""}`} aria-label={cell.label}>
                              <header>
                                <strong>{displayFactoryCell(cell.cell)}</strong>
                                <small>{cell.summary ? `${cell.summary.assets.length}대 연결` : "상태 미연결"}</small>
                              </header>
                              <div className="mvp-factory-cell-slots">
                                {cell.slots.map((slot) => {
                                  const asset = slot.asset;
                                  const currentPrediction = asset ? postMaintenancePredictions[asset.assetId] : null;
                                  const selected = asset
                                    ? selectedAsset?.assetId === asset.assetId
                                    : factorySlotPreview?.slot.id === slot.id;
                                  const tone = asset ? mapTone(currentPrediction?.statusGrade ?? asset.status) : "slot";
                                  const title = asset
                                    ? `${displayFactorySlotName(slot, cell)} · ${formatProbability(currentPrediction?.failureProbability ?? asset.failureProbability)} · ${displayPartLabel(asset.sparePartAvailable)}`
                                    : `${cell.label} · ${slot.label} · 상태 미연결`;
                                  return (
                                    <button
                                      key={slot.id}
                                      type="button"
                                      className={`mvp-factory-asset-node ${tone} ${slot.kind} ${selected ? "is-selected" : ""}`}
                                      aria-pressed={selected}
                                      onClick={() => asset ? previewFactoryAssetSlot(asset, slot, cell) : previewFactorySlot(slot, cell)}
                                      title={title}
                                    >
                                      <span>{asset ? displayAssetShortName(asset) : slot.kind === "compressor" ? "공기압축기" : slot.label.replace("CNC ", "")}</span>
                                    </button>
                                  );
                                })}
                              </div>
                            </section>
                          ))}
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>
            ) : <MvpState kind="empty" title="셀 배치 데이터가 없습니다" detail="연결된 설비 판단에 공장 셀 기준 배치 정보가 없습니다." />}
          </MvpPanel>

        </div>
      )}

      <WorkStatusQueueBoard
        candidates={queueCandidates}
        role={role}
        selectedAssetId={selectedAsset?.assetId ?? null}
        workOrders={openInspectionWorkOrders}
        loadError={openInspectionWorkOrdersError}
        onPreview={previewInDrawer}
      />

      {(drawerAsset || factorySlotPreview) && detailDrawerOpen ? (
        <div className="mvp-detail-drawer-layer" role="presentation">
          <button
            type="button"
            className="mvp-detail-drawer-scrim"
            aria-label="상세 패널 닫기"
            onClick={() => setDetailDrawerOpen(false)}
          />
          <aside className="mvp-detail-drawer" role="dialog" aria-modal="true" aria-label="선택 설비 상세">
            <AssetPreviewPanel asset={drawerAsset} factorySlotPreview={factorySlotPreview} candidate={drawerCandidate} lineSummary={drawerLineSummary} factors={drawerFactors} riskPercent={drawerRiskPercent} planningImpact={drawerPlanningImpact} detail={drawerDetail} detailLoading={factorySlotPreview && !drawerAsset ? false : detailLoading} detailError={factorySlotPreview && !drawerAsset ? null : detailError} sensorWindow={sensorWindow} role={role} currentUserId={currentUserId} activeTab={detailDrawerTab} workStatus={drawerWorkStatus} workStatusSource={drawerLifecycleSummary ? "ViewModel" : drawerClosedLoop ? "API" : "화면"} workId={drawerWorkId} workActionLabel={drawerActionLabel} workActionHelper={drawerActionHelper} workActionDisabled={drawerWorkActionDisabled} lifecycleSummary={drawerLifecycleSummary} activityTimeline={drawerClosedLoop?.timeline ?? []} assignee={drawerAssignee} canMaterializeAgentSummary={canMaterializeAgentSummary} canManageWorkflow={canManageWorkflow} canExecuteFieldWorkflow={canExecuteFieldWorkflow} projectId={model.context.projectId} workspaceId={model.context.workspaceId} datasetVersionId={model.context.datasetVersionId} eventId={drawerEventId} onChanged={onRefresh} onPostMaintenancePrediction={handlePostMaintenancePrediction} onTabChange={setDetailDrawerTab} onSensorWindowChange={onSensorWindowChange} onPreviewAsset={onPreviewAsset} />
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function MapReportFeatureSeries({
  title,
  unit,
  points,
  windowId,
  window,
  emptyTitle,
  emptyDetail,
  currentValue,
  currentObservedAt,
  primary,
}: {
  title: string;
  unit: string | null;
  points: SeriesDatum[];
  windowId: MvpSensorWindowId;
  window?: MvpFeatureHistoryWindow | null;
  emptyTitle: string;
  emptyDetail: string;
  currentValue?: number | string | boolean | null;
  currentObservedAt?: string | null;
  primary?: boolean;
}) {
  const color = title.includes("진동") || title.includes("토크") ? "#a7630c" : "#285fcb";
  const visiblePoints = filterSeriesPoints(points, currentObservedAt, windowId);
  const numericPoints = visiblePoints.filter((point): point is SeriesDatum & { value: number } => typeof point.value === "number" && Number.isFinite(point.value));
  const currentNumericValue = typeof currentValue === "number" && Number.isFinite(currentValue) ? currentValue : null;
  if (!visiblePoints.length || !numericPoints.length) {
    return (
      <section className="asset-series-block">
        <header className="asset-series-heading">
          <div><LineChart size={17} /><strong>{title}</strong></div>
          <span>관측 이력 없음</span>
        </header>
        <div className="asset-chart-empty"><strong>{emptyTitle}</strong><span>{emptyDetail}</span></div>
      </section>
    );
  }
  const values = numericPoints.map((point) => point.value);
  const scale = distributionScale(values);
  const valueAnchors = currentNumericValue === null ? values : [...values, currentNumericValue];
  const rawMinimum = Math.min(scale.minimum, ...valueAnchors);
  const rawMaximum = Math.max(scale.maximum, ...valueAnchors);
  const rawSpan = rawMaximum - rawMinimum || Number.EPSILON;
  const min = rawMinimum - rawSpan * 0.08;
  const max = rawMaximum + rawSpan * 0.08;
  const range = max - min || Number.EPSILON;
  const chartWidth = 720;
  const chartHeight = 282;
  const frame = { left: 64, right: 690, top: 22, bottom: 226 };
  const width = frame.right - frame.left;
  const totalSlots = visiblePoints.length + (currentObservedAt ? 1 : 0);
  const height = frame.bottom - frame.top;
  const yAt = (value: number) => frame.bottom - ((value - min) / range) * height;
  const xAt = (index: number) => totalSlots <= 1 ? (frame.left + frame.right) / 2 : frame.left + (width * index) / (totalSlots - 1);
  const coords = visiblePoints.map((point, index) => {
    const x = xAt(index);
    if (typeof point.value !== "number" || !Number.isFinite(point.value)) return { ...point, x, y: null };
    const y = yAt(point.value);
    return { ...point, x, y };
  });
  const segments: Array<Array<typeof coords[number] & { y: number; value: number }>> = [];
  let currentSegment: Array<typeof coords[number] & { y: number; value: number }> = [];
  coords.forEach((point) => {
    if (typeof point.value !== "number" || typeof point.y !== "number") {
      if (currentSegment.length) segments.push(currentSegment);
      currentSegment = [];
      return;
    }
    currentSegment.push(point as typeof point & { y: number; value: number });
  });
  if (currentSegment.length) segments.push(currentSegment);
  const ticks = [max, (min + max) / 2, min];
  const bandLower = clamp(scale.bandLower, min, max);
  const bandUpper = clamp(scale.bandUpper, min, max);
  const bandY = yAt(bandUpper);
  const bandHeight = Math.max(2, yAt(bandLower) - yAt(bandUpper));
  const crossing = coords.find((point) => typeof point.value === "number" && typeof point.y === "number" && (point.value < scale.bandLower || point.value > scale.bandUpper));
  const crossingText = crossing && typeof crossing.value === "number"
    ? `최근 분포 대비 이탈 ${formatSeriesTime(crossing.observedAt)} · ${crossing.value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${unit ? ` ${unit}` : ""}`
    : null;
  const crossingLabelWidth = crossingText ? Math.min(260, Math.max(150, crossingText.length * 6.6 + 18)) : 0;
  const crossingLabelX = crossing && crossingText ? clamp(crossing.x - crossingLabelWidth / 2, frame.left + 6, frame.right - crossingLabelWidth - 6) : null;
  const crossingLabelY = crossing && typeof crossing.y === "number" ? frame.bottom - 10 : null;
  const latestHistory = [...coords].reverse().find((point) => typeof point.value === "number" && typeof point.y === "number");
  const currentTimeLabel = currentObservedAt ? formatSeriesTime(currentObservedAt) : "현재 시간 없음";
  const currentPoint = currentNumericValue === null || !currentObservedAt ? null : { x: xAt(visiblePoints.length), y: yAt(currentNumericValue), value: currentNumericValue };
  return (
    <section className={primary ? "asset-series-block is-primary" : "asset-series-block"}>
      <header className="asset-series-heading">
        <div><RotateCcw size={17} /><strong>{title}</strong></div>
        <span className="asset-baseline-key"><i style={{ background: color }} />{seriesRangeLabel(visiblePoints, windowId, window)}</span>
      </header>
      <svg className="asset-series-chart" viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`${title} 관측 흐름`}>
        <rect className="asset-chart-frame" x={frame.left} y={frame.top} width={width} height={height} />
        {ticks.map((tick) => {
          const y = yAt(tick);
          return <g key={tick}><line className="asset-chart-grid" x1={frame.left} x2={frame.right} y1={y} y2={y} /><text className="asset-chart-axis" x="58" y={y + 4} textAnchor="end">{tick.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}</text></g>;
        })}
        <rect className="asset-baseline-band" x={frame.left} y={bandY} width={width} height={bandHeight} style={{ fill: color }} />
        <line className="asset-baseline-mean" x1={frame.left} x2={frame.right} y1={yAt((scale.bandLower + scale.bandUpper) / 2)} y2={yAt((scale.bandLower + scale.bandUpper) / 2)} />
        {segments.map((segment, index) => <polyline key={`${title}-segment-${index}`} className="asset-series-line" points={segment.map((point) => `${point.x},${point.y}`).join(" ")} style={{ stroke: color }} />)}
        {crossing && crossingText && typeof crossing.y === "number" && crossingLabelX !== null && crossingLabelY !== null ? (
          <g>
            <line className="asset-crossing-line" x1={crossing.x} x2={crossing.x} y1={crossing.y} y2={frame.bottom} style={{ stroke: color }} />
            <circle className="asset-crossing-marker" cx={crossing.x} cy={crossing.y} r="5" style={{ fill: color }} />
            <rect className="asset-chart-label-bg" x={crossingLabelX} y={crossingLabelY - 16} width={crossingLabelWidth} height="23" rx="5" />
            <text className="asset-crossing-label" x={crossingLabelX + 9} y={crossingLabelY}>{crossingText}</text>
          </g>
        ) : null}
        {currentPoint ? (
          <g>
            {latestHistory && typeof latestHistory.y === "number" ? <line className="asset-current-extension-line" x1={latestHistory.x} x2={currentPoint.x} y1={latestHistory.y} y2={currentPoint.y} style={{ stroke: color }} /> : null}
            <path className="asset-current-value-marker" d={`M ${currentPoint.x} ${currentPoint.y - 6} L ${currentPoint.x + 6} ${currentPoint.y} L ${currentPoint.x} ${currentPoint.y + 6} L ${currentPoint.x - 6} ${currentPoint.y} Z`} style={{ fill: color }} />
          </g>
        ) : null}
        {coords.map((point, index) => point.qualityStatus === "bad" || point.qualityStatus === "unknown"
          ? typeof point.y === "number"
            ? <circle key={`${point.observedAt}-${point.value}-${index}`} className="asset-quality-marker" cx={point.x} cy={point.y} r="4.4" style={{ fill: color }} />
            : <circle key={`${point.observedAt}-gap-${index}`} className="asset-gap-marker" cx={point.x} cy={frame.bottom} r="4.2" />
          : null)}
        <text className="asset-chart-axis" x={frame.left} y="252" textAnchor="start">{formatSeriesTime(visiblePoints[0].observedAt)}</text>
        {currentPoint ? <text className="asset-chart-axis asset-current-axis" x={currentPoint.x} y="252" textAnchor="end">현재 {currentTimeLabel}</text> : null}
        <text className="asset-chart-axis-title" x="376" y="270" textAnchor="middle">시간</text>
      </svg>
    </section>
  );
}

function FeatureSeriesCollection({
  title,
  sensors,
  windowId,
  onWindowChange,
  emptyTitle,
  emptyDetail,
}: {
  title: string;
  sensors: ReturnType<typeof sensorSeries>;
  windowId: MvpSensorWindowId;
  onWindowChange: (windowId: MvpSensorWindowId) => void;
  emptyTitle: string;
  emptyDetail: string;
}) {
  const visibleSensors = sensors;
  return (
    <section className="mvp-feature-series-collection" aria-label={title}>
      <header>
        <LineChart size={14} />
        <strong>{title}</strong>
        <div className="asset-window-control" role="group" aria-label="관측 기간 선택">
          {SENSOR_WINDOW_OPTIONS.map((option) => (
            <button
              type="button"
              key={option.id}
              className={option.id === windowId ? "is-active" : ""}
              onClick={() => onWindowChange(option.id)}
              aria-pressed={option.id === windowId}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>
      {sensors.length ? (
        <>
          {visibleSensors.map((sensor) => (
            <MapReportFeatureSeries
              key={sensor.id}
              title={sensor.label}
              unit={sensor.unit}
              points={sensor.points}
              windowId={windowId}
              window={sensor.window}
              currentValue={sensor.currentValue}
              currentObservedAt={sensor.currentObservedAt}
              primary={PRIMARY_FIELD_SENSOR_KEYS.has(sensor.id)}
              emptyTitle="관측 이력 없음"
              emptyDetail={`${sensor.label} 관측 이력이 비어 있어 임의 그래프를 표시하지 않습니다.`}
            />
          ))}
        </>
      ) : <MvpState kind="empty" title={emptyTitle} detail={emptyDetail} />}
    </section>
  );
}

function DerivedMetricSlots({ sensors, windowId }: { sensors: ReturnType<typeof sensorSeries>; windowId: MvpSensorWindowId }) {
  const derivedSensors = sensors.filter((sensor) => DERIVED_FEATURE_KEYS.has(sensor.id));
  return (
    <details className="mvp-derived-metric-dropdown" aria-label="파생 지표 관측 흐름">
      <summary><span><LineChart size={14} />파생 지표 관측 흐름</span><b>{derivedSensors.length ? `${derivedSensors.length}개` : "미연결"}</b></summary>
      {derivedSensors.length ? (
        <div className="mvp-derived-series-list">
          {derivedSensors.map((sensor) => (
            <MapReportFeatureSeries
              key={sensor.id}
              title={sensor.label}
              unit={sensor.unit}
              points={sensor.points}
              windowId={windowId}
              window={sensor.window}
              currentValue={sensor.currentValue}
              currentObservedAt={sensor.currentObservedAt}
              emptyTitle="관측 이력 없음"
              emptyDetail={`${sensor.label} 관측 이력이 비어 있어 임의 그래프를 표시하지 않습니다.`}
            />
          ))}
        </div>
      ) : (
        <MvpState kind="empty" title="파생 지표 미연결" detail="화면 데이터에 파생 지표 관측 이력이 내려오면 같은 그래프로 표시됩니다." />
      )}
    </details>
  );
}

function AssetPreviewPanel({
  asset,
  factorySlotPreview,
  candidate,
  lineSummary,
  factors,
  riskPercent,
  planningImpact,
  detail,
  detailLoading,
  detailError,
  sensorWindow,
  role,
  currentUserId,
  activeTab,
  workStatus,
  workStatusSource,
  workId,
  workActionLabel,
  workActionHelper,
  workActionDisabled,
  lifecycleSummary,
  activityTimeline,
  assignee,
  canMaterializeAgentSummary,
  canManageWorkflow,
  canExecuteFieldWorkflow,
  projectId,
  workspaceId,
  datasetVersionId,
  eventId,
  onChanged,
  onPostMaintenancePrediction,
  onTabChange,
  onSensorWindowChange,
  onPreviewAsset,
}: {
  asset: MvpAsset | null;
  factorySlotPreview: FactorySlotPreview | null;
  candidate: WorkOrderCandidate | null;
  lineSummary: LineImpactSummary | null;
  factors: MvpAsset["topFactors"];
  riskPercent: number | null;
  planningImpact: PlanningImpactRow | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  sensorWindow: MvpSensorWindowId;
  role: MvpRoleLens;
  currentUserId: string;
  activeTab: DrawerTab;
  workStatus: WorkStatus;
  workStatusSource: string;
  workId: string;
  workActionLabel: string | null;
  workActionHelper: string;
  workActionDisabled: boolean;
  lifecycleSummary: MvpClosedLoopLifecycleSummary | null;
  activityTimeline: MvpClosedLoopTimelineItem[];
  assignee: string;
  canMaterializeAgentSummary: boolean;
  canManageWorkflow: boolean;
  canExecuteFieldWorkflow: boolean;
  projectId: string;
  workspaceId: string;
  datasetVersionId: string;
  eventId: string | null;
  onChanged: () => void;
  onPostMaintenancePrediction: (assetId: string, prediction: PostMaintenancePredictionSummary) => void;
  onTabChange: (tab: DrawerTab) => void;
  onSensorWindowChange: (windowId: MvpSensorWindowId) => void;
  onPreviewAsset: (assetId: string, eventId: string | null) => void;
}) {
  const [reportOutputOpen, setReportOutputOpen] = useState(false);
  const [printReportTab, setPrintReportTab] = useState<MvpReportTab | null>(null);
  const [agentSummary, setAgentSummary] = useState<MvpAgentReviewSummary | null>(null);
  const [agentSummaryTrace, setAgentSummaryTrace] = useState<MvpAgentReviewSummaryResponse["trace"] | null>(null);
  const [agentSummaryLoading, setAgentSummaryLoading] = useState(false);
  const [agentSummaryMaterializing, setAgentSummaryMaterializing] = useState(false);
  const [agentSummaryError, setAgentSummaryError] = useState("");
  const [agentSummaryRequestKey, setAgentSummaryRequestKey] = useState("");
  const [costReviewEventId, setCostReviewEventId] = useState<string | null>(null);
  const [workflowStatus, setWorkflowStatus] = useState<MaintenanceWorkflowDisplayStatus | null>(null);
  const [workflowRevision, setWorkflowRevision] = useState(0);
  const assetId = asset?.assetId ?? null;
  const reportPostMaintenancePrediction = useCallback((prediction: PostMaintenancePredictionSummary) => {
    if (assetId) onPostMaintenancePrediction(assetId, prediction);
  }, [assetId, onPostMaintenancePrediction]);
  const refreshWorkflow = () => {
    setWorkflowRevision((value) => value + 1);
    onChanged();
  };
  const costReviewEligible = Boolean(eventId && costReviewEventId === eventId);
  const effectiveWorkStatus: WorkStatus = workflowStatus
    ?? (costReviewEligible
      && ["candidate_recommended", "work_requested", "assigned", "inspection_started"].includes(workStatus)
      ? "inspection_completed"
      : workStatus);
  const effectiveWorkActionLabel = workflowStatus || costReviewEligible ? null : workActionLabel;
  const effectiveWorkActionHelper = costReviewEligible
    ? "비용 분석은 참고 정보이며 정비 추천·승인·실행을 자동 생성하지 않습니다."
    : workActionHelper;
  const effectiveWorkActionDisabled = costReviewEligible || workActionDisabled;
  const featureSnapshots = sensorSeries(detail, asset);
  const directFeatureSnapshots = featureSnapshots.filter((sensor) => !DERIVED_FEATURE_KEYS.has(sensor.id));
  const inspectionTargets: InspectionTargetView[] = detail?.inspectionTargets.length
    ? detail.inspectionTargets.slice(0, 3).map((target, index) => ({
      target,
      factor: factors[index] ?? null,
      rank: index + 1,
    }))
    : factors.slice(0, 3).map((factor, index) => ({
      target: null,
      factor,
      rank: index + 1,
    }));
  const factoryAssetName = factorySlotPreview ? displayFactorySlotName(factorySlotPreview.slot, factorySlotPreview.cell) : null;
  const assetDisplayName = asset ? factoryAssetName ?? displayAssetName(asset) : "선택된 설비 없음";
  const outputReport = (reportTab: MvpReportTab) => {
    if (!asset) return;
    setPrintReportTab(reportTab);
    setReportOutputOpen(false);
    window.setTimeout(() => window.print(), 100);
  };
  const agentSummaryKey = asset ? `${asset.assetId}:${candidate?.event.datasetVersionId ?? ""}:${sensorWindow}` : "";
  const loadAgentSummary = async (materialize = false) => {
    if (!asset) return;
    if (materialize) setAgentSummaryMaterializing(true);
    else setAgentSummaryLoading(true);
    setAgentSummaryError("");
    setAgentSummary(null);
    setAgentSummaryTrace(null);
    setAgentSummaryRequestKey(agentSummaryKey);
    if (materialize && !canMaterializeAgentSummary) {
      setAgentSummaryMaterializing(false);
      setAgentSummaryError("AI 요약 재생성 권한이 없습니다. 저장된 요약은 계속 조회할 수 있습니다.");
      return;
    }
    try {
      const request = {
        assetId: asset.assetId,
        datasetVersionId: candidate?.event.datasetVersionId ?? null,
        historyWindow: sensorWindow,
      };
      const summaryResponse = materialize
        ? await createMvpAgentReviewSummary({ ...request, trigger: "ui_manual_regeneration" })
        : await getMvpAgentReviewSummary(request);
      setAgentSummary(summaryResponse.summary);
      setAgentSummaryTrace(summaryResponse.trace);
    } catch (reason: unknown) {
      const fallbackMessage = materialize
        ? "AI 검토 요약을 생성하지 못했습니다."
        : "AI 검토 요약을 불러오지 못했습니다.";
      setAgentSummaryError(reason instanceof Error ? reason.message : fallbackMessage);
    } finally {
      if (materialize) setAgentSummaryMaterializing(false);
      if (!materialize) setAgentSummaryLoading(false);
    }
  };
  useEffect(() => {
    if (role !== "field_operator" || activeTab !== "status" || !asset || !agentSummaryKey) return;
    if (agentSummaryLoading || agentSummaryRequestKey === agentSummaryKey) return;
    void loadAgentSummary();
  }, [activeTab, agentSummaryKey, agentSummaryLoading, agentSummaryRequestKey, asset, role]);
  useEffect(() => {
    if (!printReportTab) return;
    document.body.classList.add("mvp-workflow-print-mode");
    const clearPrintMode = () => setPrintReportTab(null);
    window.addEventListener("afterprint", clearPrintMode);
    return () => {
      document.body.classList.remove("mvp-workflow-print-mode");
      window.removeEventListener("afterprint", clearPrintMode);
    };
  }, [printReportTab]);
  const agentHistoryItems = agentSummary?.history_summary ?? [];
  const agentFocusItems = agentSummary?.inspection_focus ?? [];
  const agentRoleSummaries = agentSummary?.role_summaries ?? [];
  const currentRoleAgentSummaries = agentRoleSummaries.filter((item) => item.role === role);
  const currentRoleQuote = currentRoleAgentSummaries[0]?.quote ?? "";
  const latestAgentWorkOrder = latestClosedLoopWorkOrder(detail?.closedLoop);
  const similarAgentHistory = agentHistoryItems.find((item) => item.includes("유사 이벤트"));
  const agentPartCandidate = extractPartCandidateFromQuote(currentRoleQuote);
  const agentEvidenceItems = [
    detail?.operationContext?.eventImpact?.estimatedLostUnits !== null && detail?.operationContext?.eventImpact?.estimatedLostUnits !== undefined
      ? { label: "운영 영향", value: `계획 손실 약 ${detail.operationContext.eventImpact.estimatedLostUnits.toLocaleString()}건` }
      : detail?.operationContext
        ? { label: "운영 영향", value: displayProductionImpact(detail.operationContext.productionImpact) }
        : null,
    latestAgentWorkOrder
      ? { label: "작업 흐름", value: `${latestAgentWorkOrder.workOrderId} · ${closedLoopWorkOrderStatusLabel(latestAgentWorkOrder.status)}` }
      : null,
    agentPartCandidate ? { label: "부품 후보", value: agentPartCandidate } : null,
    similarAgentHistory ? { label: "유사 이력", value: formatAgentHistoryItem(similarAgentHistory.replace(/^최근 30일 유사 이벤트:\s*/, "")) } : null,
    agentFocusItems.length ? { label: "점검 위치", value: agentFocusItems.map((item) => item.component_label).join(", ") } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item));
  const agentDataFootnotes = agentSummary?.data_footnotes ?? [];
  const visibleAgentDataFootnotes = agentDataFootnotes.slice(0, 4);
  if (factorySlotPreview && !asset) {
    const { slot, cell } = factorySlotPreview;
    return (
      <div className="mvp-asset-preview-panel">
        <div className="mvp-asset-preview">
          <header>
            <span className="mvp-slot-status">상태 미연결</span>
            <div><strong>{displayFactorySlotName(slot, cell)}</strong><small>{slot.assetId} · 고장 확정 아님</small></div>
          </header>
          <WorkStatusFixedBar status={effectiveWorkStatus} actionLabel={effectiveWorkActionLabel} statusSource={workStatusSource} disabled />
          <div className="mvp-drawer-tabs" role="tablist" aria-label="사이드뷰 탭">
            <button type="button" role="tab" aria-selected={activeTab === "status"} className={activeTab === "status" ? "is-active" : ""} onClick={() => onTabChange("status")}>상태</button>
            <button type="button" role="tab" aria-selected={activeTab === "action"} className={activeTab === "action" ? "is-active" : ""} onClick={() => onTabChange("action")}>처리</button>
          </div>
          <WorkStatusTimeline status={effectiveWorkStatus} lifecycleSummary={lifecycleSummary} />
          <ClosedLoopActivityTimeline timeline={activityTimeline} />
          {activeTab === "status" ? (
            <>
              <dl>
                <div><dt>구역</dt><dd>{displayFactorySite(cell.site)}</dd></div>
                <div><dt>셀</dt><dd>{displayFactoryCell(cell.cell)}</dd></div>
                <div><dt>설비 유형</dt><dd>{displayAssetType(slot.kind)}</dd></div>
                <div><dt>상태</dt><dd>상세 데이터 미연결</dd></div>
                <div><dt>작업 ID</dt><dd>{workId}</dd></div>
                <div><dt>관측 상세</dt><dd>상세 데이터 미연결</dd></div>
                <div><dt>계획 기준</dt><dd>생산계획 데이터 미연결</dd></div>
              </dl>
              <section className="mvp-production-impact-block" aria-label="정상 설비 상세">
                <header><Activity size={14} /><strong>설비 상세</strong><span>데모 배치</span></header>
                <dl>
                  <div><dt>설비 ID</dt><dd>{slot.assetId}</dd></div>
                  <div><dt>설비</dt><dd>{slot.label}</dd></div>
                  <div className="is-wide"><dt>배치</dt><dd>{displayFactorySite(cell.site)} · {displayFactoryCell(cell.cell)} · 데모 배치 슬롯</dd></div>
                  <div className="is-wide"><dt>상태 해석</dt><dd>현재 화면 데이터에 위험/정상 관측이 연결되지 않은 설비 슬롯입니다. 센서 관측과 생산 영향은 상세 데이터 연결 후 표시됩니다.</dd></div>
                </dl>
              </section>
            </>
          ) : activeTab === "action" ? (
            <section className="mvp-overview-action-panel" aria-label="정상 설비 처리">
              <header><ClipboardCheck size={14} /><strong>처리</strong><span>작업요청 없음</span></header>
              <div className="mvp-action-summary-card">
                <span className="mvp-slot-status">상태 미연결</span>
                <div>
                  <strong>{slot.label}</strong>
                  <small>작업요청 ID 없음 · 현재 조치 대상 아님</small>
                </div>
              </div>
              <dl className="mvp-action-facts">
                <div><dt>대상 설비</dt><dd>{slot.assetId}</dd></div>
                <div><dt>구역</dt><dd>{displayFactorySite(cell.site)}</dd></div>
                <div><dt>셀</dt><dd>{displayFactoryCell(cell.cell)}</dd></div>
                <div><dt>상태</dt><dd>상세 데이터 미연결</dd></div>
              </dl>
              <div className="mvp-action-placeholder-grid" aria-label="작업 입력 자리">
                <label><span>요청 메모</span><textarea disabled placeholder="요청 화면 연결 후 입력" /></label>
                <label><span>담당자</span><input disabled placeholder="미배정" /></label>
              </div>
              <WorkStatusPrimaryAction status={effectiveWorkStatus} actionLabel={effectiveWorkActionLabel} helperText={effectiveWorkActionHelper} disabled />
              <p className="mvp-action-note">
                위험 이벤트와 작업요청이 연결되지 않은 설비는 자동 조치하지 않습니다.
              </p>
            </section>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <div className="mvp-asset-preview-panel">
      {asset ? (
        <div className="mvp-asset-preview">
          <header>
            <MvpStatusBadge status={asset.status} />
            <div><strong>{assetDisplayName}</strong><small>{asset.line || asset.cell || asset.assetId} · 관측 {formatTimestamp(asset.observedAt)} · 고장 확정 아님</small></div>
            <button type="button" className="mvp-icon-button" onClick={() => setReportOutputOpen(true)} aria-label="보고서 출력" title="보고서 출력">
              <Printer size={15} />
            </button>
          </header>
          <WorkStatusFixedBar status={effectiveWorkStatus} actionLabel={effectiveWorkActionLabel} statusSource={workStatusSource} disabled={effectiveWorkActionDisabled} />
          <div className="mvp-drawer-tabs" role="tablist" aria-label="사이드뷰 탭">
            <button type="button" role="tab" aria-selected={activeTab === "status"} className={activeTab === "status" ? "is-active" : ""} onClick={() => onTabChange("status")}>상태</button>
            <button type="button" role="tab" aria-selected={activeTab === "action"} className={activeTab === "action" ? "is-active" : ""} onClick={() => onTabChange("action")}>처리</button>
          </div>
          <WorkStatusTimeline status={effectiveWorkStatus} lifecycleSummary={lifecycleSummary} />
          <ClosedLoopActivityTimeline timeline={activityTimeline} />
          {role === "process_manager" && activeTab === "status" ? (
            <>
              <dl>
                <div><dt>공장 위치</dt><dd>{assetDisplayName}</dd></div>
                <div><dt>계획 상태</dt><dd>{planningImpact ? PLANNING_STATUS_LABEL[planningImpact.status] : "생산 영향 미산정"}</dd></div>
                <div><dt>부품 제약</dt><dd>{displayPartLabel(asset.sparePartAvailable)}</dd></div>
                <div><dt>담당</dt><dd>{assignee}</dd></div>
                <div><dt>작업 ID</dt><dd>{workId}</dd></div>
                <div><dt>예상 정지 영향</dt><dd>{formatMinutes(asset.estimatedDowntimeMinutes)}</dd></div>
                <div><dt>신뢰도</dt><dd><MvpConfidenceBadge confidence={asset.confidence} /></dd></div>
                {lineSummary ? <div><dt>라인 설비</dt><dd>{lineSummary.line} · {lineSummary.assets.length}대</dd></div> : null}
                <div><dt>권고</dt><dd>{DECISION_LABEL[asset.recommendedDecision]}</dd></div>
              </dl>

              <section className="mvp-production-impact-block" aria-label="생산 영향">
                <header><Activity size={14} /><strong>생산 영향</strong><span>계획 기준 추정</span></header>
                <dl>
                  <div><dt>계획 영향</dt><dd>{productionLossLabel(planningImpact?.estimatedLossUnits ?? null)}</dd></div>
                  <div><dt>상태</dt><dd>{planningImpact ? PLANNING_STATUS_LABEL[planningImpact.status] : "생산 영향 미산정"}</dd></div>
                  <div><dt>생산 영향 수준</dt><dd>{lineSummary ? productionImpactLevelLabel(lineSummary, detail) : "생산 영향 수준 미연결"}</dd></div>
                  <div><dt>검토 우선순위</dt><dd>{lineSummary ? reviewPriorityLabel(lineSummary, detail) : "검토 우선순위 미제공"}</dd></div>
                  <div className="is-wide"><dt>근거</dt><dd>{planningBasisFromDetail(detail).value}</dd></div>
                  <div className="is-wide"><dt>다음 검토</dt><dd>{planningImpact ? `${planningImpact.nextAction} · 현장 점검 요청 필요` : "데이터 품질 확인 필요"}</dd></div>
                </dl>
                <p>합성 용량 모델 기반 계획 영향 추정 · 고장확률, 위험도, 점검 근거, 권고 판단을 변경하지 않습니다.</p>
              </section>
              {lineSummary ? (
                <section className="mvp-line-asset-list" aria-label="라인 위험 설비 목록">
                  <header><ClipboardList size={14} /><strong>{lineSummary.line} 위험 설비</strong><span>{lineSummary.assets.length}대</span></header>
                  <div>
                    {lineSummary.assets.map((lineAsset) => {
                      const currentLineAsset = lineAsset.assetId === asset.assetId ? asset : lineAsset;
                      return (
                        <button type="button" key={lineAsset.assetId} className={lineAsset.assetId === asset.assetId ? "is-selected" : ""} onClick={() => onPreviewAsset(lineAsset.assetId, lineAsset.eventId)}>
                          <MvpStatusBadge status={currentLineAsset.status} />
                          <strong>{displayFactoryAssetName(lineAsset.assetId) ?? displayAssetName(lineAsset)}</strong>
                          <span>{formatProbability(currentLineAsset.failureProbability)} · {displayPartLabel(lineAsset.sparePartAvailable)}</span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ) : null}
            </>
          ) : null}

          {role === "process_manager" && activeTab === "action" ? (
            <>
              <section className="mvp-overview-action-panel" aria-label="생산 관리자 처리">
                <header><ClipboardCheck size={14} /><strong>처리</strong><span>작업요청 검토</span></header>
                <div className="mvp-action-summary-card">
                  <MvpStatusBadge status={asset.status} />
                  <div>
                    <strong>{assetDisplayName}</strong>
                    <small>{workId} · 권고 {DECISION_LABEL[asset.recommendedDecision]}</small>
                  </div>
                </div>
                <dl className="mvp-action-facts">
                  <div><dt>대상 설비</dt><dd>{assetDisplayName}</dd></div>
                  <div><dt>계획 영향</dt><dd>{productionLossLabel(planningImpact?.estimatedLossUnits ?? null)}</dd></div>
                  <div><dt>담당</dt><dd>{assignee}</dd></div>
                  <div><dt>부품</dt><dd>{displayPartLabel(asset.sparePartAvailable)}</dd></div>
                  <div><dt>처리 상태</dt><dd>{WORK_STATUS_LABEL[effectiveWorkStatus]}</dd></div>
                  <div><dt>권한 액션</dt><dd>{effectiveWorkActionLabel ?? WORK_STATUS_ACTION[effectiveWorkStatus].label}</dd></div>
                </dl>
                <p className="mvp-action-note">
                  아래 Closed-loop 버튼은 현재 단계와 로그인 권한을 확인한 뒤 한 단계만 실행합니다.
                </p>
              </section>
              {eventId ? (
                <MaintenanceCostDecisionPanel
                  projectId={projectId}
                  workspaceId={workspaceId}
                  eventId={eventId}
                  guidance={inspectionTargets.find((item) => item.target?.inspectionGuidance)?.target?.inspectionGuidance ?? null}
                  onChanged={refreshWorkflow}
                  onEligibilityChanged={(eligible) => setCostReviewEventId(eligible ? eventId : null)}
                />
              ) : null}
              {eventId ? (
                <MaintenanceWorkflowActionPanel
                  key={`${eventId}:${workflowRevision}:manager`}
                  projectId={projectId}
                  workspaceId={workspaceId}
                  datasetVersionId={datasetVersionId}
                  eventId={eventId}
                  assetId={asset.assetId}
                  assetType={asset.assetType}
                  role={role}
                  currentUserId={currentUserId}
                  snapshotBasis={detail?.snapshotBasis ?? null}
                  canManage={canManageWorkflow}
                  canFieldExecute={canExecuteFieldWorkflow}
                  onChanged={refreshWorkflow}
                  onStatusChanged={setWorkflowStatus}
                  onPostMaintenancePrediction={reportPostMaintenancePrediction}
                />
              ) : null}
            </>
          ) : null}

          {role === "field_operator" && activeTab === "status" ? (
            <>
              <section className="mvp-agent-review-packet" aria-label="AI 검토 요약">
                <header>
                  <Bot size={14} />
                  <strong>AI 검토 요약</strong>
                  <span>저장 요약</span>
                  <button
                    type="button"
                    className="mvp-agent-review-refresh"
                    onClick={() => void loadAgentSummary(true)}
                    disabled={!canMaterializeAgentSummary || agentSummaryLoading || agentSummaryMaterializing}
                    aria-label="AI 요약 재생성"
                    title={canMaterializeAgentSummary ? "AI 요약 재생성" : "AI 요약 재생성 권한 없음"}
                  >
                    <RefreshCw className={agentSummaryMaterializing ? "mvp-action-spinner" : ""} size={13} />
                    <span>{agentSummaryMaterializing ? "생성 중" : canMaterializeAgentSummary ? "요약 재생성" : "재생성 권한 없음"}</span>
                  </button>
                </header>
                {!canMaterializeAgentSummary ? <p>현재 역할은 저장된 AI 요약만 조회할 수 있습니다.</p> : null}
                {agentSummaryLoading ? <p>저장된 AI 요약을 조회하는 중입니다.</p> : null}
                {agentSummaryMaterializing ? <p>현재 snapshot 기준 AI 요약을 다시 생성하는 중입니다.</p> : null}
                {!agentSummaryLoading ? (
                  <>
                    {agentSummaryError ? <p>{agentSummaryError}</p> : null}
                    {agentSummary ? (
                      <>
                        <div className="mvp-agent-review-meta" aria-label="AI 요약 상태">
                          <span>{agentSummaryStatusLabel(agentSummaryTrace, agentSummary)}</span>
                          <span>{agentSummaryModeLabel(agentSummary)}</span>
                          <span>{agentSummaryWorkflowRunLabel(agentSummaryTrace)}</span>
                          {agentFocusItems.length ? <span>{agentFocusItems.length}개 점검 계통</span> : null}
                        </div>
                        {agentEvidenceItems.length ? (
                          <div className="mvp-agent-evidence-grid" aria-label="AI 근거 요약">
                            {agentEvidenceItems.map((item) => (
                              <span key={`${agentSummary.asset_id}-evidence-${item.label}`}>
                                <b>{item.label}</b>
                                <em>{item.value}</em>
                              </span>
                            ))}
                          </div>
                        ) : null}
                        <div className="mvp-agent-review-draft">
                          <strong>{agentSummary.title}</strong>
                          <p>{agentSummary.summary}</p>
                          {currentRoleAgentSummaries.length ? (
                            <div className="mvp-agent-role-quotes" aria-label="현재 역할 AI 요약">
                              {currentRoleAgentSummaries.map((item) => (
                                <figure key={`${agentSummary.asset_id}-role-${item.role}`}>
                                  <figcaption>
                                    <span>{agentRoleSummaryCaption(item.role, item.label)}</span>
                                    <small>{agentRoleSummaryHint(item.role)}</small>
                                  </figcaption>
                                  <blockquote>{renderHighlightedAgentQuote(item.quote)}</blockquote>
                                </figure>
                              ))}
                            </div>
                          ) : null}
                          {agentFocusItems.length ? (
                            <ul>
                              {agentFocusItems.slice(0, 4).map((item) => (
                                <li key={`${agentSummary.asset_id}-focus-${item.component_id}`}>
                                  {item.component_label}{item.location_label ? ` · ${item.location_label}` : ""}
                                </li>
                              ))}
                            </ul>
                          ) : null}
                          <small>{agentSummary.boundary_note}</small>
                        </div>
                        {agentHistoryItems.length ? (
                          <div className="mvp-agent-history-strip" aria-label="이력 조회 요약">
                            {agentHistoryItems.slice(0, 3).map((item) => (
                              <span key={`${agentSummary.asset_id}-history-${item}`}>{formatAgentHistoryItem(item)}</span>
                            ))}
                          </div>
                        ) : null}
                        {visibleAgentDataFootnotes.length ? (
                          <ol className="mvp-agent-footnotes" aria-label="부족 데이터 각주">
                            {visibleAgentDataFootnotes.map((item, index) => (
                              <li key={`${agentSummary.asset_id}-footnote-${item.code}-${index}`}>
                                <sup>{index + 1}</sup>{item.note}
                              </li>
                            ))}
                          </ol>
                        ) : null}
                        {agentSummaryTrace?.materialization?.reused ? (
                          <small>동일 snapshot 기준 저장본을 재사용했습니다.</small>
                        ) : null}
                        {agentSummary.mode === "deterministic_fallback" ? (
                          <small>LLM 후보가 없거나 검증을 통과하지 못해 검증된 fallback 요약을 저장했습니다.</small>
                        ) : null}
                        <small>AI 요약은 검토 전용이며 Closed-loop 상태를 변경하지 않습니다.</small>
                      </>
                    ) : agentSummaryError ? null : (
                      <p>
                        저장된 AI 요약이 아직 없습니다. watcher 또는 생성 API가 같은 snapshot 기준 요약을 만들면 이 화면은 저장본만 재사용합니다.
                      </p>
                    )}
                  </>
                ) : null}
              </section>

              <section className="mvp-overview-inspection-panel mvp-side-map-report" aria-label="점검 근거">
                <header><Wrench size={14} /><strong>점검 근거</strong><span>SOP 참고 안내</span></header>
                <div className="equipment-sketch" aria-label="설비 참고도">
                  <EquipmentSketchVisual assetType={asset.assetType} inspectionTargets={inspectionTargets} />
                  <div>
                    <strong>{inspectionTargets[0]?.target?.componentLabel ?? candidate?.suspectedPart ?? (factors[0] ? fieldFactorItem(factors[0]) : fieldFailureLabel(asset.predictedFailureType))}</strong>
                    <ul className="sketch-legend">
                      {inspectionTargets.length ? inspectionTargets.map((target) => (
                        <li key={target.target?.targetId ?? target.factor?.id ?? `inspection-legend-${target.rank}`}>
                          <b>{target.rank}</b>{inspectionLocationLabel(target.target)}: {target.target?.componentLabel ?? (target.factor ? fieldFactorItem(target.factor) : "점검 후보")}
                          {target.target?.inspectionGuidance ? <small>{inspectionGuidanceSourceLabel(target.target)}</small> : null}
                        </li>
                      )) : <li><b>!</b>위치 근거: 부품 근거 없음</li>}
                    </ul>
                  </div>
                </div>
                <div className="target-list">
                  {inspectionTargets.length ? (
                    inspectionTargets.map((target) => (
                      <article key={target.target?.targetId ?? target.factor?.id ?? `inspection-target-${target.rank}`}>
                        <b>{target.rank}</b><i><Wrench size={18} /></i>
                        <div>
                          <strong>{target.target?.componentLabel ?? (target.factor ? fieldFactorItem(target.factor) : "점검 후보")}</strong>
                          <p>{target.target
                            ? `확인 이유: ${inspectionBasisSummary(target.target)}`
                            : target.factor?.direction === "risk_up"
                              ? `${fieldFactorSymptom(target.factor)}이 점검 우선순위를 높인 근거입니다.`
                              : `${target.factor ? fieldFactorSymptom(target.factor) : "근거"}이 위험 판단을 낮춘 보조 근거입니다.`}</p>
                          {target.target ? <p>{inspectionTopFactorBundleSummary(target.target)}</p> : null}
                          {target.target?.inspectionGuidance ? (
                            <p>{target.target.inspectionGuidance.disclaimer}</p>
                          ) : null}
                          {target.target?.inspectionGuidance?.maintenanceReviewPrerequisites ? (
                            <div className="mvp-inspection-guidance-note">
                              <strong>{replacementReviewTitle(target.target)}</strong>
                              <ul>
                                {maintenanceReviewPrerequisitePreview(target.target).map((item) => (
                                  <li key={`${target.target?.targetId}-maintenance-review-${item}`}>{item}</li>
                                ))}
                              </ul>
                              <small>{replacementReviewBoundaryLabel(target.target)}</small>
                            </div>
                          ) : null}
                        </div>
                        <span className="target-severity high">{target.factor ? factorValueLabel(target.factor) : "위치 미제공"}</span>
                      </article>
                    ))
                  ) : (
                    <article>
                      <b>!</b><i><Wrench size={18} /></i>
                      <div><strong>{candidate?.suspectedPart ?? fieldFailureLabel(asset.predictedFailureType)}</strong><p>점검 위치 근거가 제공되지 않았습니다.</p></div>
                      <span className="target-severity high">근거 부족</span>
                    </article>
                  )}
                </div>
              </section>

              <section className="mvp-overview-report-graph mvp-side-map-report" aria-label="요약 리포트 센서 관측 그래프">
                <header><LineChart size={14} /><strong>요약 리포트 관측 흐름</strong><span>{detailLoading ? "불러오는 중" : detailError ? "상세 연결 실패" : "동일 관측 기준"}</span></header>
                <div className="mvp-overview-risk-meter">
                  <div><span>위험 예측 확률</span><strong>{riskPercent === null ? "-" : `${riskPercent}%`}</strong></div>
                  <i aria-hidden="true"><b style={{ width: `${riskPercent ?? 0}%` }} /></i>
                  <small>고장 확정이 아니라 점검 우선순위 판단 근거입니다.</small>
                </div>
                <FeatureSeriesCollection
                  title="센서 관측 흐름"
                  sensors={directFeatureSnapshots}
                  windowId={sensorWindow}
                  onWindowChange={onSensorWindowChange}
                  emptyTitle="센서 이력 없음"
                  emptyDetail="현재 화면 데이터에는 표시할 센서 관측 이력이 없습니다."
                />
                <DerivedMetricSlots sensors={featureSnapshots} windowId={sensorWindow} />
              </section>
            </>
          ) : null}

          {role === "field_operator" && activeTab === "action" ? (
            <>
            <section className="mvp-overview-action-panel" aria-label="현장 관리자 처리">
              <header><Wrench size={14} /><strong>현장 처리</strong><span>점검 후보</span></header>
              <div className="mvp-action-summary-card">
                <MvpStatusBadge status={asset.status} />
                <div>
                  <strong>{candidate?.suspectedPart ?? (factors[0] ? fieldFactorItem(factors[0]) : fieldFailureLabel(asset.predictedFailureType))}</strong>
                  <small>{workId} · {planningImpact?.nextAction ?? "현장 점검 요청"}</small>
                </div>
              </div>
              <dl className="mvp-action-facts">
                <div><dt>대상 설비</dt><dd>{assetDisplayName}</dd></div>
                <div><dt>점검 항목</dt><dd>{candidate?.suspectedPart ?? (factors[0] ? fieldFactorItem(factors[0]) : "근거 부족")}</dd></div>
                <div><dt>설비 위치</dt><dd>{asset.cell || asset.line}</dd></div>
                <div><dt>부품</dt><dd>{displayPartLabel(asset.sparePartAvailable)}</dd></div>
                <div><dt>데이터 품질</dt><dd>{asset.status === "data_quality_hold" ? "데이터 품질 확인 필요" : "확인 가능"}</dd></div>
                <div><dt>작업 ID</dt><dd>{workId}</dd></div>
                <div><dt>다음 액션</dt><dd>{workActionLabel ?? planningImpact?.nextAction ?? "현장 점검 요청"}</dd></div>
              </dl>
              <p className="mvp-action-note">
                현장 관리자는 요청을 수락해 본인에게 배정한 뒤 점검을 시작할 수 있습니다.
              </p>
            </section>
            {eventId ? (
              <MaintenanceWorkflowActionPanel
                key={`${eventId}:${workflowRevision}:field`}
                projectId={projectId}
                workspaceId={workspaceId}
                datasetVersionId={datasetVersionId}
                eventId={eventId}
                assetId={asset.assetId}
                assetType={asset.assetType}
                role={role}
                currentUserId={currentUserId}
                snapshotBasis={detail?.snapshotBasis ?? null}
                canManage={canManageWorkflow}
                canFieldExecute={canExecuteFieldWorkflow}
                onChanged={refreshWorkflow}
                onStatusChanged={setWorkflowStatus}
                onPostMaintenancePrediction={reportPostMaintenancePrediction}
              />
            ) : null}
            </>
          ) : null}
          {reportOutputOpen ? (
            <ReportOutputDialog
              onSelect={outputReport}
              onClose={() => setReportOutputOpen(false)}
            />
          ) : null}
          {printReportTab ? (
            <WorkflowPrintReport
              reportTab={printReportTab}
              asset={asset}
              detail={detail}
              factors={factors}
              inspectionTargets={inspectionTargets}
              planningImpact={planningImpact}
              workStatus={workStatus}
              assignee={assignee}
              workId={workId}
            />
          ) : null}
        </div>
      ) : <MvpState kind="empty" title="선택된 설비가 없습니다" detail="왼쪽의 설비 또는 라인을 선택하세요." />}
    </div>
  );
}

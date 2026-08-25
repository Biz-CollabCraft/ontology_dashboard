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
} from "lucide-react";
import { useEffect, useState } from "react";
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
import {
  FIELD_FACTOR_LABELS,
  displayAssetName,
  displayAssetShortName,
  displayAssetType,
  displayEventAssetName,
  displayEventLabel,
  displayProductionImpact,
  displayReviewPriority,
  displaySensorLabel,
  fieldFactorItem,
  fieldFactorLocation,
  fieldFactorSymptom,
  fieldFailureLabel,
} from "../displayLabels";

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

interface LineImpactSummary {
  line: string;
  assets: MvpAsset[];
  highestRiskAsset: MvpAsset;
  averageRisk: number | null;
  critical: number;
  warning: number;
  hold: number;
  attention: number;
  planningRows: PlanningImpactRow[];
}

interface FactoryCellSlot {
  id: string;
  kind: "cnc" | "compressor";
  label: string;
  assetId: string;
  cell: string;
  asset: MvpAsset | null;
}

interface FactoryCellLayout {
  id: string;
  site: string;
  cell: string;
  label: string;
  planUnits: number;
  summary: LineImpactSummary | null;
  slots: FactoryCellSlot[];
}

interface FactorySlotPreview {
  slot: FactoryCellSlot;
  cell: FactoryCellLayout;
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
const PLANNING_MODEL_BASIS = "전체 설비 100대 계약 기준 · 16,200개/일 계획 영향 추정";
const FACTORY_SITE_IDS = ["S01", "S02", "S03", "S04"];
const FACTORY_CELLS_PER_SITE = 5;
const FACTORY_CELL_COUNT = FACTORY_SITE_IDS.length * FACTORY_CELLS_PER_SITE;
const FACTORY_CELL_PLAN_UNITS = Math.round(TODAY_PLAN_UNITS / FACTORY_CELL_COUNT);
const FACTORY_SITE_LABELS: Record<string, string> = {
  S01: "1구역",
  S02: "2구역",
  S03: "3구역",
  S04: "4구역",
};
const PLANNING_IMPACT_ROWS: PlanningImpactRow[] = [
  { assetId: "CNC-S04-L02-03", eventId: "EVT-GS-004", line: "S04-L02", productLabel: "금속 성형 부품 L", estimatedLossUnits: 51, status: "plan_at_risk", nextAction: "부품 재고 확인", sparePartAvailable: false },
  { assetId: "CNC-S01-L04-03", eventId: "EVT-GS-003", line: "S01-L04", productLabel: "성형 공정", estimatedLossUnits: 32, status: "shift_inspection", nextAction: "교대 내 점검 예약", sparePartAvailable: null },
  { assetId: "CNC-S04-L04-01", eventId: "EVT-GS-002", line: "S04-L04", productLabel: "가공 공정", estimatedLossUnits: 25, status: "inspection_priority", nextAction: "점검 우선", sparePartAvailable: null },
  { assetId: "CNC-S04-L05-01", eventId: "EVT-GS-007", line: "S04-L05", productLabel: "검사 공정", estimatedLossUnits: null, status: "data_quality_hold", nextAction: "데이터 품질 확인 필요", sparePartAvailable: true },
];

const PLANNING_STATUS_LABEL: Record<PlanningImpactRow["status"], string> = {
  plan_at_risk: "계획 위험",
  shift_inspection: "교대 내 점검",
  inspection_priority: "점검 우선",
  data_quality_hold: "데이터 품질 확인 필요",
};

const DERIVED_FEATURE_KEYS = new Set(["temperature_difference_k", "mechanical_power_w", "overstrain_index"]);
const PRIMARY_FIELD_SENSOR_KEYS = new Set(["torque_nm", "tool_wear_min", "rotational_speed_rpm"]);

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

function displayFactorySite(site: string): string {
  return FACTORY_SITE_LABELS[site] ?? site;
}

function displayFactoryCell(cell: string): string {
  const suffix = cell.match(/-L(\d+)$/)?.[1];
  return suffix ? `${Number(suffix)}셀` : cell;
}

function canonicalSlotAssetId(cell: string, kind: FactoryCellSlot["kind"], slotIndex: number): string {
  if (kind === "compressor") return `CMP-${cell}-01`;
  return `CNC-${cell}-${String(slotIndex).padStart(2, "0")}`;
}

function factorySlotLabel(kind: FactoryCellSlot["kind"], slotIndex: number): string {
  if (kind === "compressor") return "공기압축기";
  return `CNC 가공기 ${slotIndex}`;
}

function displayFactorySlotName(slot: FactoryCellSlot, cell: FactoryCellLayout): string {
  return `${displayFactorySite(cell.site)} · ${displayFactoryCell(cell.cell)} · ${slot.label}`;
}

function displayFactoryAssetName(assetId: string): string | null {
  const match = assetId.match(/^(CNC|CMP)-(S\d+)-L(\d+)-(\d+)$/);
  if (!match) return null;
  const [, prefix, site, line, slot] = match;
  const cell = `${site}-L${line}`;
  const kind: FactoryCellSlot["kind"] = prefix === "CMP" ? "compressor" : "cnc";
  return `${displayFactorySite(site)} · ${displayFactoryCell(cell)} · ${factorySlotLabel(kind, Number(slot))}`;
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

function buildLineImpactSummaries(assets: MvpAsset[]): LineImpactSummary[] {
  const groups = new Map<string, MvpAsset[]>();
  assets.forEach((asset) => {
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
      planningRows: PLANNING_IMPACT_ROWS.filter((row) => group.some((asset) => asset.assetId === row.assetId)),
    };
  }).sort((a, b) => {
    const toneWeight = { critical: 4, warning: 3, hold: 2, attention: 1, normal: 0 };
    return toneWeight[riskTone(b)] - toneWeight[riskTone(a)] || (b.averageRisk ?? -1) - (a.averageRisk ?? -1);
  });
}

function buildFactoryCellLayout(assets: MvpAsset[], summaries: LineImpactSummary[]): FactoryCellLayout[] {
  const assetsByCell = new Map<string, MvpAsset[]>();
  assets.forEach((asset) => {
    const cell = canonicalCellKeyFromAsset(asset);
    if (!cell) return;
    assetsByCell.set(cell, [...(assetsByCell.get(cell) ?? []), asset]);
  });
  const usedAssets = new Set<string>();
  return FACTORY_SITE_IDS.flatMap((site) =>
    Array.from({ length: FACTORY_CELLS_PER_SITE }, (_, cellIndex): FactoryCellLayout => {
      const cell = `${site}-L${String(cellIndex + 1).padStart(2, "0")}`;
      const cellAssets = assetsByCell.get(cell) ?? [];
      const summary = summaries.find((item) => item.assets.some((asset) => cellAssets.some((cellAsset) => cellAsset.assetId === asset.assetId))) ?? null;
      const slots: FactoryCellSlot[] = [
        { id: `${cell}-cmp`, kind: "compressor", label: factorySlotLabel("compressor", 1), assetId: canonicalSlotAssetId(cell, "compressor", 1), cell, asset: null },
        { id: `${cell}-cnc-1`, kind: "cnc", label: factorySlotLabel("cnc", 1), assetId: canonicalSlotAssetId(cell, "cnc", 1), cell, asset: null },
        { id: `${cell}-cnc-2`, kind: "cnc", label: factorySlotLabel("cnc", 2), assetId: canonicalSlotAssetId(cell, "cnc", 2), cell, asset: null },
        { id: `${cell}-cnc-3`, kind: "cnc", label: factorySlotLabel("cnc", 3), assetId: canonicalSlotAssetId(cell, "cnc", 3), cell, asset: null },
        { id: `${cell}-cnc-4`, kind: "cnc", label: factorySlotLabel("cnc", 4), assetId: canonicalSlotAssetId(cell, "cnc", 4), cell, asset: null },
      ];
      cellAssets.forEach((asset) => {
        const slotMatch = asset.assetId.match(/^(CNC|CMP)-S\d+-L\d+-(\d+)$/);
        const targetIndex = slotMatch?.[1] === "CMP" ? 0 : Number(slotMatch?.[2] ?? 1);
        if (usedAssets.has(asset.assetId)) return;
        const slot = slots[targetIndex] ?? slots[1];
        slot.asset = asset;
        if (asset) usedAssets.add(asset.assetId);
      });
      return {
        id: cell,
        site,
        cell,
        label: `${displayFactorySite(site)} · ${displayFactoryCell(cell)}`,
        planUnits: FACTORY_CELL_PLAN_UNITS,
        summary,
        slots,
      };
    })
  );
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

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
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
  const iqr = Math.max(p75 - p25, maximum - minimum, 1);
  const domainMinimum = Math.min(minimum, p25 - iqr * 0.65);
  const domainMaximum = Math.max(maximum, p75 + iqr * 0.65);
  const domainSpan = Math.max(domainMaximum - domainMinimum, 1);
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

function reviewPriorityLabel(summary: LineImpactSummary, detail: MvpEventDetailModel | null): string {
  const hasSelectedAsset = detail ? summary.assets.some((asset) => asset.assetId === detail.event.assetId) : false;
  return hasSelectedAsset ? displayReviewPriority(detail?.reviewPriority?.level) : "검토 우선순위 미제공";
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
  const lineImpactSummaries = buildLineImpactSummaries(model.assets);
  const factoryCells = buildFactoryCellLayout(model.assets, lineImpactSummaries);
  const selectedAsset = model.assets.find((asset) => asset.assetId === selectedAssetId)
    ?? topAssets[0]
    ?? null;
  const selectedEvent = selectedAsset?.eventId
    ? model.events.find((event) => event.eventId === selectedAsset.eventId) ?? null
    : null;
  const selectedFactors = detail?.event.assetId === selectedAsset?.assetId && detail.topFactors.length
    ? detail.topFactors
    : selectedAsset?.topFactors ?? [];
  const needsPartCheck = anomalyEvents.filter((event) => displayPartLabel(event.assetId, event.sparePartAvailable) !== "확보").length;
  const dataQualityEvent = model.events.find((event) => event.status === "data_quality_hold") ?? null;
  const dataQualityCount = model.events.filter((event) => event.status === "data_quality_hold").length;
  const spareMissingCount = PLANNING_IMPACT_ROWS.filter((row) => row.sparePartAvailable === false).length;
  const decisionCounts = DECISION_ORDER.map((decision) => ({
    decision,
    count: model.events.filter((event) => event.recommendedDecision === decision).length,
  }));
  const riskyLines = model.lineRisk.filter((line) => line.critical + line.warning + line.dataQualityHold > 0).length;
  const selectedLineSummary = selectedAsset
    ? lineImpactSummaries.find((summary) => summary.line === (selectedAsset.line || selectedAsset.cell || "라인 근거 없음")) ?? null
    : null;
  const selectedCandidate = selectedEvent
    ? workOrderCandidates.find((candidate) => candidate.event.eventId === selectedEvent.eventId) ?? null
    : null;
  const selectedRiskPercent = selectedAsset?.failureProbability === null || selectedAsset?.failureProbability === undefined
    ? null
    : Math.round(selectedAsset.failureProbability * 100);
  const selectedPlanningImpact = planningImpactForAsset(selectedAsset?.assetId);
  const maxPlanningImpact = PLANNING_IMPACT_ROWS.find((row) => row.eventId === "EVT-GS-004") ?? PLANNING_IMPACT_ROWS[0];
  const agentSummaryLine = role === "field_operator"
    ? `점검 후보 ${workOrderCandidates.length}건 · 부품 확인 ${needsPartCheck}건 · 작업요청 ID 미생성`
    : `위험 라인 ${riskyLines}개 · 라인 ${lineImpactSummaries.length}개 · 평균 위험도 ${formatProbability(metrics.averageRisk)}`;
  const [detailDrawerOpen, setDetailDrawerOpen] = useState(false);
  const [detailDrawerTab, setDetailDrawerTab] = useState<DrawerTab>("status");
  const [factorySlotPreview, setFactorySlotPreview] = useState<FactorySlotPreview | null>(null);
  const drawerAsset = factorySlotPreview?.slot.asset ?? (factorySlotPreview ? null : selectedAsset);
  const drawerEvent = drawerAsset?.eventId
    ? model.events.find((event) => event.eventId === drawerAsset.eventId) ?? null
    : null;
  const drawerCandidate = drawerEvent
    ? workOrderCandidates.find((candidate) => candidate.event.eventId === drawerEvent.eventId) ?? null
    : null;
  const drawerLineSummary = drawerAsset
    ? lineImpactSummaries.find((summary) => summary.line === (drawerAsset.line || drawerAsset.cell || "라인 근거 없음")) ?? null
    : null;
  const drawerFactors = drawerAsset && detail?.event.assetId === drawerAsset.assetId && detail.topFactors.length
    ? detail.topFactors
    : drawerAsset?.topFactors ?? [];
  const drawerRiskPercent = drawerAsset?.failureProbability === null || drawerAsset?.failureProbability === undefined
    ? null
    : Math.round(drawerAsset.failureProbability * 100);
  const drawerPlanningImpact = planningImpactForAsset(drawerAsset?.assetId);

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
                ? `${displayAssetName(selectedAsset)} 기준으로 점검 후보를 먼저 봅니다`
                : `생산 리스크 요약 · ${displayFactoryAssetName(selectedAsset.assetId) ?? displayAssetName(selectedAsset)} 우선 관리`
              : "선택된 설비가 없습니다"}
          </strong>
          <p>
            {role === "field_operator"
              ? "자동 작업요청 생성이나 승인 실행은 하지 않고, 현재 관측 기준의 점검 근거만 다음 클릭으로 이어줍니다."
              : `${agentSummaryLine} · 계획 영향은 합성 용량 모델 기반 추정이며 생산계획 화면 데이터 연결 전 표시입니다.`}
          </p>
        </div>
        {role === "process_manager" ? (
          <div className="mvp-agent-sample-strip" aria-label="생산 관리 관련 데이터">
            <span>오늘 계획 {TODAY_PLAN_UNITS.toLocaleString()}개/일</span>
            <span>생산계획 화면 데이터 미연결</span>
            <span>실제 생산관리 실적 아님</span>
          </div>
        ) : null}
        <button type="button" className="mvp-button ghost" onClick={onRefresh}><RefreshCw size={15} />새로고침</button>
      </section>

      {role === "process_manager" ? (
        <section className="mvp-overview-topline" aria-label="생산 관리자 상단 지표">
          <article className="mvp-plan-impact-card">
            <span>오늘 계획</span>
            <strong>{TODAY_PLAN_UNITS.toLocaleString()}개/일</strong>
            <small>계획 기준 · 생산계획 화면 데이터 미연결</small>
          </article>
          <article className="mvp-plan-impact-card is-critical">
            <span>최대 계획 영향</span>
            <strong>{productionLossLabel(maxPlanningImpact.estimatedLossUnits)}</strong>
            <small>{displayEventLabel(maxPlanningImpact.eventId)} / {displayFactoryAssetName(maxPlanningImpact.assetId) ?? displayAssetName({ assetId: maxPlanningImpact.assetId })}</small>
          </article>
          <article className="mvp-plan-impact-card">
            <span>즉시 판단 필요</span>
            <strong>1건</strong>
            <small>계획 위험 이벤트 기준</small>
          </article>
          <article className="mvp-plan-impact-card is-hold">
            <span>데이터 품질 보류</span>
            <strong>{dataQualityCount.toLocaleString()}건</strong>
            <small>생산 영향 미산정 포함</small>
          </article>
          <article className="mvp-plan-impact-card is-hold">
            <span>부품 미확보</span>
            <strong>{spareMissingCount.toLocaleString()}건</strong>
            <small>조치 제약 확인 필요</small>
          </article>
        </section>
      ) : (
        <section className="mvp-overview-topline" aria-label="현장 관리자 상단 지표">
          <article className="mvp-plan-impact-card">
            <span>점검 후보</span>
            <strong>{workOrderCandidates.length.toLocaleString()}건</strong>
            <small>작업요청 미생성 후보</small>
          </article>
          <article className="mvp-plan-impact-card is-critical">
            <span>최우선 설비</span>
            <strong>{displayAssetName(selectedAsset)}</strong>
            <small>최우선 점검 대상</small>
          </article>
          <article className="mvp-plan-impact-card">
            <span>부품 확인 필요</span>
            <strong>{needsPartCheck.toLocaleString()}건</strong>
            <small>미확보 또는 확인 필요 후보</small>
          </article>
          <article className="mvp-plan-impact-card is-hold">
            <span>데이터 품질 확인</span>
            <strong>{dataQualityCount.toLocaleString()}건</strong>
            <small>{dataQualityEvent ? `${displayEventAssetName(dataQualityEvent)} / ${displayEventLabel(dataQualityEvent)}` : "품질 보류 없음"}</small>
          </article>
          <article className="mvp-plan-impact-card">
            <span>작업 상태</span>
            <strong>미생성</strong>
            <small>작업요청 ID 미생성 · 점검 후보</small>
          </article>
        </section>
      )}

      {role === "field_operator" ? (
        <div className="mvp-role-overview mvp-role-overview-wide">
          <MvpPanel title="우선순위" eyebrow="점검 요청 기준" className="mvp-today-panel">
            <div className="mvp-order-board">
              <header><ClipboardList size={15} /><strong>점검 후보 · 의심 부품</strong><span>{workOrderCandidates.length}건</span></header>
              <div className="mvp-work-card-list">
                {workOrderCandidates.length ? workOrderCandidates.map((candidate, index) => (
                  <button type="button" key={candidate.event.eventId} className={selectedAsset?.assetId === candidate.event.assetId ? "mvp-work-card is-selected" : "mvp-work-card"} onClick={() => previewInDrawer(candidate.event.assetId, candidate.event.eventId)}>
                    <div><MvpStatusBadge status={candidate.event.status} /><strong>{candidate.suspectedPart}</strong><small>제안 #{String(index + 1).padStart(2, "0")} · {displayEventAssetName(candidate.event)}</small></div>
                    <dl>
                      <div><dt>설비</dt><dd>{displayEventAssetName(candidate.event)}</dd></div>
                      <div><dt>부품</dt><dd>{displayPartLabel(candidate.event.assetId, candidate.event.sparePartAvailable)}</dd></div>
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
          <MvpPanel title="전체 공장 셀별 설비 지도" eyebrow="공장 셀 기준" className="mvp-process-panel mvp-factory-map-panel">
            <div className="mvp-plan-impact-note">100대 설비 계약 배치 · 4구역 × 5셀 · 셀당 공기압축기 1대 + CNC 가공기 4대 · 계획 영향 추정</div>
            {factoryCells.length ? (
              <div className="mvp-factory-map">
                <div className="mvp-factory-map-legend" aria-label="설비 상태 범례">
                  <i className="critical">위험</i><i className="warning">경고</i><i className="attention">주의</i><i className="normal">정상</i><i className="hold">데이터 확인</i>
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
                      <article key={site} className={`mvp-factory-line-row tone-${siteTone} ${siteAssets.some((asset) => asset.assetId === selectedAsset?.assetId) ? "is-selected" : ""}`}>
                        <header>
                          <strong>{displayFactorySite(site)}</strong>
                          <small>{siteCells.length}셀 · 설비 25대 · 셀 계획 {FACTORY_CELL_PLAN_UNITS.toLocaleString()}개/일</small>
                        </header>
                        <div className="mvp-factory-cell-grid" aria-label={`${site} 셀별 설비 상태`}>
                          {siteCells.map((cell) => (
                            <section key={cell.id} className={`mvp-factory-cell-card tone-${cell.summary ? riskTone(cell.summary) : "empty"} ${cell.slots.some((slot) => slot.asset?.assetId === selectedAsset?.assetId) ? "is-selected" : ""}`} aria-label={cell.label}>
                              <header>
                                <strong>{displayFactoryCell(cell.cell)}</strong>
                                <small>{cell.summary ? `${cell.summary.assets.length}건 확인` : `${cell.planUnits.toLocaleString()}개/일`}</small>
                              </header>
                              <div className="mvp-factory-cell-slots">
                                {cell.slots.map((slot) => {
                                  const asset = slot.asset;
                                  const selected = asset
                                    ? selectedAsset?.assetId === asset.assetId
                                    : factorySlotPreview?.slot.id === slot.id;
                                  const tone = asset ? mapTone(asset.status) : "slot";
                                  const title = asset
                                    ? `${displayFactorySlotName(slot, cell)} · ${formatProbability(asset.failureProbability)} · ${displayPartLabel(asset.assetId, asset.sparePartAvailable)}`
                                    : `${cell.label} · ${slot.label} · 설비 상세`;
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

          <div className="mvp-manager-column">
            <MvpPanel title="진행 현황" eyebrow="검토 대기">
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

      {(drawerAsset || factorySlotPreview) && detailDrawerOpen ? (
        <div className="mvp-detail-drawer-layer" role="presentation">
          <button
            type="button"
            className="mvp-detail-drawer-scrim"
            aria-label="상세 패널 닫기"
            onClick={() => setDetailDrawerOpen(false)}
          />
          <aside className="mvp-detail-drawer" role="dialog" aria-modal="true" aria-label="선택 설비 상세">
            <AssetPreviewPanel asset={drawerAsset} factorySlotPreview={factorySlotPreview} event={drawerEvent} candidate={drawerCandidate} lineSummary={drawerLineSummary} factors={drawerFactors} riskPercent={drawerRiskPercent} planningImpact={drawerPlanningImpact} detail={factorySlotPreview && !drawerAsset ? null : detail} detailLoading={factorySlotPreview && !drawerAsset ? false : detailLoading} detailError={factorySlotPreview && !drawerAsset ? null : detailError} role={role} activeTab={detailDrawerTab} onTabChange={setDetailDrawerTab} onOpenAsset={onOpenAsset} onOpenEvent={onOpenEvent} onOpenReport={onOpenReport} />
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
  emptyTitle,
  emptyDetail,
  qualityStatus,
  currentValue,
  currentObservedAt,
  fieldItemLabel,
  primary,
}: {
  title: string;
  unit: string | null;
  points: SeriesDatum[];
  emptyTitle: string;
  emptyDetail: string;
  qualityStatus?: "good" | "bad" | "unknown";
  currentValue?: number | string | boolean | null;
  currentObservedAt?: string | null;
  fieldItemLabel?: string;
  primary?: boolean;
}) {
  const color = title.includes("진동") || title.includes("토크") ? "#a7630c" : "#285fcb";
  const numericPoints = points.filter((point): point is SeriesDatum & { value: number } => typeof point.value === "number" && Number.isFinite(point.value));
  const currentNumericValue = typeof currentValue === "number" && Number.isFinite(currentValue) ? currentValue : null;
  if (!points.length || !numericPoints.length) {
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
  const rawSpan = Math.max(1, rawMaximum - rawMinimum);
  const min = rawMinimum - rawSpan * 0.08;
  const max = rawMaximum + rawSpan * 0.08;
  const range = Math.max(1, max - min);
  const chartWidth = 720;
  const chartHeight = 282;
  const frame = { left: 64, right: 690, top: 22, bottom: 226 };
  const width = frame.right - frame.left;
  const totalSlots = points.length + (currentObservedAt ? 1 : 0);
  const height = frame.bottom - frame.top;
  const yAt = (value: number) => frame.bottom - ((value - min) / range) * height;
  const xAt = (index: number) => totalSlots <= 1 ? (frame.left + frame.right) / 2 : frame.left + (width * index) / (totalSlots - 1);
  const coords = points.map((point, index) => {
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
  const latest = numericPoints[numericPoints.length - 1];
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
  const currentPoint = currentNumericValue === null || !currentObservedAt ? null : { x: xAt(points.length), y: yAt(currentNumericValue), value: currentNumericValue };
  return (
    <section className={primary ? "asset-series-block is-primary" : "asset-series-block"}>
      <header className="asset-series-heading">
        <div><RotateCcw size={17} /><strong>{title}</strong></div>
        <span className="asset-baseline-key"><i style={{ background: color }} />최근 24시간 관측 분포</span>
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
        <text className="asset-chart-axis" x={frame.left} y="252" textAnchor="start">{formatSeriesTime(points[0].observedAt)}</text>
        {currentPoint ? <text className="asset-chart-axis asset-current-axis" x={currentPoint.x} y="252" textAnchor="end">현재 {currentTimeLabel}</text> : null}
        <text className="asset-chart-axis-title" x="376" y="270" textAnchor="middle">시간</text>
      </svg>
    </section>
  );
}

function FeatureSeriesCollection({
  title,
  sensors,
  emptyTitle,
  emptyDetail,
}: {
  title: string;
  sensors: ReturnType<typeof sensorSeries>;
  emptyTitle: string;
  emptyDetail: string;
}) {
  const primarySensors = sensors.filter((sensor) => PRIMARY_FIELD_SENSOR_KEYS.has(sensor.id));
  const secondarySensors = sensors.filter((sensor) => !PRIMARY_FIELD_SENSOR_KEYS.has(sensor.id));
  const visibleSensors = primarySensors.length ? primarySensors : sensors;
  return (
    <section className="mvp-feature-series-collection" aria-label={title}>
      <header><LineChart size={14} /><strong>{title}</strong><span>관측 이력 기반</span></header>
      {sensors.length ? (
        <>
          {visibleSensors.map((sensor) => (
            <MapReportFeatureSeries
              key={sensor.id}
              title={sensor.label}
              unit={sensor.unit}
              points={sensor.points}
              qualityStatus={sensor.currentQuality}
              currentValue={sensor.currentValue}
              currentObservedAt={sensor.currentObservedAt}
              fieldItemLabel={FIELD_FACTOR_LABELS[sensor.id]?.item}
              primary={PRIMARY_FIELD_SENSOR_KEYS.has(sensor.id)}
              emptyTitle="관측 이력 없음"
              emptyDetail={`${sensor.label} 관측 이력이 비어 있어 임의 그래프를 표시하지 않습니다.`}
            />
          ))}
          {primarySensors.length && secondarySensors.length ? (
            <details className="mvp-derived-metric-dropdown mvp-secondary-sensor-series">
              <summary><span><LineChart size={14} />보조 센서 관측</span><b>{secondarySensors.length}개</b></summary>
              <div className="mvp-derived-series-list">
                {secondarySensors.map((sensor) => (
                  <MapReportFeatureSeries
                    key={sensor.id}
                    title={sensor.label}
                    unit={sensor.unit}
                    points={sensor.points}
                    qualityStatus={sensor.currentQuality}
                    currentValue={sensor.currentValue}
                    currentObservedAt={sensor.currentObservedAt}
                    fieldItemLabel={FIELD_FACTOR_LABELS[sensor.id]?.item}
                    emptyTitle="관측 이력 없음"
                    emptyDetail={`${sensor.label} 관측 이력이 비어 있어 임의 그래프를 표시하지 않습니다.`}
                  />
                ))}
              </div>
            </details>
          ) : null}
        </>
      ) : <MvpState kind="empty" title={emptyTitle} detail={emptyDetail} />}
    </section>
  );
}

function DerivedMetricSlots({ sensors }: { sensors: ReturnType<typeof sensorSeries> }) {
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
              qualityStatus={sensor.currentQuality}
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
  event,
  candidate,
  lineSummary,
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
  factorySlotPreview: FactorySlotPreview | null;
  event: MvpEvent | null;
  candidate: WorkOrderCandidate | null;
  lineSummary: LineImpactSummary | null;
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
  const featureSnapshots = sensorSeries(detail, asset);
  const directFeatureSnapshots = featureSnapshots.filter((sensor) => !DERIVED_FEATURE_KEYS.has(sensor.id));
  const inspectionTargets = factors.slice(0, 3).map((factor, index) => ({
    factor,
    rank: index + 1,
    location: inspectionLocationForFeature(factor.feature),
  }));
  const fallbackInspectionLocation = inspectionLocationForFeature(asset?.predictedFailureType ?? "");
  const factoryAssetName = factorySlotPreview ? displayFactorySlotName(factorySlotPreview.slot, factorySlotPreview.cell) : null;
  const assetDisplayName = asset ? factoryAssetName ?? displayAssetName(asset) : "선택된 설비 없음";
  if (factorySlotPreview && !asset) {
    const { slot, cell } = factorySlotPreview;
    return (
      <div className="mvp-asset-preview-panel">
        <div className="mvp-asset-preview">
          <div className="mvp-drawer-tabs" role="tablist" aria-label="사이드뷰 탭">
            <button type="button" role="tab" aria-selected={activeTab === "status"} className={activeTab === "status" ? "is-active" : ""} onClick={() => onTabChange("status")}>상태</button>
            <button type="button" role="tab" aria-selected={activeTab === "action"} className={activeTab === "action" ? "is-active" : ""} onClick={() => onTabChange("action")}>처리</button>
          </div>
          <header>
            <span className="mvp-slot-status">상태 미연결</span>
            <div><strong>{slot.label}</strong><small>{cell.label} · {slot.assetId}</small></div>
          </header>
          {activeTab === "status" ? (
            <>
              <dl>
                <div><dt>구역</dt><dd>{displayFactorySite(cell.site)}</dd></div>
                <div><dt>셀</dt><dd>{displayFactoryCell(cell.cell)}</dd></div>
                <div><dt>설비 유형</dt><dd>{displayAssetType(slot.kind)}</dd></div>
                <div><dt>상태</dt><dd>상세 데이터 미연결</dd></div>
                <div><dt>관측 상세</dt><dd>상세 데이터 미연결</dd></div>
                <div><dt>계획 기준</dt><dd>{cell.planUnits.toLocaleString()}개/일</dd></div>
              </dl>
              <section className="mvp-production-impact-block" aria-label="정상 설비 상세">
                <header><Activity size={14} /><strong>설비 상세</strong><span>계약 배치 기준</span></header>
                <dl>
                  <div><dt>설비 ID</dt><dd>{slot.assetId}</dd></div>
                  <div><dt>설비</dt><dd>{slot.label}</dd></div>
                  <div className="is-wide"><dt>배치</dt><dd>{displayFactorySite(cell.site)} · {displayFactoryCell(cell.cell)} · 공기압축기 1대와 CNC 가공기 4대 구성</dd></div>
                  <div className="is-wide"><dt>상태 해석</dt><dd>현재 화면 데이터에 위험/정상 관측이 연결되지 않은 설비 슬롯입니다. 센서 관측과 생산 영향은 상세 데이터 연결 후 표시됩니다.</dd></div>
                </dl>
              </section>
            </>
          ) : (
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
              <p className="mvp-action-note">
                위험 이벤트와 작업요청이 연결되지 않은 설비는 자동 조치하지 않습니다.
              </p>
            </section>
          )}
        </div>
      </div>
    );
  }
  return (
    <div className="mvp-asset-preview-panel">
      {asset ? (
        <div className="mvp-asset-preview">
          <div className="mvp-drawer-tabs" role="tablist" aria-label="사이드뷰 탭">
            <button type="button" role="tab" aria-selected={activeTab === "status"} className={activeTab === "status" ? "is-active" : ""} onClick={() => onTabChange("status")}>상태</button>
            <button type="button" role="tab" aria-selected={activeTab === "action"} className={activeTab === "action" ? "is-active" : ""} onClick={() => onTabChange("action")}>처리</button>
          </div>
          <header>
            <MvpStatusBadge status={asset.status} />
            <div><strong>{assetDisplayName}</strong><small>{factorySlotPreview ? `관측 ${formatTimestamp(asset.observedAt)}` : `${asset.assetId} · 관측 ${formatTimestamp(asset.observedAt)}`}</small></div>
          </header>
          {role === "process_manager" && activeTab === "status" ? (
            <>
              <dl>
                <div><dt>공장 위치</dt><dd>{assetDisplayName}</dd></div>
                <div><dt>계획 상태</dt><dd>{planningImpact ? PLANNING_STATUS_LABEL[planningImpact.status] : "생산 영향 미산정"}</dd></div>
                <div><dt>부품 제약</dt><dd>{displayPartLabel(asset.assetId, asset.sparePartAvailable)}</dd></div>
                <div><dt>담당</dt><dd>{asset.assignedEngineer ?? "미배정"}</dd></div>
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
                  <div className="is-wide"><dt>근거</dt><dd>{PLANNING_MODEL_BASIS}</dd></div>
                  <div className="is-wide"><dt>다음 검토</dt><dd>{planningImpact ? `${planningImpact.nextAction} · 현장 점검 요청 필요` : "데이터 품질 확인 필요"}</dd></div>
                </dl>
                <p>합성 용량 모델 기반 계획 영향 추정 · 고장확률, 위험도, 점검 근거, 권고 판단을 변경하지 않습니다.</p>
                <div className="mvp-side-action-flow">
                  <button type="button" className="mvp-button primary" onClick={() => event && onOpenEvent(event.eventId, event.assetId)} disabled={!event}><ClipboardCheck size={14} />작업요청에서 검토</button>
                  <button type="button" className="mvp-button ghost" onClick={() => onTabChange("action")}><ArrowRight size={14} />처리 탭</button>
                </div>
              </section>
              {lineSummary ? (
                <section className="mvp-line-asset-list" aria-label="라인 위험 설비 목록">
                  <header><ClipboardList size={14} /><strong>{lineSummary.line} 위험 설비</strong><span>{lineSummary.assets.length}대</span></header>
                  <div>
                    {lineSummary.assets.map((lineAsset) => (
                      <button type="button" key={lineAsset.assetId} className={lineAsset.assetId === asset.assetId ? "is-selected" : ""} onClick={() => onOpenAsset(lineAsset.assetId, lineAsset.eventId)}>
                        <MvpStatusBadge status={lineAsset.status} />
                        <strong>{displayFactoryAssetName(lineAsset.assetId) ?? displayAssetName(lineAsset)}</strong>
                        <span>{formatProbability(lineAsset.failureProbability)} · {displayPartLabel(lineAsset.assetId, lineAsset.sparePartAvailable)}</span>
                      </button>
                    ))}
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
                    <small>작업요청 ID 미생성 · 권고 {DECISION_LABEL[asset.recommendedDecision]}</small>
                  </div>
                </div>
                <dl className="mvp-action-facts">
                  <div><dt>대상 설비</dt><dd>{assetDisplayName}</dd></div>
                  <div><dt>계획 영향</dt><dd>{productionLossLabel(planningImpact?.estimatedLossUnits ?? null)}</dd></div>
                  <div><dt>담당</dt><dd>{asset.assignedEngineer ?? "미배정"}</dd></div>
                  <div><dt>부품</dt><dd>{displayPartLabel(asset.assetId, asset.sparePartAvailable)}</dd></div>
                  <div><dt>처리 상태</dt><dd>후보 검토</dd></div>
                  <div><dt>권한 액션</dt><dd>작업요청에서 처리</dd></div>
                </dl>
                <div className="mvp-side-action-flow">
                  <button type="button" className="mvp-button secondary" onClick={() => onTabChange("status")}><LineChart size={14} />상태 다시 보기</button>
                  <button type="button" className="mvp-button primary" onClick={() => event && onOpenEvent(event.eventId, event.assetId)} disabled={!event}><ClipboardCheck size={14} />작업요청에서 처리</button>
                  <button type="button" className="mvp-button ghost" onClick={() => onOpenReport(event?.eventId ?? null, asset.assetId)}><FileText size={14} />보고서 보기</button>
                </div>
                <p className="mvp-action-note">
                  승인, 보류, 반려, 메모 저장은 자동 실행하지 않고 작업요청의 승인 절차에서 처리합니다.
                </p>
              </section>
            </>
          ) : null}

          {role === "field_operator" && activeTab === "status" ? (
            <>
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
                    <strong>{candidate?.suspectedPart ?? (factors[0] ? fieldFactorItem(factors[0]) : fieldFailureLabel(asset.predictedFailureType))}</strong>
                    <ul className="sketch-legend">
                      {inspectionTargets.length ? inspectionTargets.map((target) => (
                        <li key={target.factor.id}><b>{target.rank}</b>{fieldFactorLocation(target.factor)}: {target.location.note}</li>
                      )) : <li><b>!</b>점검 위치: 부품 근거 없음</li>}
                    </ul>
                  </div>
                </div>
                <div className="target-list">
                  {inspectionTargets.length ? (
                    inspectionTargets.map((target) => (
                      <article key={target.factor.id}>
                        <b>{target.rank}</b><i><Wrench size={18} /></i>
                        <div><strong>{fieldFactorItem(target.factor)}</strong><p>{target.factor.direction === "risk_up" ? `${fieldFactorSymptom(target.factor)}이 점검 우선순위를 높인 근거입니다.` : `${fieldFactorSymptom(target.factor)}이 위험 판단을 낮춘 보조 근거입니다.`}</p></div>
                        <span className="target-severity high">{factorValueLabel(target.factor)}</span>
                      </article>
                    ))
                  ) : (
                    <article>
                      <b>!</b><i><Wrench size={18} /></i>
                      <div><strong>{candidate?.suspectedPart ?? fieldFailureLabel(asset.predictedFailureType)}</strong><p>현장 점검 위치 확인이 필요합니다.</p></div>
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
                  emptyTitle="센서 이력 없음"
                  emptyDetail="현재 화면 데이터에는 표시할 센서 관측 이력이 없습니다."
                />
                <DerivedMetricSlots sensors={featureSnapshots} />
              </section>
            </>
          ) : null}

          {role === "field_operator" && activeTab === "action" ? (
            <section className="mvp-overview-action-panel" aria-label="현장 관리자 처리">
              <header><Wrench size={14} /><strong>현장 처리</strong><span>점검 후보</span></header>
              <div className="mvp-action-summary-card">
                <MvpStatusBadge status={asset.status} />
                <div>
                  <strong>{candidate?.suspectedPart ?? (factors[0] ? fieldFactorItem(factors[0]) : fieldFailureLabel(asset.predictedFailureType))}</strong>
                  <small>작업요청 ID 미생성 · {planningImpact?.nextAction ?? "현장 점검 요청"}</small>
                </div>
              </div>
              <dl className="mvp-action-facts">
                <div><dt>대상 설비</dt><dd>{assetDisplayName}</dd></div>
                <div><dt>점검 항목</dt><dd>{candidate?.suspectedPart ?? (factors[0] ? fieldFactorItem(factors[0]) : "근거 부족")}</dd></div>
                <div><dt>점검 위치</dt><dd>{asset.cell || asset.line}</dd></div>
                <div><dt>부품</dt><dd>{displayPartLabel(asset.assetId, asset.sparePartAvailable)}</dd></div>
                <div><dt>데이터 품질</dt><dd>{asset.status === "data_quality_hold" ? "데이터 품질 확인 필요" : "확인 가능"}</dd></div>
                <div><dt>다음 액션</dt><dd>{planningImpact?.nextAction ?? "현장 점검 요청"}</dd></div>
              </dl>
              <div className="mvp-side-action-flow">
                <button type="button" className="mvp-button secondary" onClick={() => onTabChange("status")}><LineChart size={14} />상태 다시 보기</button>
                <button type="button" className="mvp-button primary" onClick={() => event && onOpenEvent(event.eventId, event.assetId)} disabled={!event}><ClipboardCheck size={14} />작업요청에서 처리</button>
                <button type="button" className="mvp-button ghost" onClick={() => onOpenReport(event?.eventId ?? null, asset.assetId)}><FileText size={14} />보고서 보기</button>
              </div>
              <p className="mvp-action-note">
                점검 요청 후보이며 작업요청이나 정비 조치는 실제 생성하지 않습니다.
              </p>
            </section>
          ) : null}
        </div>
      ) : <MvpState kind="empty" title="선택된 설비가 없습니다" detail="왼쪽의 설비 또는 라인을 선택하세요." />}
    </div>
  );
}

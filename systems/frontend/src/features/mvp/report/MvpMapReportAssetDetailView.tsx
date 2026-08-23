import { CalendarRange, Database, Gauge, History, RotateCcw, Volume2 } from "lucide-react";
import { useMemo, useState } from "react";
import type { MvpAsset, MvpBootstrapModel, MvpEvent, MvpRiskStatus } from "../api/mvpContracts";
import { formatTimestamp } from "../components/MvpUi";

const observedAt = "2026-08-29 23:00";
const alarmThresholdBasis = "0.85로 낮추면 고장 5건을 더 잡지만 점검 126회가 늘어납니다. 계획 점검 0.5h 기준 추가 점검 63h, 조기 포착 절감 24.6h라 순손해 약 38.4h입니다. 그래서 알람 경계는 0.90으로 둡니다.";

const detailRangeOptions = [
  { id: "1h", label: "1시간", minutes: 60, pointCount: 7, displayGrain: "10분 원본", ticks: ["22:00", "22:20", "22:40", "23:00"] },
  { id: "6h", label: "6시간", minutes: 360, pointCount: 37, displayGrain: "10분 원본", ticks: ["17:00", "19:00", "21:00", "23:00"] },
  { id: "24h", label: "24시간", minutes: 1_440, pointCount: 49, displayGrain: "30분 평균", ticks: ["08/29 00", "08:00", "16:00", "23:00"] },
  { id: "7d", label: "7일", minutes: 10_080, pointCount: 29, displayGrain: "6시간 평균", ticks: ["08/23", "08/25", "08/27", "08/29"] },
  { id: "30d", label: "30일", minutes: 43_200, pointCount: 31, displayGrain: "1일 평균", ticks: ["08/01", "08/10", "08/20", "08/29"] },
] as const;

type DetailRange = (typeof detailRangeOptions)[number];
type HistoryTone = "critical" | "warning" | "normal" | "hold";

interface Baseline {
  lower: number;
  upper: number;
}

interface Domain {
  minimum: number;
  maximum: number;
}

interface AssetHistoryRow {
  id: string;
  occurredAt: string;
  kind: string;
  tone: HistoryTone;
  description: string;
  source: string;
  memo?: string;
}

interface FeatureTemplate {
  key: string;
  label: string;
  unit: string;
  current: number;
  baseline: Baseline;
  domain: Domain;
  expectedSide: "low" | "high";
  history: Array<[string, string, string, string, string?]>;
}

interface DetailFeature extends Omit<FeatureTemplate, "current" | "history"> {
  current: number | null;
  history: AssetHistoryRow[];
}

interface AssetDetailViewModel {
  asset: {
    assetId: string;
    displayName: string;
    assetType: string;
    locationLabel: string;
    status: MvpRiskStatus;
    probability: number | null;
    observedAt: string;
  };
  observationIntervalMinutes: number;
  ranges: readonly DetailRange[];
  risk: {
    current: number | null;
    threshold: number;
    domain: Domain;
  };
  features: DetailFeature[];
  equipmentHistory: AssetHistoryRow[];
  provenance: {
    displayMode: "fixture-view-model";
  };
}

const equipmentHistory: AssetHistoryRow[] = [
  { id: "event-current-risk", occurredAt: "2026-08-29 23:00", kind: "예측 알람", tone: "critical", description: "24시간 내 위험 예측이 알람 경계를 넘어 점검 요청 후보가 생성되었습니다.", source: "시스템 기록" },
  { id: "event-sensor-anomaly", occurredAt: "2026-08-29 20:20", kind: "센서 이상", tone: "warning", description: "주요 피처가 평상시 평균 범위를 벗어난 상태로 관측되었습니다.", source: "시스템 기록" },
  { id: "maintenance-20260812", occurredAt: "2026-08-12 10:30", kind: "정기 점검", tone: "normal", description: "벨트 장력 조정과 구동부 윤활을 완료했습니다.", source: "김도윤", memo: "벨트 장력이 기준 하한에 가까워 재조정했습니다. 2주 뒤 회전 편차를 다시 확인하세요." },
  { id: "maintenance-20260728", occurredAt: "2026-07-28 18:10", kind: "복구 점검", tone: "normal", description: "전원과 축 정렬을 확인한 뒤 설비를 재가동했습니다.", source: "박지훈", memo: "축 정렬 보정 후 공회전 테스트에서 진동이 정상 범위로 복귀했습니다." },
  { id: "failure-20260728", occurredAt: "2026-07-28 17:30", kind: "고장", tone: "critical", description: "설비 정지 이벤트가 기록되었습니다. 원인은 이 화면에서 확정하지 않습니다.", source: "운영 기록" },
  { id: "maintenance-20260603", occurredAt: "2026-06-03 09:15", kind: "정기 점검", tone: "normal", description: "필터·윤활 상태와 센서 부착 상태를 확인했습니다.", source: "이서진", memo: "특이사항이 없었고 센서 체결 상태가 양호해 정상 기준 데이터로 사용할 수 있습니다." },
  { id: "anomaly-20260511", occurredAt: "2026-05-11 14:40", kind: "이상", tone: "warning", description: "진동 평균이 일시 상승한 뒤 30분 내 평상시 범위로 복귀했습니다.", source: "시스템 기록" },
];

const compressorFeatures: FeatureTemplate[] = [
  {
    key: "rotation_raw",
    label: "회전 평균",
    unit: "rpm",
    current: 420.1,
    baseline: { lower: 448, upper: 462 },
    domain: { minimum: 400, maximum: 475 },
    expectedSide: "low",
    history: [
      ["2026-08-29 23:00", "위험", "420.1 rpm · 평균 대비 -2.9σ · 낮음 지속", "현재값"],
      ["2026-08-29 21:40", "이상", "회전 평균이 기준선 대비 -2.1σ에 도달", "알람 연결"],
      ["2026-08-29 19:50", "범위 이탈", "평상시 평균 범위 448-462 rpm 최초 이탈", "자동 기록"],
      ["2026-08-12 10:40", "점검 후", "454.8 rpm · 평상시 범위 복귀", "김도윤", "벨트 장력 조정 직후 30분 평균입니다. 회전 편차가 감소한 것을 확인했습니다."],
      ["2026-07-28 17:30", "고장 시점", "398.2 rpm · 급격한 회전 저하 기록", "고장 이력"],
      ["2026-06-03 09:15", "점검 기준", "456.1 rpm · 기준선 갱신에 사용", "이서진", "무부하·정상 부하 구간 모두 안정적이어서 정상 기준 데이터로 승인했습니다."],
    ],
  },
  {
    key: "vibration_raw",
    label: "진동 평균",
    unit: "mm/s",
    current: 39.8,
    baseline: { lower: 35.4, upper: 37.8 },
    domain: { minimum: 33.5, maximum: 43 },
    expectedSide: "high",
    history: [
      ["2026-08-29 23:00", "위험", "39.8 mm/s · 평균 대비 +1.6σ · 높음 지속", "현재값"],
      ["2026-08-29 22:10", "이상", "진동 평균이 기준선 대비 +1.3σ에 도달", "알람 연결"],
      ["2026-08-29 21:00", "범위 이탈", "평상시 평균 범위 35.4-37.8 mm/s 최초 이탈", "자동 기록"],
      ["2026-08-12 10:40", "점검 후", "36.1 mm/s · 평상시 범위 복귀", "김도윤", "윤활 및 벨트 장력 조정 후 진동이 안정됐습니다. 베어링 소음은 관찰되지 않았습니다."],
      ["2026-07-28 17:30", "고장 시점", "44.2 mm/s · 고진동 구간 기록", "고장 이력"],
      ["2026-06-03 09:15", "점검 기준", "36.7 mm/s · 기준선 갱신에 사용", "이서진", "센서 체결 상태와 측정 방향을 확인했고 정상 진동값으로 승인했습니다."],
    ],
  },
];

const cncFeatures: FeatureTemplate[] = [
  {
    key: "rotational_speed_rpm",
    label: "회전 속도",
    unit: "rpm",
    current: 1342,
    baseline: { lower: 1450, upper: 1650 },
    domain: { minimum: 1200, maximum: 1750 },
    expectedSide: "low",
    history: [
      ["2026-08-29 23:00", "주의", "1,342 rpm · 평상시 범위 아래에서 관측", "현재값"],
      ["2026-08-29 20:10", "범위 이탈", "평상시 회전 범위 1,450-1,650 rpm 최초 이탈", "자동 기록"],
      ["2026-08-12 11:20", "점검 후", "1,538 rpm · 평상시 범위 복귀", "김도윤", "공구와 주축 체결 상태를 확인한 뒤 시험 운전에서 회전 속도가 안정됐습니다."],
      ["2026-07-19 16:30", "이상", "1,301 rpm · 저회전 구간 기록", "운영 기록"],
    ],
  },
  {
    key: "torque_nm",
    label: "토크 평균",
    unit: "N·m",
    current: 57.8,
    baseline: { lower: 34, upper: 50 },
    domain: { minimum: 25, maximum: 65 },
    expectedSide: "high",
    history: [
      ["2026-08-29 23:00", "주의", "57.8 N·m · 평상시 범위 위에서 관측", "현재값"],
      ["2026-08-29 21:00", "범위 이탈", "평상시 토크 범위 34-50 N·m 최초 이탈", "자동 기록"],
      ["2026-08-12 11:20", "점검 후", "43.4 N·m · 평상시 범위 복귀", "김도윤", "시험 운전 중 토크가 기준 범위에 머무는 것을 확인했습니다."],
      ["2026-07-19 16:30", "이상", "61.2 N·m · 고토크 구간 기록", "운영 기록"],
    ],
  },
];

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function hashSeed(value: string) {
  return [...value].reduce((accumulator, character) => (accumulator * 31 + character.charCodeAt(0)) % 997, 17) / 997;
}

function buildSeries({ start, end, count, amplitude, cycles, phase, minimum, maximum }: {
  start: number;
  end: number;
  count: number;
  amplitude: number;
  cycles: number;
  phase: number;
  minimum: number;
  maximum: number;
}) {
  const values = Array.from({ length: count }, (_, index) => {
    const progress = index / Math.max(1, count - 1);
    const trend = start + (end - start) * progress;
    const wave = Math.sin((progress * cycles + phase) * Math.PI * 2) * amplitude * (0.9 - progress * 0.35);
    const secondary = Math.sin((progress * cycles * 2.1 + 0.23) * Math.PI * 2) * amplitude * 0.2;
    return clamp(trend + wave + secondary, minimum, maximum);
  });
  values[values.length - 1] = end;
  return values;
}

function normalizeHistory(rows: FeatureTemplate["history"], prefix: string): AssetHistoryRow[] {
  return rows.map(([occurredAt, kind, description, source, memo], index) => ({
    id: `${prefix}-${index}`,
    occurredAt,
    kind,
    tone: kind.includes("위험") || kind.includes("고장") ? "critical" : kind.includes("이상") || kind.includes("이탈") || kind.includes("주의") ? "warning" : "normal",
    description,
    source,
    memo,
  }));
}

function adjustedFeature(feature: FeatureTemplate, asset: MvpAsset): DetailFeature {
  const probability = asset.failureProbability ?? 0.5;
  const severity = Math.max(0.45, probability);
  const baselineCenter = (feature.baseline.lower + feature.baseline.upper) / 2;
  const span = feature.baseline.upper - feature.baseline.lower;
  const derivedCurrent = feature.expectedSide === "low"
    ? baselineCenter - span * (0.45 + severity)
    : baselineCenter + span * (0.15 + severity * 0.65);
  const current = asset.assetId.includes("CMP-S03-L03-01") ? feature.current : derivedCurrent;
  const normalizedHistory = normalizeHistory(feature.history, `${asset.assetId}-${feature.key}`);

  if (asset.status === "data_quality_hold") {
    normalizedHistory[0] = {
      ...normalizedHistory[0],
      kind: "데이터 확인",
      tone: "warning",
      description: "현재 피처 값이 없어 데이터 수집 상태 확인이 필요합니다.",
      source: "품질 게이트",
    };
  } else {
    normalizedHistory[0] = {
      ...normalizedHistory[0],
      description: `${Number(current).toLocaleString("ko-KR", { maximumFractionDigits: 1 })} ${feature.unit} · 현재 선택 설비 관측값`,
    };
  }

  return {
    ...feature,
    current: asset.status === "data_quality_hold" ? null : Number(current.toFixed(1)),
    history: normalizedHistory,
  };
}

function buildAssetDetailViewModel(asset: MvpAsset): AssetDetailViewModel {
  const isCompressor = asset.assetType.toLowerCase().includes("compressor") || asset.assetId.startsWith("M-");
  const featureTemplate = isCompressor ? compressorFeatures : cncFeatures;
  const history = equipmentHistory.map((row) => ({ ...row, id: `${asset.assetId}-${row.id}` }));

  if (asset.status === "data_quality_hold") {
    history[0] = {
      ...history[0],
      kind: "데이터 확인",
      tone: "warning",
      description: "현재 위험 예측값을 확정할 수 없어 데이터 품질 확인 상태로 보류되었습니다.",
      source: "품질 게이트",
    };
  } else {
    history[0] = {
      ...history[0],
      kind: (asset.failureProbability ?? 0) >= 0.7 ? "예측 알람" : "예측 갱신",
      tone: (asset.failureProbability ?? 0) >= 0.7 ? "critical" : (asset.failureProbability ?? 0) >= 0.4 ? "warning" : "normal",
      description: `24시간 내 위험 예측 ${Number((asset.failureProbability ?? 0) * 100).toFixed(1)}%가 기록되었습니다. 고장 확정은 아닙니다.`,
    };
  }

  return {
    asset: {
      assetId: asset.assetId,
      displayName: asset.displayName,
      assetType: asset.assetType,
      locationLabel: asset.line || `${asset.site} / ${asset.cell}`,
      status: asset.status,
      probability: asset.failureProbability,
      observedAt,
    },
    observationIntervalMinutes: 10,
    ranges: detailRangeOptions,
    risk: {
      current: asset.failureProbability === null ? null : Number((asset.failureProbability * 100).toFixed(1)),
      threshold: 90,
      domain: { minimum: 0, maximum: 100 },
    },
    features: featureTemplate.map((feature) => adjustedFeature(feature, asset)),
    equipmentHistory: history,
    provenance: { displayMode: "fixture-view-model" },
  };
}

function createRangeSeries(viewModel: AssetDetailViewModel, range: DetailRange) {
  const rangeWeight = { "1h": 0.22, "6h": 0.48, "24h": 0.68, "7d": 0.84, "30d": 1 }[range.id] ?? 0.48;
  const phase = hashSeed(`${viewModel.asset.assetId}-${range.id}`);
  const cycles = 1.2 + rangeWeight * 3.8;
  const risk = viewModel.risk.current === null
    ? []
    : buildSeries({
      start: Math.max(4, viewModel.risk.current - 58 * rangeWeight),
      end: viewModel.risk.current,
      count: range.pointCount,
      amplitude: 2.4 + rangeWeight * 11,
      cycles,
      phase,
      ...viewModel.risk.domain,
    });

  const features = viewModel.features.map((feature, featureIndex) => {
    if (feature.current === null) return { ...feature, values: [] };
    const baselineCenter = (feature.baseline.lower + feature.baseline.upper) / 2;
    const span = feature.baseline.upper - feature.baseline.lower;
    const historicalStart = baselineCenter + (feature.expectedSide === "low" ? span * 0.08 : -span * 0.06);
    return {
      ...feature,
      values: buildSeries({
        start: historicalStart,
        end: feature.current,
        count: range.pointCount,
        amplitude: span * (0.08 + rangeWeight * 0.22),
        cycles: cycles + featureIndex * 0.65,
        phase: phase + featureIndex * 0.29,
        ...feature.domain,
      }),
    };
  });

  return { risk, features };
}

function formatValue(value: number | null | undefined, unit = "") {
  if (value === null || value === undefined) return "데이터 없음";
  const digits = Math.abs(value) >= 100 ? 0 : 1;
  return `${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: digits })}${unit ? ` ${unit}` : ""}`;
}

function formatCrossingTime(range: DetailRange, index: number, count: number) {
  if (index === 0) return "조회 시작 이전";
  const progress = index / Math.max(1, count - 1);
  const endTime = new Date("2026-08-29T23:00:00+09:00").getTime();
  const timestamp = endTime - range.minutes * 60_000 + progress * range.minutes * 60_000;
  const date = new Date(timestamp);
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    month: range.minutes > 1_440 ? "2-digit" : undefined,
    day: range.minutes > 1_440 ? "2-digit" : undefined,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function buildVisibleDomain({
  values,
  domain,
  baseline,
  threshold,
}: {
  values: number[];
  domain: Domain;
  baseline?: Baseline;
  threshold?: number;
}) {
  const anchors = [
    ...values,
    ...(baseline ? [baseline.lower, baseline.upper] : []),
    ...(threshold !== undefined ? [threshold] : []),
  ].filter(Number.isFinite);

  if (anchors.length === 0) return domain;

  const rawMinimum = Math.min(...anchors);
  const rawMaximum = Math.max(...anchors);
  const rawSpan = Math.max(rawMaximum - rawMinimum, (domain.maximum - domain.minimum) * 0.08, 1);
  const padding = rawSpan * 0.18;
  const minimum = Math.max(domain.minimum, rawMinimum - padding);
  const maximum = Math.min(domain.maximum, rawMaximum + padding);

  if (maximum - minimum < rawSpan * 0.4) return domain;
  return { minimum, maximum };
}

function SeriesChart({
  title,
  icon: Icon,
  unit,
  values,
  range,
  domain,
  baseline,
  threshold,
  color,
  emptyLabel,
}: {
  title: string;
  icon: typeof Gauge;
  unit: string;
  values: number[];
  range: DetailRange;
  domain: Domain;
  baseline?: Baseline;
  threshold?: number;
  color: string;
  emptyLabel: string;
}) {
  const frame = { left: 68, right: 684, top: 16, bottom: 274 };
  const width = frame.right - frame.left;
  const height = frame.bottom - frame.top;
  const visibleDomain = buildVisibleDomain({ values, domain, baseline, threshold });
  const xAt = (index: number) => frame.left + (index / Math.max(1, values.length - 1)) * width;
  const yAt = (value: number) => frame.bottom - ((value - visibleDomain.minimum) / (visibleDomain.maximum - visibleDomain.minimum)) * height;
  const points = values.map((value, index) => `${xAt(index).toFixed(1)},${yAt(value).toFixed(1)}`).join(" ");
  const crossingIndex = values.findIndex((value) => threshold !== undefined ? value >= threshold : baseline ? value < baseline.lower || value > baseline.upper : false);
  const crossingX = crossingIndex >= 0 ? xAt(crossingIndex) : null;
  const crossingY = crossingIndex >= 0 ? yAt(values[crossingIndex]) : null;
  const current = values.at(-1);
  const currentY = current === undefined ? null : yAt(current);
  const yTicks = [visibleDomain.maximum, (visibleDomain.minimum + visibleDomain.maximum) / 2, visibleDomain.minimum];

  return (
    <section className="asset-series-block">
      <header className="asset-series-heading">
        <div><Icon size={17} /><strong>{title}</strong></div>
        {baseline ? <span className="asset-baseline-key"><i style={{ background: color }} />평상시 평균 {formatValue(baseline.lower, unit)}-{formatValue(baseline.upper, unit)}</span> : null}
        {threshold !== undefined ? (
          <span className="asset-threshold-key" tabIndex={0} data-tooltip={alarmThresholdBasis} aria-label={alarmThresholdBasis}>
            알람 경계 {threshold}% <small>근거</small>
          </span>
        ) : null}
      </header>
      {values.length === 0 ? (
        <div className="asset-chart-empty"><Database size={20} /><strong>{emptyLabel}</strong><span>값을 0으로 대체하지 않습니다.</span></div>
      ) : (
        <svg className="asset-series-chart" viewBox="0 0 720 316" role="img" aria-label={`${title} ${range.label} 시계열`}>
          <rect className="asset-chart-frame" x={frame.left} y={frame.top} width={width} height={height} />
          {yTicks.map((tick) => {
            const y = yAt(tick);
            return <g key={tick}><line className="asset-chart-grid" x1={frame.left} x2={frame.right} y1={y} y2={y} /><text className="asset-chart-axis" x="58" y={y + 4} textAnchor="end">{formatValue(tick)}</text></g>;
          })}
          {baseline ? <rect className="asset-baseline-band" x={frame.left} y={yAt(baseline.upper)} width={width} height={yAt(baseline.lower) - yAt(baseline.upper)} style={{ fill: color }} /> : null}
          {threshold !== undefined ? <line className="asset-threshold-line" x1={frame.left} x2={frame.right} y1={yAt(threshold)} y2={yAt(threshold)} /> : null}
          <polyline className="asset-series-line" points={points} style={{ stroke: color }} />
          {crossingIndex >= 0 && crossingX !== null && crossingY !== null ? (
            <g>
              <line className="asset-crossing-line" x1={crossingX} x2={crossingX} y1={crossingY} y2={frame.bottom} style={{ stroke: color }} />
              <circle className="asset-crossing-marker" cx={crossingX} cy={crossingY} r="5" style={{ fill: color }} />
              <text className="asset-crossing-label" x={clamp(crossingX + 8, 76, 548)} y={clamp(crossingY + 17, 30, 268)} style={{ fill: color }}>
                {threshold !== undefined ? "알람 경계 초과" : "범위 이탈"} {formatCrossingTime(range, crossingIndex, values.length)}
              </text>
            </g>
          ) : null}
          {currentY !== null ? <circle className="asset-current-marker" cx={frame.right} cy={currentY} r="5" style={{ fill: color }} /> : null}
          {currentY !== null ? <text className="asset-current-label" x="674" y={clamp(currentY - 8, 25, 270)} textAnchor="end" style={{ fill: color }}>{formatValue(current, unit)}</text> : null}
          {range.ticks.map((tick, index) => <text key={tick} className="asset-chart-axis" x={frame.left + (index / 3) * width} y="296" textAnchor={index === 0 ? "start" : index === 3 ? "end" : "middle"}>{tick}</text>)}
          <text className="asset-chart-axis-title" x="376" y="312" textAnchor="middle">시간</text>
        </svg>
      )}
    </section>
  );
}

function HistoryTable({ title, rows, kindLabel = "유형" }: { title: string; rows: AssetHistoryRow[]; kindLabel?: string }) {
  return (
    <section className="asset-history-section">
      <header><div><History size={16} /><strong>{title}</strong></div><span>전체 {rows.length}건 · 최신순</span></header>
      <div className="asset-history-columns" aria-hidden="true"><span>일시</span><span>{kindLabel}</span><span>이력 내용</span><span>담당·메모</span></div>
      <div className="asset-history-rows">
        {rows.map((row) => (
          <article className="asset-history-row" key={row.id}>
            <time>{row.occurredAt}</time>
            <span className={`asset-history-kind ${row.tone}`}>{row.kind}</span>
            <p>{row.description}</p>
            <div className="asset-history-source">
              {row.memo ? <details><summary>{row.source} · 점검 메모</summary><div className="asset-history-memo"><strong>점검자 메모</strong><p>{row.memo}</p></div></details> : row.source}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export function MvpMapReportAssetDetailView({
  model,
  selectedEvent,
  onSelectEvent,
  statusMeta,
}: {
  model: MvpBootstrapModel;
  selectedEvent: MvpEvent | null;
  onSelectEvent: (event: MvpEvent) => void;
  statusMeta: Record<MvpRiskStatus, { label: string; tone: string }>;
}) {
  const [rangeId, setRangeId] = useState<DetailRange["id"]>("6h");
  const eventById = useMemo(() => new Map(model.events.map((event) => [event.eventId, event])), [model.events]);
  const selectedAsset = model.assets.find((asset) => asset.eventId === selectedEvent?.eventId)
    ?? model.assets.find((asset) => asset.assetId === selectedEvent?.assetId)
    ?? model.assets.find((asset) => asset.eventId)
    ?? model.assets[0]
    ?? null;
  const viewModel = selectedAsset ? buildAssetDetailViewModel(selectedAsset) : null;
  const range = viewModel?.ranges.find((item) => item.id === rangeId) ?? detailRangeOptions[1];
  const rangeSeries = useMemo(() => viewModel ? createRangeSeries(viewModel, range) : null, [range, viewModel]);
  const status = viewModel ? statusMeta[viewModel.asset.status] : null;

  if (!viewModel || !rangeSeries) {
    return <div className="asset-detail-view mvp-asset-graphs" data-testid="mvp-summary-graphs"><p>선택 가능한 설비가 없습니다.</p></div>;
  }

  return (
    <div className="asset-detail-view mvp-asset-graphs" data-testid="mvp-summary-graphs">
      <section className="asset-detail-header">
        <div className="asset-detail-header-main">
          <span>선택 설비 상세</span>
          <h1>{viewModel.asset.displayName}</h1>
          <p>{viewModel.asset.assetType} · {viewModel.asset.locationLabel} · {viewModel.asset.assetId}</p>
        </div>
        <label className="asset-detail-picker">
          <span>다른 설비 보기</span>
          <select value={selectedAsset.eventId ?? ""} onChange={(event) => {
            const next = eventById.get(event.target.value);
            if (next) onSelectEvent(next);
          }}>
            {model.assets.filter((asset) => asset.eventId).map((asset) => (
              <option value={asset.eventId ?? ""} key={asset.assetId}>{asset.displayName} · {statusMeta[asset.status].label}</option>
            ))}
          </select>
        </label>
        {status ? <span className={`status-badge ${status.tone}`}>{status.label}</span> : null}
        <dl className="asset-detail-facts">
          <div><dt>24시간 위험 예측</dt><dd>{viewModel.risk.current === null ? "데이터 없음" : `${viewModel.risk.current.toFixed(1)}%`}</dd></div>
          <div><dt>원본 관측 간격</dt><dd>{viewModel.observationIntervalMinutes}분</dd></div>
          <div><dt>기준 시각</dt><dd>{formatTimestamp(selectedAsset.observedAt ?? model.context.observedAt) || viewModel.asset.observedAt}</dd></div>
          <div><dt>표시 모드</dt><dd>{viewModel.provenance.displayMode === "fixture-view-model" ? "Fixture Replay" : "Runtime 저장 데이터"}</dd></div>
        </dl>
      </section>

      <section className="asset-graph-workspace">
        <header className="asset-graph-toolbar">
          <div><span>피처 그래프와 전체 이력</span><h2>범위별 설비 상태 변화</h2></div>
          <div className="asset-range-group" role="group" aria-label="그래프 시간 범위">
            {viewModel.ranges.map((item) => <button type="button" key={item.id} aria-pressed={item.id === range.id} onClick={() => setRangeId(item.id)}>{item.label}</button>)}
          </div>
          <div className="asset-range-meta"><CalendarRange size={15} />원본 10분 · {range.displayGrain}</div>
        </header>

        <SeriesChart title="24시간 내 고장 위험도" icon={Gauge} unit="%" values={rangeSeries.risk} range={range} domain={viewModel.risk.domain} threshold={viewModel.risk.threshold} color="#b42318" emptyLabel="위험도 시계열을 표시할 수 없습니다" />
        <HistoryTable title={`설비 전체 이력 · ${viewModel.asset.assetId}`} rows={viewModel.equipmentHistory} />
        {rangeSeries.features.map((feature) => (
          <div key={feature.key}>
            <SeriesChart title={feature.label} icon={feature.key.includes("vibration") || feature.key.includes("torque") ? Volume2 : RotateCcw} unit={feature.unit} values={feature.values} range={range} domain={feature.domain} baseline={feature.baseline} color={feature.key.includes("vibration") || feature.key.includes("torque") ? "#a7630c" : "#285fcb"} emptyLabel={`${feature.label} 시계열을 표시할 수 없습니다`} />
            <HistoryTable title={`${feature.label} 전체 이력`} rows={feature.history} kindLabel="피처 상태" />
          </div>
        ))}
      </section>
    </div>
  );
}

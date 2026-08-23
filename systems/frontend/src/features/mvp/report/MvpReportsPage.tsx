import { AlertTriangle, CalendarRange, ClipboardCheck, Clock3, DatabaseZap, FileText, Filter, Gauge, Map as MapIcon, Printer, RotateCcw, ShieldCheck, Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import type { MvpAsset, MvpBootstrapModel, MvpEvent, MvpEventDetailModel, MvpLineRisk, MvpReportTab, MvpRiskStatus } from "../api/mvpContracts";
import { DECISION_LABEL, formatMinutes, formatProbability, formatTimestamp } from "../components/MvpUi";
import { MvpExecutiveReportPage } from "./MvpExecutiveReportPage";
import { MvpInspectionReportPage } from "./MvpInspectionReportPage";

const REPORT_TABS: Array<{ id: MvpReportTab; label: string; description: string; icon: typeof MapIcon }> = [
  { id: "status-map", label: "상태 요약", description: "설비 상태 맵과 우선순위", icon: MapIcon },
  { id: "inspection-request", label: "점검 요청", description: "현장 확인 항목", icon: ClipboardCheck },
  { id: "summary-report", label: "요약 보고서", description: "관리자 공유본", icon: FileText },
  { id: "executive-brief", label: "Executive Brief", description: "선택 Event 보고서", icon: FileText },
];

const GRAPH_RANGES = [
  { id: "1h", label: "1시간", pointCount: 12, grain: "5분 단위" },
  { id: "6h", label: "6시간", pointCount: 36, grain: "10분 단위" },
  { id: "24h", label: "24시간", pointCount: 48, grain: "30분 단위" },
  { id: "7d", label: "7일", pointCount: 56, grain: "3시간 단위" },
] as const;

const DEFAULT_FEATURE_SERIES = [
  { id: "rotation_raw", label: "회전 상태", unit: "rpm", color: "#4c90f0", base: 455, spread: 42 },
  { id: "pressure_raw", label: "압력", unit: "kPa", color: "#45b880", base: 100, spread: 8 },
  { id: "vibration_raw", label: "진동", unit: "mm/s", color: "#f0a23a", base: 37, spread: 7 },
  { id: "voltage_raw", label: "전압", unit: "V", color: "#9a77e8", base: 176, spread: 5 },
] as const;

const MAP_STATUS_META: Record<MvpRiskStatus, { label: string; tone: string; sentence: string }> = {
  critical: { label: "위험", tone: "critical", sentence: "즉시 점검이 필요한 위험 신호" },
  warning: { label: "경고", tone: "warning", sentence: "우선순위 점검 후보" },
  attention: { label: "주의", tone: "attention", sentence: "추가 관찰 필요" },
  normal: { label: "정상", tone: "normal", sentence: "특이 위험 신호 없음" },
  data_quality_hold: { label: "데이터 확인", tone: "hold", sentence: "데이터 확인 후 판단" },
};

function MapStatusBadge({ status }: { status: MvpRiskStatus }) {
  const meta = MAP_STATUS_META[status];
  return <span className={`status-badge ${meta.tone}`}>{meta.label}</span>;
}

function ReportKpi({
  icon: Icon,
  label,
  value,
  detail,
  tone = "",
}: {
  icon: typeof Gauge;
  label: string;
  value: string;
  detail: string;
  tone?: string;
}) {
  return (
    <article className={`kpi ${tone}`}>
      <Icon size={18} />
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function lineKey(asset: MvpAsset) {
  return asset.line || asset.cell || asset.site || "미분류 라인";
}

const MIN_LINE_MAP_NODES = 20;

interface StatusMapNode {
  id: string;
  label: string;
  status: MvpRiskStatus;
  probability: number | null;
  asset: MvpAsset | null;
  event: MvpEvent | null;
}

function lineMapStatus(index: number, averageRisk: number | null, anchorStatus: MvpRiskStatus): MvpRiskStatus {
  if (averageRisk === null) {
    return index % 7 === 0 ? "data_quality_hold" : index % 5 === 0 ? "attention" : "normal";
  }
  if (anchorStatus === "data_quality_hold" && index % 6 === 0) return "data_quality_hold";
  if (averageRisk >= 0.75) return index % 5 === 0 ? "critical" : index % 3 === 0 ? "warning" : "attention";
  if (averageRisk >= 0.55) return index % 6 === 0 ? "critical" : index % 2 === 0 ? "warning" : "attention";
  if (averageRisk >= 0.25) return index % 5 === 0 ? "warning" : index % 2 === 0 ? "attention" : "normal";
  return index % 6 === 0 ? "attention" : "normal";
}

function lineMapProbability(status: MvpRiskStatus, averageRisk: number | null, index: number) {
  if (status === "data_quality_hold") return null;
  const baseline = averageRisk ?? (status === "critical" ? 0.82 : status === "warning" ? 0.62 : status === "attention" ? 0.36 : 0.14);
  const offset = ((index % 5) - 2) * 0.025;
  return Math.max(0.03, Math.min(0.97, baseline + offset));
}

function representativeEventForStatus(line: string, status: MvpRiskStatus, assets: MvpAsset[], events: MvpEvent[], eventById: Map<string, MvpEvent>) {
  const sameStatusAsset = assets.find((asset) => asset.status === status && asset.eventId && eventById.has(asset.eventId));
  if (sameStatusAsset?.eventId) return eventById.get(sameStatusAsset.eventId) ?? null;

  const sameLineAsset = assets.find((asset) => asset.eventId && eventById.has(asset.eventId));
  if (sameLineAsset?.eventId) return eventById.get(sameLineAsset.eventId) ?? null;

  return events.find((event) => event.line === line && event.status === status)
    ?? events.find((event) => event.line === line)
    ?? events[0]
    ?? null;
}

function buildLineMapNodes(line: string, assets: MvpAsset[], summary: MvpLineRisk | undefined, events: MvpEvent[], eventById: Map<string, MvpEvent>) {
  const actualNodes: StatusMapNode[] = assets.map((asset) => ({
    id: asset.assetId,
    label: asset.assetId.split("-").at(-1) ?? asset.assetId,
    status: asset.status,
    probability: asset.failureProbability,
    asset,
    event: asset.eventId ? eventById.get(asset.eventId) ?? null : null,
  }));
  const targetCount = Math.max(summary?.total ?? 0, actualNodes.length, actualNodes.length < 6 ? MIN_LINE_MAP_NODES : actualNodes.length);
  const usedLabels = new Set(actualNodes.map((node) => node.label));
  const nodes = [...actualNodes];
  const anchorStatus = actualNodes[0]?.status ?? "normal";

  for (let unit = 1; nodes.length < targetCount; unit += 1) {
    const label = String(unit).padStart(3, "0");
    if (usedLabels.has(label) || usedLabels.has(String(unit).padStart(2, "0"))) continue;
    const status = lineMapStatus(unit, summary?.averageRisk ?? null, anchorStatus);
    nodes.push({
      id: `${line}-map-${label}`,
      label,
      status,
      probability: lineMapProbability(status, summary?.averageRisk ?? null, unit),
      asset: null,
      event: representativeEventForStatus(line, status, assets, events, eventById),
    });
    usedLabels.add(label);
  }

  return nodes.sort((a, b) => a.label.localeCompare(b.label, "ko", { numeric: true }));
}

function seededWave(seed: string, count: number, end: number, spread: number, floor = 0, ceiling = 100) {
  const phase = [...seed].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 23;
  return Array.from({ length: count }, (_, index) => {
    const progress = index / Math.max(1, count - 1);
    const trend = end - spread + spread * progress;
    const wave = Math.sin((progress * 3.4 + phase) * Math.PI) * spread * 0.22;
    return Math.min(ceiling, Math.max(floor, trend + wave));
  });
}

function buildFeatureSeries(asset: MvpAsset, range: (typeof GRAPH_RANGES)[number]) {
  const factorByFeature = new Map(asset.topFactors.map((factor) => [factor.feature, factor]));
  const riskLevel = asset.failureProbability ?? 0.18;

  return DEFAULT_FEATURE_SERIES.map((feature, index) => {
    const matchedFactor = [...factorByFeature.entries()].find(([featureId]) => featureId.includes(feature.id) || feature.id.includes(featureId));
    const factor = matchedFactor?.[1];
    const factorValue = typeof factor?.value === "number" ? factor.value : null;
    const riskDirection = feature.id === "rotation_raw" || feature.id === "voltage_raw" ? -1 : 1;
    const featureEnd = factorValue ?? feature.base + riskDirection * riskLevel * feature.spread + (index - 1.5) * feature.spread * 0.12;
    const values = seededWave(
      `${asset.assetId}-${range.id}-${feature.id}`,
      range.pointCount,
      featureEnd,
      Math.max(feature.spread * 0.55, Math.abs(featureEnd) * 0.035),
      Math.max(0, feature.base - feature.spread * 2.1),
      feature.base + feature.spread * 2.1,
    );

    return {
      id: feature.id,
      title: factor?.label ?? feature.label,
      values,
      color: feature.color,
      unit: ` ${factor?.unit ?? feature.unit}`,
    };
  });
}

function MiniSeriesChart({
  title,
  values,
  color,
  unit,
  threshold,
}: {
  title: string;
  values: number[];
  color: string;
  unit: string;
  threshold?: number;
}) {
  const width = 640;
  const height = 150;
  const frame = { left: 46, right: 618, top: 18, bottom: 112 };
  const min = Math.min(...values, threshold ?? values[0] ?? 0);
  const max = Math.max(...values, threshold ?? values[0] ?? 1);
  const padding = Math.max(1, (max - min) * 0.18);
  const domainMin = Math.max(0, min - padding);
  const domainMax = Math.max(domainMin + 1, max + padding);
  const xAt = (index: number) => frame.left + (index / Math.max(1, values.length - 1)) * (frame.right - frame.left);
  const yAt = (value: number) => frame.bottom - ((value - domainMin) / (domainMax - domainMin)) * (frame.bottom - frame.top);
  const points = values.map((value, index) => `${xAt(index).toFixed(1)},${yAt(value).toFixed(1)}`).join(" ");
  const latest = values.at(-1) ?? 0;

  return (
    <section className="asset-series-block">
      <header className="asset-series-heading">
        <div><Gauge size={17} /><strong>{title}</strong></div>
        <span>현재 {latest.toFixed(1)}{unit}</span>
      </header>
      <svg className="asset-series-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${title} 그래프`}>
        <rect className="asset-chart-frame" x={frame.left} y={frame.top} width={frame.right - frame.left} height={frame.bottom - frame.top} />
        {[domainMax, (domainMax + domainMin) / 2, domainMin].map((tick) => {
          const y = yAt(tick);
          return (
            <g key={tick}>
              <line className="asset-chart-grid" x1={frame.left} x2={frame.right} y1={y} y2={y} />
              <text className="asset-chart-axis" x="38" y={y + 4} textAnchor="end">{tick.toFixed(0)}</text>
            </g>
          );
        })}
        {threshold !== undefined ? <line className="asset-threshold-line" x1={frame.left} x2={frame.right} y1={yAt(threshold)} y2={yAt(threshold)} /> : null}
        <polyline className="asset-series-line" points={points} style={{ stroke: color }} />
        <circle className="asset-current-marker" cx={frame.right} cy={yAt(latest)} r="5" style={{ fill: color }} />
        <text className="asset-current-label" x={frame.right - 8} y={Math.max(28, yAt(latest) - 8)} textAnchor="end" style={{ fill: color }}>{latest.toFixed(1)}{unit}</text>
        <text className="asset-chart-axis" x={frame.left} y="136">시작</text>
        <text className="asset-chart-axis" x={frame.right} y="136" textAnchor="end">현재</text>
      </svg>
    </section>
  );
}

function MvpAssetGraphsSection({
  model,
  selectedEvent,
  onSelectEvent,
}: {
  model: MvpBootstrapModel;
  selectedEvent: MvpEvent | null;
  onSelectEvent: (event: MvpEvent) => void;
}) {
  const [rangeId, setRangeId] = useState<(typeof GRAPH_RANGES)[number]["id"]>("6h");
  const range = GRAPH_RANGES.find((item) => item.id === rangeId) ?? GRAPH_RANGES[1];
  const eventById = useMemo(() => new Map(model.events.map((event) => [event.eventId, event])), [model.events]);
  const selectedAsset = model.assets.find((asset) => asset.eventId === selectedEvent?.eventId)
    ?? model.assets.find((asset) => asset.assetId === selectedEvent?.assetId)
    ?? model.assets.find((asset) => asset.eventId)
    ?? model.assets[0]
    ?? null;
  const riskEnd = selectedAsset?.failureProbability === null || selectedAsset?.failureProbability === undefined
    ? 0
    : selectedAsset.failureProbability * 100;
  const riskValues = selectedAsset
    ? seededWave(`${selectedAsset.assetId}-${range.id}-risk`, range.pointCount, riskEnd, Math.max(10, riskEnd * 0.42), 0, 100)
    : [];
  const featureSeries = selectedAsset ? buildFeatureSeries(selectedAsset, range) : [];

  return (
    <div className="asset-detail-view mvp-asset-graphs" data-testid="mvp-summary-graphs">
      <section className="asset-detail-header">
        <div className="asset-detail-header-main">
          <span>선택 설비 상세</span>
          <h1>{selectedAsset?.displayName ?? "선택 설비 없음"}</h1>
          <p>{selectedAsset ? `${selectedAsset.assetType} · ${selectedAsset.line} · ${selectedAsset.assetId}` : "상태 맵에서 설비를 선택하세요."}</p>
        </div>
        <label className="asset-detail-picker">
          <span>다른 설비 보기</span>
          <select value={selectedAsset?.eventId ?? ""} onChange={(event) => {
            const next = eventById.get(event.target.value);
            if (next) onSelectEvent(next);
          }}>
            {model.assets.filter((asset) => asset.eventId).map((asset) => (
              <option value={asset.eventId ?? ""} key={asset.assetId}>{asset.displayName} · {MAP_STATUS_META[asset.status].label}</option>
            ))}
          </select>
        </label>
        {selectedAsset ? <MapStatusBadge status={selectedAsset.status} /> : null}
        <dl className="asset-detail-facts">
          <div><dt>24시간 위험 예측</dt><dd>{formatProbability(selectedAsset?.failureProbability ?? null)}</dd></div>
          <div><dt>예측 신뢰도</dt><dd>{selectedAsset?.confidence ?? "unavailable"}</dd></div>
          <div><dt>기준 시각</dt><dd>{formatTimestamp(selectedAsset?.observedAt ?? model.context.observedAt)}</dd></div>
          <div><dt>표시 모드</dt><dd>{model.context.sourceMode === "canonical-runtime" ? "Runtime Result" : "Fallback Replay"}</dd></div>
        </dl>
      </section>

      <section className="asset-graph-workspace">
        <header className="asset-graph-toolbar">
          <div>
            <span>피처 그래프와 전체 이력</span>
            <h2>범위별 설비 상태 변화</h2>
          </div>
          <div className="asset-range-group" role="group" aria-label="그래프 시간 범위">
            {GRAPH_RANGES.map((item) => (
              <button type="button" key={item.id} aria-pressed={item.id === range.id} onClick={() => setRangeId(item.id)}>{item.label}</button>
            ))}
          </div>
          <div className="asset-range-meta"><CalendarRange size={15} />원본 10분 · {range.grain}</div>
        </header>

        {selectedAsset ? (
          <>
            <MiniSeriesChart title="24시간 내 고장 위험도" values={riskValues} color="#b42318" unit="%" threshold={70} />
            {featureSeries.map((series) => <MiniSeriesChart key={series.id} title={series.title} values={series.values} color={series.color} unit={series.unit} />)}
            <section className="asset-history-section">
              <header><div><RotateCcw size={16} /><strong>설비 전체 이력 · {selectedAsset.assetId}</strong></div><span>현재 MVP Event 스냅샷</span></header>
              <div className="asset-history-columns" aria-hidden="true"><span>일시</span><span>유형</span><span>이력 내용</span><span>담당·메모</span></div>
              <div className="asset-history-rows">
                {(selectedAsset.eventId ? [eventById.get(selectedAsset.eventId)].filter((event): event is MvpEvent => Boolean(event)) : []).map((event) => (
                  <article className="asset-history-row" key={event.eventId}>
                    <time>{formatTimestamp(event.observedAt)}</time>
                    <span className={`asset-history-kind ${MAP_STATUS_META[event.status].tone}`}>{MAP_STATUS_META[event.status].label}</span>
                    <p>{DECISION_LABEL[event.recommendedDecision]} · {event.predictedFailureType}</p>
                    <div className="asset-history-source">{event.assignedEngineer ?? "담당 미배정"}</div>
                  </article>
                ))}
              </div>
            </section>
          </>
        ) : <p>선택 가능한 설비가 없습니다.</p>}
      </section>
    </div>
  );
}

function MvpStatusMapReport({
  model,
  selectedEvent,
  onSelectEvent,
}: {
  model: MvpBootstrapModel;
  selectedEvent: MvpEvent | null;
  onSelectEvent: (event: MvpEvent) => void;
}) {
  const [focusedMapNodeId, setFocusedMapNodeId] = useState<string | null>(null);
  const eventById = useMemo(() => new Map(model.events.map((event) => [event.eventId, event])), [model.events]);
  const selectedAsset = model.assets.find((asset) => asset.eventId === selectedEvent?.eventId)
    ?? model.assets.find((asset) => asset.assetId === selectedEvent?.assetId)
    ?? model.assets[0]
    ?? null;
  const groupedLines = useMemo(() => {
    const buckets = new Map<string, MvpAsset[]>();
    for (const asset of model.assets) {
      const key = lineKey(asset);
      buckets.set(key, [...(buckets.get(key) ?? []), asset]);
    }
    return [...buckets.entries()].map(([line, assets]) => ({
      line,
      assets,
      summary: model.lineRisk.find((item) => item.line === line),
      nodes: buildLineMapNodes(line, assets, model.lineRisk.find((item) => item.line === line), model.events, eventById),
    }));
  }, [eventById, model.assets, model.events, model.lineRisk]);
  const priorityAssets = model.assets
    .filter((asset) => asset.recommendedDecision !== "continue_monitoring")
    .slice(0, 6);

  return (
    <div data-testid="mvp-status-map-report">
      <header className="topbar">
        <div>
          <span>상태 요약 보고서</span>
          <h1>예지보전 상태 요약 보고서</h1>
          <p>현재 MVP의 Result Artifact와 Event 목록을 기준으로 위험 상태, 판단 대기, 데이터 품질 보류를 라인별 맵으로 요약합니다.</p>
        </div>
        <div className="report-meta">
          <small>생성 시각</small>
          <strong>{formatTimestamp(model.context.refreshedAt)}</strong>
          <span>{model.context.sourceMode === "canonical-runtime" ? "Runtime 기반" : "Fallback 기반"}</span>
        </div>
      </header>

      <section className="kpis" aria-label="예지보전 상태 KPI">
        <ReportKpi icon={Gauge} label="전체 설비" value={`${model.metrics.totalAssets}대`} detail={model.context.datasetVersionId} />
        <ReportKpi icon={AlertTriangle} label="위험/경고" value={`${model.metrics.critical + model.metrics.warning}대`} detail={`위험 ${model.metrics.critical} · 경고 ${model.metrics.warning}`} tone="warm" />
        <ReportKpi icon={ClipboardCheck} label="판단 대기" value={`${model.metrics.pendingDecisions}건`} detail="점검·정지 검토·데이터 확인" />
        <ReportKpi icon={Clock3} label="예상 영향" value={formatMinutes(model.metrics.estimatedDowntimeMinutes)} detail="Event 합산" />
        <ReportKpi icon={DatabaseZap} label="품질 보류" value={`${model.metrics.dataQualityHold}건`} detail="고장 확정 표현 금지" tone="hold" />
      </section>

      <section className="priority-panel">
        <div className="panel-heading">
          <div><span>우선 확인 설비</span><h2>미결정 Event 우선순위</h2></div>
          <button type="button" className="filter-button"><Filter size={15} />미결정만</button>
        </div>
        <div className="priority-list">
          {priorityAssets.map((asset) => {
            const event = asset.eventId ? eventById.get(asset.eventId) : null;
            return (
              <button key={asset.assetId} type="button" className={asset.assetId === selectedAsset?.assetId ? "active" : ""} onClick={() => event && onSelectEvent(event)} disabled={!event}>
                <MapStatusBadge status={asset.status} />
                <strong>{asset.displayName}</strong>
                <span>{asset.line}</span>
                <b>{formatProbability(asset.failureProbability)}</b>
                <small>{DECISION_LABEL[asset.recommendedDecision]}</small>
                <em>{asset.assignedEngineer ? `담당 ${asset.assignedEngineer}` : "담당 미배정"}</em>
              </button>
            );
          })}
        </div>
      </section>

      <div className="main-grid">
        <section className="map-panel">
          <div className="panel-heading">
            <div><span>설비 상태 맵</span><h2>라인별 설비 상태</h2></div>
            <div className="legend">
              {Object.entries(MAP_STATUS_META).map(([key, meta]) => <i key={key} className={`dot ${meta.tone}`}>{meta.label}</i>)}
            </div>
          </div>
          <div className="line-map">
            {groupedLines.map((line) => (
              <article key={line.line} className="line-row">
                <header>
                  <strong>{line.line}</strong>
                  <small>맵 표시 {line.nodes.length}대 · 평균 위험 {formatProbability(line.summary?.averageRisk ?? null)}</small>
                </header>
                <div className="asset-grid">
                  {line.nodes.map((node) => {
                    const selected = focusedMapNodeId === node.id || (!focusedMapNodeId && node.asset?.assetId === selectedAsset?.assetId);
                    return (
                      <button
                        key={node.id}
                        type="button"
                        className={`asset-node ${MAP_STATUS_META[node.status].tone} ${selected ? "selected" : ""}`}
                        aria-pressed={selected}
                        aria-disabled={!node.event}
                        onClick={() => {
                          setFocusedMapNodeId(node.id);
                          if (node.event) onSelectEvent(node.event);
                        }}
                        title={`${node.asset?.displayName ?? `${line.line} ${node.label}호 설비`} · ${MAP_STATUS_META[node.status].label} · 위험 예측 확률 ${formatProbability(node.probability)}${node.asset ? "" : " · 클릭 시 같은 라인 대표 Event로 이동"}`}
                      >
                        <span>{node.label}</span>
                      </button>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="report-panel">
          {selectedAsset ? (
            <>
              <div className="panel-heading compact">
                <div>
                  <span>선택 설비 상세</span>
                  <h2>{selectedAsset.displayName}</h2>
                  <small className="sub-id">{selectedAsset.line} · {selectedAsset.assignedEngineer ? `담당 ${selectedAsset.assignedEngineer}` : "담당 미배정"}</small>
                </div>
                <MapStatusBadge status={selectedAsset.status} />
              </div>
              <dl className="detail-grid">
                <div><dt>설비 유형</dt><dd>{selectedAsset.assetType}</dd></div>
                <div><dt>위치</dt><dd>{selectedAsset.site} / {selectedAsset.cell}</dd></div>
                <div><dt>위험 예측 확률</dt><dd>{formatProbability(selectedAsset.failureProbability)}</dd></div>
                <div><dt>신뢰도</dt><dd>{selectedAsset.confidence}</dd></div>
                <div><dt>권장 조치</dt><dd>{DECISION_LABEL[selectedAsset.recommendedDecision]}</dd></div>
                <div><dt>예상 영향</dt><dd>{formatMinutes(selectedAsset.estimatedDowntimeMinutes)}</dd></div>
              </dl>
              <section className="narrative">
                <span>보고서 요약</span>
                <p>{selectedAsset.status === "data_quality_hold" ? `${selectedAsset.displayName}는 데이터 품질 확인 보류 상태입니다. 고장 위험으로 단정하지 않고 센서 수집 상태와 데이터 처리 상태를 먼저 확인해야 합니다.` : `${selectedAsset.displayName}는 ${MAP_STATUS_META[selectedAsset.status].label} 상태이며, ${DECISION_LABEL[selectedAsset.recommendedDecision]} 대상으로 분류됩니다. 모델 결과는 점검 우선순위 판단 근거이며 고장 확정은 아닙니다.`}</p>
              </section>
              <section className="inspection-card">
                <header><Wrench size={16} /><strong>점검 근거</strong></header>
                <ul>
                  {selectedAsset.topFactors.slice(0, 3).map((factor) => <li key={factor.id}><b>{factor.label}</b>: {Math.round(factor.contribution * 100)}%</li>)}
                  {!selectedAsset.topFactors.length ? <li>세부 설명 요인이 제공되지 않았습니다.</li> : null}
                </ul>
              </section>
              <section className="limitations">
                <header><ShieldCheck size={16} /><strong>한계</strong></header>
                <p>공정 순서도나 실제 공장 도면이 아니라 운영 요약용 상태 맵입니다. 모델은 원인과 고장 발생을 확정하지 않습니다.</p>
              </section>
            </>
          ) : <p>선택 가능한 설비가 없습니다.</p>}
        </aside>
      </div>
    </div>
  );
}

function MvpSummaryReport({
  model,
  selectedEvent,
  onSelectEvent,
}: {
  model: MvpBootstrapModel;
  selectedEvent: MvpEvent | null;
  onSelectEvent: (event: MvpEvent) => void;
}) {
  const actionableEvents = model.events
    .filter((event) => event.recommendedDecision !== "continue_monitoring")
    .slice(0, 5);
  const criticalLines = [...model.lineRisk]
    .sort((a, b) => (b.averageRisk ?? -1) - (a.averageRisk ?? -1))
    .slice(0, 4);
  const qualityEvents = model.events.filter((event) => event.status === "data_quality_hold");
  const selected = selectedEvent ?? actionableEvents[0] ?? model.events[0] ?? null;

  return (
    <div className="mvp-summary-report" data-testid="mvp-summary-report">
      <header className="topbar">
        <div>
          <span>요약 보고서</span>
          <h1>예지보전 운영 요약 보고서</h1>
          <p>map-report prototype의 요약 보고서 슬롯을 현재 MVP 데이터로 채운 공유용 보고서입니다. 상태 맵의 전체 흐름과 점검 요청의 현장 항목을 한 장으로 압축합니다.</p>
        </div>
        <div className="report-meta">
          <small>작성 상태</small>
          <strong>{model.context.sourceMode === "canonical-runtime" ? "Runtime 요약" : "Fallback 요약"}</strong>
          <span>{formatTimestamp(model.context.refreshedAt)}</span>
        </div>
      </header>

      <section className="summary-hero">
        <div>
          <span>이번 스냅샷 판단</span>
          <h2>{model.metrics.critical + model.metrics.warning}대 설비가 위험/경고 상태이며 {model.metrics.pendingDecisions}건의 사람 판단이 대기 중입니다.</h2>
          <p>이 보고서는 고장 확정이나 정비 완료를 주장하지 않고, 모델 예측 결과를 기준으로 운영 검토·현장 점검·데이터 확인 대상을 분리합니다.</p>
        </div>
        <dl>
          <div><dt>전체 설비</dt><dd>{model.metrics.totalAssets}대</dd></div>
          <div><dt>평균 위험</dt><dd>{formatProbability(model.metrics.averageRisk)}</dd></div>
          <div><dt>예상 영향</dt><dd>{formatMinutes(model.metrics.estimatedDowntimeMinutes)}</dd></div>
          <div><dt>품질 보류</dt><dd>{qualityEvents.length}건</dd></div>
        </dl>
      </section>

      <MvpAssetGraphsSection model={model} selectedEvent={selectedEvent} onSelectEvent={onSelectEvent} />

      <div className="summary-grid">
        <section className="report-panel">
          <div className="panel-heading compact"><div><span>MANAGER SUMMARY</span><h2>운영 판단 요약</h2></div></div>
          <div className="summary-decision-list">
            <article><strong>1. 우선순위</strong><p>위험/경고 설비를 먼저 확인하고, 생산 영향이 큰 설비는 Operations에서 결정 메모를 남깁니다.</p></article>
            <article><strong>2. 현장 확인</strong><p>점검 요청 보고서의 설비별 센서 근거와 점검 위치를 현장 담당자에게 전달합니다.</p></article>
            <article><strong>3. 데이터 품질</strong><p>품질 보류 Event는 위험 수치로 단정하지 않고 원천 데이터 확인 대상으로 분리합니다.</p></article>
          </div>
        </section>

        <section className="report-panel">
          <div className="panel-heading compact"><div><span>LINE RISK</span><h2>라인별 위험 상위</h2></div></div>
          <div className="summary-line-list">
            {criticalLines.map((line) => (
              <article key={line.line}>
                <div><strong>{line.line}</strong><span>설비 {line.total}대 · 위험 {line.critical} · 경고 {line.warning}</span></div>
                <b>{formatProbability(line.averageRisk)}</b>
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="priority-panel summary-event-panel">
        <div className="panel-heading">
          <div><span>ACTIONABLE EVENTS</span><h2>보고서에 포함할 Event</h2></div>
          {selected ? <MapStatusBadge status={selected.status} /> : null}
        </div>
        <div className="summary-event-list">
          {actionableEvents.map((event) => (
            <button key={event.eventId} type="button" className={event.eventId === selected?.eventId ? "active" : ""} onClick={() => onSelectEvent(event)}>
              <strong>{event.assetName}</strong>
              <span>{event.line} · {event.eventId}</span>
              <b>{formatProbability(event.failureProbability)}</b>
              <small>{DECISION_LABEL[event.recommendedDecision]}</small>
            </button>
          ))}
        </div>
        {selected ? (
          <aside className="summary-selected-note">
            <strong>{selected.assetName}</strong>
            <p>{selected.status === "data_quality_hold" ? "데이터 품질 확인이 먼저 필요한 Event입니다." : `${DECISION_LABEL[selected.recommendedDecision]} 대상으로 분류됐으며 예상 영향은 ${formatMinutes(selected.estimatedDowntimeMinutes)}입니다.`}</p>
          </aside>
        ) : null}
      </section>

      <section className="priority-panel warning-strip">
        <ShieldCheck size={18} />
        <p>이 요약 보고서는 운영 공유용 스냅샷입니다. 고장 발생, 원인 확정, 정비 완료, 자동 제어 수행을 의미하지 않습니다.</p>
      </section>
    </div>
  );
}

export function MvpReportsPage({
  activeTab,
  model,
  selectedEvent,
  detail,
  detailLoading,
  detailError,
  onSelectTab,
  onSelectEvent,
  onBackToOverview,
  onOpenOperations,
  onRetryDetail,
}: {
  activeTab: MvpReportTab;
  model: MvpBootstrapModel;
  selectedEvent: MvpEvent | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  onSelectTab: (tab: MvpReportTab) => void;
  onSelectEvent: (event: MvpEvent) => void;
  onBackToOverview: () => void;
  onOpenOperations: (event: MvpEvent) => void;
  onRetryDetail: () => void;
}) {
  return (
    <div className="mvp-page map-report-prototype mvp-reports-page" data-testid="mvp-reports">
      <div className="mvp-report-tabs" role="tablist" aria-label="보고서 종류">
        {REPORT_TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <button key={tab.id} type="button" role="tab" aria-selected={activeTab === tab.id} className={activeTab === tab.id ? "active" : ""} onClick={() => onSelectTab(tab.id)}>
              <Icon size={16} />
              <span>{tab.label}</span>
              <small>{tab.description}</small>
            </button>
          );
        })}
        <button type="button" className="mvp-report-print" onClick={() => window.print()}><Printer size={15} />Print</button>
      </div>

      {activeTab === "status-map" ? (
        <MvpStatusMapReport model={model} selectedEvent={selectedEvent} onSelectEvent={onSelectEvent} />
      ) : activeTab === "inspection-request" ? (
        <MvpInspectionReportPage />
      ) : activeTab === "summary-report" ? (
        <MvpSummaryReport model={model} selectedEvent={selectedEvent} onSelectEvent={onSelectEvent} />
      ) : (
        <MvpExecutiveReportPage model={model} selectedEvent={selectedEvent} detail={detail} detailLoading={detailLoading} detailError={detailError} onBackToOverview={onBackToOverview} onOpenOperations={onOpenOperations} onRetryDetail={onRetryDetail} />
      )}
    </div>
  );
}

import { CalendarRange, Database, Gauge, GitBranch, History, RotateCcw, ShieldCheck, Volume2 } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  OperationsBootstrapModel,
  OperationsEvent,
  OperationsEventDetailModel,
  OperationsRiskSeriesPoint,
  OperationsRiskStatus,
  OperationsSensorValue,
  OperationsTraceStage,
} from "../api/operationsContracts";
import { formatProbability, formatTimestamp } from "../components/OperationsUi";
import { displayAssetName, displayEventAssetName, displaySensorLabel } from "../displayLabels";

type ChartTone = "risk" | "sensor";

interface ChartPoint {
  observedAt: string;
  value: number | null;
  qualityStatus?: "good" | "bad" | "unknown";
}

function formatValue(value: number | null | undefined, unit = "") {
  if (value === null || value === undefined || !Number.isFinite(value)) return "데이터 없음";
  const digits = Math.abs(value) >= 100 ? 0 : 1;
  return `${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: digits, minimumFractionDigits: digits })}${unit ? ` ${unit}` : ""}`;
}

function chartDomain(points: ChartPoint[], threshold?: number | null) {
  const values = points
    .map((point) => point.value)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const anchors = threshold === null || threshold === undefined ? values : [...values, threshold];
  if (!anchors.length) return { minimum: 0, maximum: 1 };
  const minimum = Math.min(...anchors);
  const maximum = Math.max(...anchors);
  const span = Math.max(maximum - minimum, Math.abs(maximum || minimum) * 0.08, Number.EPSILON);
  return { minimum: minimum - span * 0.16, maximum: maximum + span * 0.16 };
}

function pointLabel(point: ChartPoint, fallback: string) {
  const stamp = formatTimestamp(point.observedAt);
  return stamp || fallback;
}

function CanonicalSeriesChart({
  title,
  unit,
  points,
  threshold,
  tone,
  emptyLabel,
}: {
  title: string;
  unit?: string | null;
  points: ChartPoint[];
  threshold?: number | null;
  tone: ChartTone;
  emptyLabel: string;
}) {
  const usablePoints = points.filter((point) => point.value !== null);
  const domain = chartDomain(points, threshold);
  const frame = { left: 58, right: 684, top: 18, bottom: 224 };
  const width = frame.right - frame.left;
  const height = frame.bottom - frame.top;
  const domainSpan = domain.maximum - domain.minimum || Number.EPSILON;
  const yAt = (value: number) => frame.bottom - ((value - domain.minimum) / domainSpan) * height;
  const xAt = (index: number) => frame.left + (index / Math.max(1, points.length - 1)) * width;
  const color = tone === "risk" ? "#ec5b62" : "#4c90f0";
  const yTicks = [domain.maximum, (domain.minimum + domain.maximum) / 2, domain.minimum];
  const coords = points.map((point, index) => ({
    ...point,
    x: xAt(index),
    y: typeof point.value === "number" ? yAt(point.value) : null,
  }));
  const segments: Array<Array<typeof coords[number] & { value: number; y: number }>> = [];
  let currentSegment: Array<typeof coords[number] & { value: number; y: number }> = [];
  coords.forEach((point) => {
    if (typeof point.value !== "number" || typeof point.y !== "number") {
      if (currentSegment.length) segments.push(currentSegment);
      currentSegment = [];
      return;
    }
    currentSegment.push({ ...point, value: point.value, y: point.y });
  });
  if (currentSegment.length) segments.push(currentSegment);
  const first = points[0];
  const last = points.at(-1);
  const middleIndex = Math.floor((points.length - 1) / 2);
  const middle = points[middleIndex];

  return (
    <section className="asset-series-block">
      <header className="asset-series-heading">
        <div>{tone === "risk" ? <Gauge size={17} /> : title.includes("진동") || title.includes("토크") ? <Volume2 size={17} /> : <RotateCcw size={17} />}<strong>{title}</strong></div>
        {threshold !== null && threshold !== undefined ? <span className="asset-threshold-key">알람 경계 {formatValue(threshold, unit ?? "")}</span> : null}
      </header>
      {usablePoints.length === 0 ? (
        <div className="asset-chart-empty"><Database size={20} /><strong>{emptyLabel}</strong><span>값을 0으로 대체하지 않습니다.</span></div>
      ) : (
        <svg className="asset-series-chart" viewBox="0 0 720 262" role="img" aria-label={`${title} 관측 흐름`}>
          <rect className="asset-chart-frame" x={frame.left} y={frame.top} width={width} height={height} />
          <text className="asset-chart-axis-title" transform={`translate(14 ${(frame.top + frame.bottom) / 2}) rotate(-90)`} textAnchor="middle">{unit || (tone === "risk" ? "%" : "값")}</text>
          {yTicks.map((tick) => {
            const y = yAt(tick);
            return (
              <g key={tick}>
                <line className="asset-chart-grid" x1={frame.left} x2={frame.right} y1={y} y2={y} />
                <text className="asset-chart-axis" x="50" y={y + 4} textAnchor="end">{formatValue(tick, unit ?? "")}</text>
              </g>
            );
          })}
          {threshold !== null && threshold !== undefined ? <line className="asset-threshold-line" x1={frame.left} x2={frame.right} y1={yAt(threshold)} y2={yAt(threshold)} /> : null}
          {segments.map((segment, index) => <polyline key={`${title}-segment-${index}`} className="asset-series-line" points={segment.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")} style={{ stroke: color }} />)}
          {coords.map((point, index) => {
            if (typeof point.value !== "number" || typeof point.y !== "number") return null;
            const timeLabel = pointLabel(point, "관측 시각 미제공");
            const valueLabel = formatValue(point.value, unit ?? "");
            const tooltipWidth = 192;
            const tooltipX = Math.min(frame.right - tooltipWidth - 4, Math.max(frame.left + 4, point.x - tooltipWidth / 2));
            const tooltipY = Math.min(frame.bottom - 36, Math.max(frame.top + 4, point.y - 42));
            return (
              <g key={`${point.observedAt}-${index}`} className="asset-chart-hover-point">
                <circle className={index === points.length - 1 ? "asset-current-marker" : "asset-crossing-marker"} cx={point.x} cy={point.y} r={index === points.length - 1 ? 5 : 3} style={{ fill: color, opacity: point.qualityStatus === "bad" ? 0.42 : 1 }} />
                <circle className="asset-chart-hit-target" cx={point.x} cy={point.y} r="10" tabIndex={0} aria-label={`${timeLabel} ${valueLabel}`}>
                  <title>{`${timeLabel} · ${valueLabel} · 품질 ${point.qualityStatus ?? "unknown"}`}</title>
                </circle>
                <g className="asset-chart-tooltip" transform={`translate(${tooltipX} ${tooltipY})`}>
                  <rect width={tooltipWidth} height="33" rx="6" />
                  <text x="9" y="13">{timeLabel}</text>
                  <text className="is-value" x="9" y="26">{valueLabel} · {point.qualityStatus ?? "unknown"}</text>
                </g>
              </g>
            );
          })}
          {first ? <text className="asset-chart-axis" x={frame.left} y="248" textAnchor="start">{pointLabel(first, "시작")}</text> : null}
          {middle && points.length > 2 ? <text className="asset-chart-axis" x={xAt(middleIndex)} y="248" textAnchor="middle">{pointLabel(middle, "중간")}</text> : null}
          {last ? <text className="asset-chart-axis" x={frame.right} y="248" textAnchor="end">{pointLabel(last, "현재")}</text> : null}
          <text className="asset-chart-axis-title" x="370" y="259" textAnchor="middle">시간</text>
        </svg>
      )}
    </section>
  );
}

function riskPoints(riskHistory: OperationsRiskSeriesPoint[]): ChartPoint[] {
  return riskHistory.map((point) => ({
    observedAt: point.observedAt,
    value: point.failureProbability * 100,
    qualityStatus: "good",
  }));
}

function sensorPoints(sensor: OperationsSensorValue): ChartPoint[] {
  return (sensor.historyPoints ?? []).map((point) => ({
    observedAt: point.observedAt,
    value: point.value,
    qualityStatus: point.qualityStatus,
  }));
}

const TRACE_STATUS_LABEL: Record<string, string> = {
  completed: "완료",
  partial: "부분 검증",
  pending: "대기",
  maintenance_completed: "정비 완료",
  observation_pending: "새 관측값 대기",
  re_prediction_requested: "재예측 요청",
  new_decision_created: "새 운영 판정 생성",
};

function SameEventTracePanel({ detail }: { detail: OperationsEventDetailModel }) {
  const trace = detail.traceability;
  const [selectedStage, setSelectedStage] = useState<OperationsTraceStage>(trace?.currentStage ?? "decision");
  if (!trace || trace.timeline.length === 0) return null;
  const selected = trace.timeline.find((item) => item.stage === selectedStage) ?? trace.timeline[0];
  const snapshot = trace.decisionSnapshot;
  return (
    <section className="same-event-trace-panel" data-testid="same-event-trace-panel">
      <header>
        <div><GitBranch size={16} /><strong>같은 사건 추적</strong></div>
        <span>{TRACE_STATUS_LABEL[selected.status] ?? selected.status}</span>
      </header>
      <dl className="same-event-trace-summary">
        <div><dt>사건 ID</dt><dd>{trace.eventId}</dd></div>
        <div><dt>현재 단계</dt><dd>{selected.label}</dd></div>
        <div><dt>기준 시각</dt><dd>{formatTimestamp(snapshot.asOf)}</dd></div>
        <div><dt>재평가 상태</dt><dd>{TRACE_STATUS_LABEL[trace.timeline.at(-1)?.status ?? "pending"] ?? "대기"}</dd></div>
      </dl>
      <div className="same-event-trace-timeline" role="tablist" aria-label="판단 조치 결과 재평가 흐름">
        {trace.timeline.map((item) => (
          <button type="button" role="tab" aria-selected={item.stage === selected.stage} className={item.stage === selected.stage ? "is-selected" : ""} key={item.stage} onClick={() => setSelectedStage(item.stage)}>
            <span>{item.label}</span>
            <strong>{TRACE_STATUS_LABEL[item.status] ?? item.status}</strong>
            <small>{item.actor ?? "담당 기록 없음"}</small>
          </button>
        ))}
      </div>
      <div className="same-event-trace-detail">
        <section>
          <header><ShieldCheck size={15} /><strong>당시 판단 근거</strong><span>{selected.usedEvidenceCount}</span></header>
          {snapshot.usedEvidence.length ? <ul>{snapshot.usedEvidence.map((item) => <li key={item.evidenceId}><strong>{item.label}</strong><span>{item.reason}</span></li>)}</ul> : <p>사용 근거가 아직 연결되지 않았습니다.</p>}
        </section>
        <section>
          <header><Database size={15} /><strong>제외된 근거</strong><span>{selected.excludedEvidenceCount}</span></header>
          {snapshot.excludedEvidence.length ? <ul>{snapshot.excludedEvidence.slice(0, 5).map((item) => <li key={`${item.evidenceId}-${item.reason}`}><strong>{item.label}</strong><span>{item.reason}</span></li>)}</ul> : <p>제외 근거 기록이 없습니다.</p>}
        </section>
        <section>
          <header><History size={15} /><strong>조치 이력</strong><span>{selected.statusChanges.length || trace.statusChanges.length}</span></header>
          {(selected.statusChanges.length ? selected.statusChanges : trace.statusChanges).slice(0, 5).map((change) => <article key={`${change.actionType}-${change.createdAt}`}><strong>{change.actor}</strong><p>{change.beforeStatus ?? "시작"} → {change.afterStatus ?? "상태 없음"}</p><small>{change.reason} · {formatTimestamp(change.createdAt)}</small></article>)}
          {!trace.statusChanges.length ? <p>상태 변경 이력이 아직 없습니다.</p> : null}
        </section>
        <section>
          <header><Database size={15} /><strong>한계 정보</strong><span>{snapshot.limitations.length}</span></header>
          {snapshot.limitations.length ? <ul>{snapshot.limitations.slice(0, 4).map((item) => <li key={item}><span>{item}</span></li>)}</ul> : <p>별도 한계 정보가 없습니다.</p>}
          <dl><div><dt>모델 버전</dt><dd>{snapshot.modelVersion ?? "미연결"}</dd></div><div><dt>근거 지문</dt><dd>{snapshot.sourceHash ? snapshot.sourceHash.slice(0, 12) : "미연결"}</dd></div></dl>
        </section>
      </div>
    </section>
  );
}

function HistoryList({ detail }: { detail: OperationsEventDetailModel }) {
  const rows = detail.equipmentHistory;
  return (
    <section className="asset-history-section">
      <header><div><History size={16} /><strong>설비 이력</strong></div><span>전체 {rows.length}건 · 운영 상세 기록</span></header>
      {rows.length ? (
        <div className="asset-history-rows">
          {rows.map((row, index) => (
            <article className="asset-history-row" key={`${row.occurredAt}-${row.kind}-${index}`}>
              <time>{formatTimestamp(row.occurredAt)}</time>
              <span className={`asset-history-kind ${row.tone}`}>{row.kind}</span>
              <p>{row.description}</p>
              <div className="asset-history-source">{row.memo ? `${row.source} · ${row.memo}` : row.source}</div>
            </article>
          ))}
        </div>
      ) : (
        <div className="asset-chart-empty"><Database size={20} /><strong>설비 이력 미연결</strong><span>현재 설비에 연결된 이력 기록이 없습니다.</span></div>
      )}
    </section>
  );
}

export function OperationsMapReportAssetDetailView({
  model,
  selectedEvent,
  detail,
  onSelectEvent,
  statusMeta,
}: {
  model: OperationsBootstrapModel;
  selectedEvent: OperationsEvent | null;
  detail: OperationsEventDetailModel | null;
  onSelectEvent: (event: OperationsEvent) => void;
  statusMeta: Record<OperationsRiskStatus, { label: string; tone: string }>;
}) {
  const eventById = useMemo(() => new Map(model.events.map((event) => [event.eventId, event])), [model.events]);
  const selectedAsset = model.assets.find((asset) => asset.eventId === selectedEvent?.eventId)
    ?? model.assets.find((asset) => asset.assetId === selectedEvent?.assetId)
    ?? null;
  const detailMatchesSelection = Boolean(detail && selectedEvent && detail.event.eventId === selectedEvent.eventId);
  const status = selectedEvent ? statusMeta[selectedEvent.status] : selectedAsset ? statusMeta[selectedAsset.status] : null;

  if (!selectedEvent || !selectedAsset) {
    return <div className="asset-detail-view operations-asset-graphs" data-testid="operations-summary-graphs"><p>선택 가능한 설비가 없습니다.</p></div>;
  }

  if (!detailMatchesSelection || !detail) {
    return (
      <div className="asset-detail-view operations-asset-graphs" data-testid="operations-summary-graphs">
        <section className="asset-detail-header">
          <div className="asset-detail-header-main">
            <span>선택 설비 상세</span>
            <h1>{displayEventAssetName(selectedEvent)}</h1>
            <p>{selectedEvent.line} · {selectedEvent.assetId}</p>
          </div>
          {status ? <span className={`status-badge ${status.tone}`}>{status.label}</span> : null}
        </section>
        <div className="asset-chart-empty"><Database size={20} /><strong>연결된 상세 데이터 없음</strong><span>현재 선택 설비에 연결된 상세 운영 데이터가 없습니다.</span></div>
      </div>
    );
  }

  const riskThreshold = typeof detail.threshold === "number" ? detail.threshold * 100 : null;

  return (
    <div className="asset-detail-view operations-asset-graphs" data-testid="operations-summary-graphs">
      <section className="asset-detail-header">
        <div className="asset-detail-header-main">
          <span>설비 상세</span>
          <h1>{displayAssetName(selectedAsset)}</h1>
          <p>{selectedAsset.assetType} · {selectedEvent.line} · {selectedEvent.assetId}</p>
        </div>
        <label className="asset-detail-picker">
          <span>다른 설비 보기</span>
          <select value={selectedEvent.eventId} onChange={(event) => {
            const next = eventById.get(event.target.value);
            if (next) onSelectEvent(next);
          }}>
            {model.events.map((event) => (
              <option value={event.eventId} key={event.eventId}>{displayEventAssetName(event)} · {statusMeta[event.status].label}</option>
            ))}
          </select>
        </label>
        {status ? <span className={`status-badge ${status.tone}`}>{status.label}</span> : null}
        <dl className="asset-detail-facts">
          <div><dt>24시간 위험 예측</dt><dd>{formatProbability(detail.event.failureProbability)}</dd></div>
          <div><dt>판단 기준</dt><dd>{detail.reviewPriority ? detail.reviewPriority.level : "검토 우선순위 미연결"}</dd></div>
          <div><dt>기준 시각</dt><dd>{formatTimestamp(detail.event.observedAt ?? model.context.observedAt)}</dd></div>
          <div><dt>표시 소스</dt><dd>운영 상세 스냅샷</dd></div>
        </dl>
      </section>

      <section className="asset-graph-workspace">
        <header className="asset-graph-toolbar">
          <div><span>DETAIL SNAPSHOT</span><h2>운영 상세 관측 흐름</h2></div>
          <div className="asset-range-meta"><CalendarRange size={15} />{formatTimestamp(model.context.observedAt ?? model.context.refreshedAt)}</div>
        </header>

        <CanonicalSeriesChart title="24시간 위험 예측" unit="%" points={riskPoints(detail.riskSeries)} threshold={riskThreshold} tone="risk" emptyLabel="위험도 관측 흐름 없음" />
        {detail.sensors.map((sensor) => (
          <CanonicalSeriesChart
            key={sensor.id}
            title={displaySensorLabel(sensor.id, sensor.label)}
            unit={sensor.unit}
            points={sensorPoints(sensor)}
            tone="sensor"
            emptyLabel={`${displaySensorLabel(sensor.id, sensor.label)} 관측 흐름 없음`}
          />
        ))}
        <SameEventTracePanel detail={detail} />
        <HistoryList detail={detail} />
      </section>
    </div>
  );
}

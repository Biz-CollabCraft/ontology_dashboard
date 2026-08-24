import {
  ArrowRight,
  BarChart3,
  Boxes,
  ClipboardCheck,
  ClipboardList,
  FileText,
  RefreshCw,
} from "lucide-react";
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

function partLabel(value: boolean | null): string {
  if (value === true) return "확보";
  if (value === false) return "미확보";
  return "확인 필요";
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
  const maxContribution = Math.max(0.01, ...selectedFactors.map((factor) => Math.abs(factor.contribution)));
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

  return (
    <div className="mvp-page mvp-overview-page" data-testid="mvp-overview">
      <section className="mvp-overview-hero" aria-label="오늘 운영 요약">
        <div>
          <span>{role === "field_operator" ? "FIELD BOARD" : "PRODUCTION BOARD"}</span>
          <h2>{role === "field_operator" ? "점검 요청 리포트에서 작업 오더 후보를 고릅니다" : "상태 요약 리포트에서 셀 상태를 봅니다"}</h2>
          <p>
            {role === "field_operator"
              ? `오더 후보 ${workOrderCandidates.length}건 · 부품 확인 ${needsPartCheck}건 · 실제 WorkOrder ID는 생성하지 않음`
              : `위험 라인 ${riskyLines}개 · 셀 ${cellSummaries.length}개 · 평균 위험도 ${formatProbability(metrics.averageRisk)}`}
          </p>
        </div>
        <button type="button" className="mvp-button ghost" onClick={onRefresh}><RefreshCw size={15} />새로고침</button>
      </section>

      <section className="mvp-kpi-grid mvp-overview-kpis" aria-label="운영 위험 KPI">
        <article className="mvp-kpi is-critical"><span>위험 설비</span><strong>{metrics.critical}</strong><small>긴급 검토가 필요한 설비</small></article>
        <article className="mvp-kpi is-warning"><span>경고 설비</span><strong>{metrics.warning}</strong><small>현장 확인 대상</small></article>
        <article className="mvp-kpi"><span>평균 위험도</span><strong>{formatProbability(metrics.averageRisk)}</strong><small>고장율이 아닌 모델 위험 평균</small></article>
        <article className="mvp-kpi"><span>판단 대기</span><strong>{metrics.pendingDecisions}</strong><small>Operations에서 처리</small></article>
        <article className="mvp-kpi is-hold"><span>데이터 확인</span><strong>{metrics.dataQualityHold}</strong><small>정상값으로 대체하지 않음</small></article>
        <article className="mvp-kpi"><span>예상 영향</span><strong>{formatMinutes(metrics.estimatedDowntimeMinutes)}</strong><small>근거 없으면 부족으로 표시</small></article>
      </section>

      {role === "field_operator" ? (
        <div className="mvp-role-overview">
          <MvpPanel title="작업 오더 제안" eyebrow="FROM INSPECTION REQUEST" className="mvp-today-panel">
            <div className="mvp-order-board">
              <header><ClipboardList size={15} /><strong>의심 부품 우선순위</strong><span>{workOrderCandidates.length}건</span></header>
              <div className="mvp-work-card-list">
                {workOrderCandidates.length ? workOrderCandidates.map((candidate, index) => (
                  <button type="button" key={candidate.event.eventId} className={selectedAsset?.assetId === candidate.event.assetId ? "mvp-work-card is-selected" : "mvp-work-card"} onClick={() => onPreviewAsset(candidate.event.assetId, candidate.event.eventId)}>
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
          <AssetPreviewPanel asset={selectedAsset} event={selectedEvent} candidate={selectedCandidate} cell={selectedCell} factors={selectedFactors} maxContribution={maxContribution} detailLoading={detailLoading} detailError={detailError} onOpenAsset={onOpenAsset} onOpenEvent={onOpenEvent} onOpenReport={onOpenReport} />
        </div>
      ) : (
        <div className="mvp-role-overview">
          <MvpPanel title="셀 단위 설비 맵" eyebrow="FROM STATUS SUMMARY" className="mvp-process-panel">
            {cellSummaries.length ? (
              <div className="mvp-cell-map">
                {cellSummaries.slice(0, 12).map((cell) => {
                  const tone = riskTone(cell);
                  return (
                    <button type="button" key={cell.cell} className={`mvp-cell-block tone-${tone} ${selectedCell?.cell === cell.cell ? "is-selected" : ""}`} onClick={() => onPreviewAsset(cell.representative.assetId, cell.representative.eventId)}>
                      <span>{cell.line}</span>
                      <strong>{cell.cell}</strong>
                      <b>{formatProbability(cell.averageRisk)}</b>
                      <small>{cell.assets.length}대 · 위험 {cell.critical} · 경고 {cell.warning} · 확인 {cell.hold}</small>
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
            <AssetPreviewPanel asset={selectedAsset} event={selectedEvent} candidate={selectedCandidate} cell={selectedCell} factors={selectedFactors} maxContribution={maxContribution} detailLoading={detailLoading} detailError={detailError} onOpenAsset={onOpenAsset} onOpenEvent={onOpenEvent} onOpenReport={onOpenReport} />
          </div>
        </div>
      )}

      <MvpPanel title="위험 설비 목록" eyebrow="SELECT ASSET" className="mvp-priority-panel">
        {topAssets.length ? (
          <div className="mvp-priority-list">
            {topAssets.map((asset, index) => (
              <button type="button" key={asset.assetId} className={selectedAsset?.assetId === asset.assetId ? "is-selected" : ""} onClick={() => onPreviewAsset(asset.assetId, asset.eventId)}>
                <span className="mvp-rank">{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{asset.displayName}</strong><small>{asset.assetId} · {asset.line}</small></div>
                <MvpStatusBadge status={asset.status} />
                <b>{formatProbability(asset.failureProbability)}</b>
                <ArrowRight size={15} />
              </button>
            ))}
          </div>
        ) : <MvpState kind="empty" title="표시할 설비가 없습니다" detail="현재 Dataset Version에서 조회된 설비가 없습니다." />}
      </MvpPanel>
    </div>
  );
}

function AssetPreviewPanel({
  asset,
  event,
  candidate,
  cell,
  factors,
  maxContribution,
  detailLoading,
  detailError,
  onOpenAsset,
  onOpenEvent,
  onOpenReport,
}: {
  asset: MvpAsset | null;
  event: MvpEvent | null;
  candidate: WorkOrderCandidate | null;
  cell: CellSummary | null;
  factors: MvpAsset["topFactors"];
  maxContribution: number;
  detailLoading: boolean;
  detailError: string | null;
  onOpenAsset: (assetId: string, eventId: string | null) => void;
  onOpenEvent: (eventId: string, assetId: string) => void;
  onOpenReport: (eventId: string | null, assetId: string | null) => void;
}) {
  return (
    <MvpPanel
      title="선택 항목"
      eyebrow="SUMMARY FEATURE GRAPH"
      className="mvp-asset-preview-panel"
      actions={asset ? (
        <>
          <button type="button" className="mvp-button secondary" onClick={() => onOpenAsset(asset.assetId, asset.eventId)}><Boxes size={14} />근거</button>
          <button type="button" className="mvp-button primary" onClick={() => event && onOpenEvent(event.eventId, event.assetId)} disabled={!event}><ClipboardCheck size={14} />판단</button>
          <button type="button" className="mvp-button ghost" onClick={() => onOpenReport(event?.eventId ?? null, asset.assetId)}><FileText size={14} />보고</button>
        </>
      ) : null}
    >
      {asset ? (
        <div className="mvp-asset-preview">
          <header>
            <MvpStatusBadge status={asset.status} />
            <div><strong>{statusText(asset)}</strong><small>{asset.assetId} · 관측 {formatTimestamp(asset.observedAt)}</small></div>
          </header>
          <dl>
            <div><dt>위험도</dt><dd>{formatProbability(asset.failureProbability)}</dd></div>
            <div><dt>권고</dt><dd>{DECISION_LABEL[asset.recommendedDecision]}</dd></div>
            <div><dt>부품</dt><dd>{partLabel(asset.sparePartAvailable)}</dd></div>
            <div><dt>담당</dt><dd>{asset.assignedEngineer ?? "미배정"}</dd></div>
            <div><dt>영향</dt><dd>{formatMinutes(asset.estimatedDowntimeMinutes)}</dd></div>
            <div><dt>신뢰도</dt><dd><MvpConfidenceBadge confidence={asset.confidence} /></dd></div>
            {candidate ? <div><dt>오더 후보</dt><dd>{candidate.suspectedPart}</dd></div> : null}
            {cell ? <div><dt>셀</dt><dd>{cell.cell} · {cell.assets.length}대</dd></div> : null}
          </dl>
          <section className="mvp-mini-feature-chart" aria-label="주요 피쳐값">
            <header><BarChart3 size={14} /><strong>주요 피쳐</strong><span>{detailLoading ? "불러오는 중" : detailError ? "상세 연결 실패" : "현재 snapshot"}</span></header>
            {factors.length ? factors.slice(0, 5).map((factor) => (
              <div key={factor.id} className="mvp-mini-feature-row">
                <span>{factor.label}</span>
                <b>{factor.value === null ? "근거 부족" : `${factor.value.toLocaleString()}${factor.unit ? ` ${factor.unit}` : ""}`}</b>
                <i><em style={{ width: `${Math.max(5, (Math.abs(factor.contribution) / maxContribution) * 100)}%` }} /></i>
              </div>
            )) : <MvpState kind="empty" title="피쳐 근거가 없습니다" detail="선택 설비의 current feature 또는 factor 근거가 연결되지 않았습니다." />}
          </section>
        </div>
      ) : <MvpState kind="empty" title="선택된 설비가 없습니다" detail="왼쪽의 설비 또는 라인을 선택하세요." />}
    </MvpPanel>
  );
}

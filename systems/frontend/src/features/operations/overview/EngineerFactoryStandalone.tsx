import type { OperationsAsset, OperationsBootstrapModel, OperationsRiskStatus } from "../api/operationsContracts";
import { displayAssetName, displayAssetShortName, displaySensorLabel, fieldFailureLabel } from "../displayLabels";

const STATUS_LABEL: Record<OperationsRiskStatus, string> = {
  normal: "정상",
  attention: "주의",
  warning: "주의",
  critical: "긴급",
  data_quality_hold: "확인 필요",
};

function formatTimestamp(value: string | null | undefined) {
  if (!value) return "시각 정보 없음";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function formatProbability(value: number | null | undefined) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function formatMinutes(value: number | null | undefined) {
  if (typeof value !== "number") return "정보 없음";
  const hours = Math.floor(value / 60);
  const minutes = Math.round(value % 60);
  return hours ? `${hours}시간 ${minutes}분` : `${minutes}분`;
}

function tone(status: OperationsRiskStatus) {
  if (status === "critical") return "critical";
  if (status === "warning" || status === "attention") return "attention";
  if (status === "data_quality_hold") return "hold";
  return "normal";
}

function LoadingPanel({ title, className = "" }: { title: string; className?: string }) {
  return <section className={`engineer-factory-card engineer-local-loading ${className}`} aria-busy="true"><header><strong>{title}</strong></header><div><i /><span>데이터 로딩 중</span></div></section>;
}

export function EngineerFactoryLoading() {
  return (
    <main className="engineer-lite-board engineer-lite-loading" aria-label="공장 현황 데이터 로딩 중">
      <header className="engineer-factory-header"><div><strong>공장 현황</strong><span>설비 데이터를 연결하고 있습니다</span></div><div className="engineer-factory-live"><i /><b>연결 확인 중</b></div></header>
      <section className="engineer-factory-kpis">
        <article aria-busy="true"><span>즉시 조치 필요 설비</span><strong>—</strong><p>데이터 로딩 중</p></article>
        <article aria-busy="true"><span>가동 중 설비</span><strong>—</strong><p>데이터 로딩 중</p></article>
        <article aria-busy="true"><span>예상 정지 영향</span><strong>—</strong><p>데이터 로딩 중</p></article>
      </section>
      <section className="engineer-lite-main">
        <LoadingPanel title="라인 · 셀 · 설비 상태" className="engineer-equipment-list" />
        <LoadingPanel title="위험 점수 추세 · 최근 12시간" className="engineer-risk-trend" />
        <LoadingPanel title="최근 이벤트" className="engineer-recent-events" />
      </section>
      <section className="engineer-factory-bottom-grid"><LoadingPanel title="선택 설비 근거 요약" /><LoadingPanel title="실시간 상태 신호" /></section>
    </main>
  );
}

export function EngineerFactoryStandalone({
  model,
  selectedAssetId,
  onSelectAsset,
  onRefresh,
}: {
  model: OperationsBootstrapModel;
  selectedAssetId: string | null;
  onSelectAsset: (assetId: string, eventId: string | null) => void;
  onRefresh: () => void;
}) {
  const selected = model.assets.find((asset) => asset.assetId === selectedAssetId) ?? model.assets[0] ?? null;
  const groups = new Map<string, OperationsAsset[]>();
  model.assets.forEach((asset) => {
    const key = `${asset.line || "위치 미상"}`;
    groups.set(key, [...(groups.get(key) ?? []), asset]);
  });
  const actionable = model.assets.filter((asset) => asset.status === "critical" || asset.status === "warning").length;
  const held = model.assets.filter((asset) => asset.status === "data_quality_hold").length;
  const recentEvents = [...model.events]
    .sort((a, b) => Date.parse(b.observedAt ?? "") - Date.parse(a.observedAt ?? ""))
    .slice(0, 3);
  const values = model.events
    .filter((event) => event.assetId === selected?.assetId && typeof event.failureProbability === "number")
    .sort((a, b) => Date.parse(a.observedAt ?? "") - Date.parse(b.observedAt ?? ""))
    .map((event) => event.failureProbability as number)
    .slice(-24);
  if (values.length < 2 && selected?.failureProbability != null) values.push(Math.max(0, selected.failureProbability * .72), selected.failureProbability);
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1) * 100).toFixed(2)},${(100 - value * 100).toFixed(2)}`).join(" ");
  const factors = selected?.topFactors.filter((factor) => typeof factor.value === "number").slice(0, 4) ?? [];

  return (
    <main className="engineer-lite-board">
      <header className="engineer-factory-header">
        <div><strong>공장 현황</strong><span>{model.context.workspaceName} · {groups.size}개 라인 · 설비 {model.assets.length}대</span></div>
        <div className="engineer-factory-live"><i /><b>실시간 수집 중</b><span>기준 시각 {formatTimestamp(model.context.observedAt ?? model.context.refreshedAt)}</span><button type="button" onClick={onRefresh} aria-label="공장 현황 새로고침">↻ 새로고침</button></div>
      </header>

      <section className="engineer-factory-kpis">
        <article><span>즉시 조치 필요 설비</span><strong>{actionable}<small>대</small></strong><p>긴급·경고 등급으로 현장 확인이 필요합니다.</p></article>
        <article><span>가동 중 설비</span><strong>{Math.max(0, model.assets.length - held)}<small>/ {model.assets.length}대</small></strong><p>확인 보류 설비 {held}대는 별도로 구분합니다.</p></article>
        <article><span>예상 정지 영향</span><strong>{formatMinutes(model.metrics.estimatedDowntimeMinutes)}</strong><p>현재 위험 설비의 예측 비가동 시간 합계입니다.</p></article>
      </section>

      <section className="engineer-lite-main">
        <section className="engineer-factory-card engineer-equipment-list">
          <header><strong>라인 · 셀 · 설비 상태</strong><span>설비를 누르면 현황이 함께 바뀝니다</span></header>
          <div className="engineer-equipment-scroll">
            {[...groups.entries()].map(([line, assets]) => <article key={line}><div><b>{line}</b><small>{assets.length}대</small></div><div className="engineer-equipment-slots">{assets.map((asset) => <button type="button" key={asset.assetId} className={`tone-${tone(asset.status)} ${asset.assetId === selected?.assetId ? "is-selected" : ""}`} onClick={() => onSelectAsset(asset.assetId, asset.eventId)}><span>{displayAssetShortName(asset)}</span><small>{STATUS_LABEL[asset.status]}</small></button>)}</div></article>)}
          </div>
          <footer className="engineer-equipment-legend"><span><i className="normal" />정상</span><span><i className="attention" />주의</span><span><i className="critical" />긴급</span><span><i className="hold" />확인 필요</span></footer>
        </section>

        <section className="engineer-factory-card engineer-risk-trend">
          <header><div><strong>위험 점수 추세 · 최근 12시간</strong><span>{selected ? `${displayAssetName(selected)} · ${selected.assetId}` : "설비를 선택하세요"}</span></div><b className={`tone-${tone(selected?.status ?? "data_quality_hold")}`}>{formatProbability(selected?.failureProbability ?? null)}</b></header>
          <div className="engineer-risk-chart"><svg viewBox="0 0 100 100" preserveAspectRatio="none"><rect y="0" width="100" height="38" className="risk-zone" /><rect y="38" width="100" height="20" className="attention-zone" /><rect y="58" width="100" height="42" className="normal-zone" /><line x1="0" x2="100" y1="38" y2="38" /><line x1="0" x2="100" y1="58" y2="58" /><polyline points={points} /></svg><div><span>이전 관측</span><span>현재</span></div></div>
          <footer><span>현재 상태 <b>{STATUS_LABEL[selected?.status ?? "data_quality_hold"]}</b></span><span>서버 관측 결과 기준</span></footer>
        </section>

        <section className="engineer-factory-card engineer-recent-events">
          <header><strong>최근 이벤트</strong><span>최근 {recentEvents.length}건</span></header>
          <div>{recentEvents.map((event) => <button type="button" key={event.eventId} onClick={() => onSelectAsset(event.assetId, event.eventId)}><span><b>{STATUS_LABEL[event.status]}</b><time>{formatTimestamp(event.observedAt)}</time></span><strong>{event.assetName || event.assetId}</strong><small>{event.line}</small><p>{fieldFailureLabel(event.predictedFailureType)}</p></button>)}</div>
        </section>
      </section>

      <section className="engineer-factory-bottom-grid">
        <section className="engineer-factory-card engineer-evidence-summary"><header><strong>선택 설비 근거 요약</strong><span>{selected?.assetId ?? "-"} · {formatTimestamp(selected?.observedAt ?? null)} 관측</span></header>{selected ? <><div className="engineer-evidence-lead"><b>{STATUS_LABEL[selected.status]}</b><strong>{selected.status === "critical" ? "지금 현장 확인과 보전 대응이 필요한 설비입니다." : selected.status === "data_quality_hold" ? "값보다 계측 연결 상태를 먼저 확인해야 합니다." : "현재 상태에 맞춰 관찰과 점검을 이어갑니다."}</strong></div><ol>{selected.topFactors.slice(0, 4).map((factor) => <li key={factor.id}>{displaySensorLabel(factor.feature, factor.label)} · 기여도 {Math.round(Math.abs(factor.contribution) * 100)}%</li>)}</ol><dl><div><dt>담당자</dt><dd>{selected.assignedEngineer ?? "미배정"}</dd></div><div><dt>예상 정지</dt><dd>{formatMinutes(selected.estimatedDowntimeMinutes)}</dd></div><div><dt>부품</dt><dd>{selected.sparePartAvailable === true ? "확보" : selected.sparePartAvailable === false ? "미확보" : "확인 필요"}</dd></div><div><dt>설비 중요도</dt><dd>{selected.criticality ?? "정보 없음"}</dd></div></dl><p className="engineer-evidence-footer">판단 근거는 현재 선택 설비의 서버 Result와 관측 시각을 기준으로 표시합니다.</p></> : null}</section>
        <section className="engineer-factory-card engineer-live-signals"><header><strong>실시간 상태 신호</strong><span>위험 점수를 밀어올린 신호 상위 {factors.length}건 · {formatTimestamp(selected?.observedAt ?? null)}</span></header><div>{factors.map((factor) => <article key={factor.id}><i><b style={{height: `${Math.max(8, Math.min(100, Math.abs(factor.contribution) * 100))}%`}} /></i><strong>{factor.value?.toLocaleString("ko-KR", {maximumFractionDigits: 2})}<small>{factor.unit ?? ""}</small></strong><span>{displaySensorLabel(factor.feature, factor.label)}</span><small>현재 관측값</small></article>)}</div><footer className="engineer-signal-note"><span><i />정상 범위 띠</span><span>막대 높이 = 위험 기여도</span><span>서버 관측 품질 기준</span></footer></section>
      </section>

    </main>
  );
}

import { ArrowLeft, Bot, Printer } from "lucide-react";
import { useEffect, useState } from "react";
import { getMvpAgentReviewSummary } from "../../../api";
import type {
  MvpAgentReviewSummaryResponse,
  MvpBootstrapModel,
  MvpEvent,
  MvpEventDetailModel,
} from "../api/mvpContracts";
import {
  DECISION_LABEL,
  CONFIDENCE_LABEL,
  MvpProvenanceView,
  MvpState,
  MvpStatusBadge,
  formatMinutes,
  formatProbability,
  formatTimestamp,
} from "../components/MvpUi";
import { displayAssetName, displayEventAssetName, displayEventLabel, fieldFactorItem, fieldFailureLabel } from "../displayLabels";

function reportAgentSummaryStatusLabel(payload: MvpAgentReviewSummaryResponse | null): string {
  if (payload?.trace.materialization?.reused) return "저장본 재사용";
  const status = payload?.trace.materialization?.status;
  if (status === "ready") return "검증 완료";
  if (status === "fallback") return "검증 fallback";
  if (status === "failed") return "생성 실패";
  if (status === "stale") return "갱신 필요";
  if (payload?.summary.mode === "llm") return "LLM 검증 완료";
  if (payload?.summary.mode === "deterministic_fallback") return "규칙 기반 요약";
  return "조회 대기";
}

export function MvpExecutiveReportPage({
  model,
  selectedEvent,
  detail,
  detailLoading,
  detailError,
  onBackToOverview,
  onRetryDetail,
}: {
  model: MvpBootstrapModel;
  selectedEvent: MvpEvent | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  onBackToOverview: () => void;
  onOpenOperations: (event: MvpEvent) => void;
  onRetryDetail: () => void;
}) {
  const [agentSummary, setAgentSummary] = useState<MvpAgentReviewSummaryResponse | null>(null);
  const [agentSummaryLoading, setAgentSummaryLoading] = useState(false);
  const [agentSummaryError, setAgentSummaryError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedEvent) {
      setAgentSummary(null);
      setAgentSummaryError(null);
      setAgentSummaryLoading(false);
      return;
    }
    let cancelled = false;
    setAgentSummaryLoading(true);
    setAgentSummaryError(null);
    getMvpAgentReviewSummary({
      assetId: selectedEvent.assetId,
      projectId: model.context.projectId,
      datasetVersionId: model.context.datasetVersionId,
    })
      .then((payload) => !cancelled && setAgentSummary(payload))
      .catch((reason: unknown) => {
        if (cancelled) return;
        setAgentSummary(null);
        setAgentSummaryError(reason instanceof Error ? reason.message : "저장된 AI 요약을 불러오지 못했습니다.");
      })
      .finally(() => !cancelled && setAgentSummaryLoading(false));
    return () => { cancelled = true; };
  }, [model.context.datasetVersionId, model.context.projectId, selectedEvent?.assetId]);

  if (!selectedEvent) {
    return <div className="mvp-page" data-testid="mvp-executive-report"><MvpState kind="empty" title="보고 대상 이벤트를 선택하세요" detail="Overview 또는 Operations에서 이벤트를 선택하면 동일 수치와 대응 상태로 보고서를 구성합니다." /></div>;
  }
  if (detailLoading) return <div className="mvp-page" data-testid="mvp-executive-report"><MvpState kind="loading" title="상황 브리핑 준비 중" detail="선택 이벤트의 근거와 보고서 내용을 확인하고 있습니다." /></div>;
  if (detailError) return <div className="mvp-page" data-testid="mvp-executive-report"><MvpState kind="error" title="보고서를 준비하지 못했습니다" detail={detailError} onRetry={onRetryDetail} /></div>;
  if (!detail) return <div className="mvp-page" data-testid="mvp-executive-report"><MvpState kind="empty" title="보고서 데이터가 없습니다" detail="선택 이벤트의 근거와 보고서 내용을 확인할 수 없습니다." /></div>;

  const report = detail.report;
  const topAssets = model.assets.slice(0, 5);
  const unresolved = model.events.filter((event) => event.recommendedDecision !== "continue_monitoring").slice(0, 6);
  const dataQualityEvents = model.events.filter((event) => event.status === "data_quality_hold");
  const latestDecision = detail.activity.find((activity) => activity.kind === "decision");

  return (
    <div className="mvp-page mvp-report-page" data-testid="mvp-executive-report">
      <div className="mvp-report-toolbar">
        <button type="button" className="mvp-button secondary" onClick={onBackToOverview}><ArrowLeft size={14} />Overview</button>
        <div><span className={`mvp-report-mode mode-${report.mode}`}>근거 기반 보고서</span><strong>숫자는 최신 이벤트와 근거를 사용합니다.</strong></div>
        <button type="button" className="mvp-button primary" onClick={() => window.print()}><Printer size={15} />A4 PDF / Print</button>
      </div>

      {detail.warnings.length ? <div className="mvp-inline-warning"><strong>생성 경로 경고</strong><ul>{detail.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}

      <article className="mvp-report-document">
        <header className="mvp-report-cover">
          <div className="mvp-report-cover-brand"><span>ONTOLOGY DASHBOARD</span><strong>Predictive Maintenance Brief</strong></div>
          <div className="mvp-report-cover-title"><span>MANUFACTURING RELIABILITY · SITUATION BRIEF</span><h1>{report.headline}</h1><p>{report.summary}</p></div>
          <dl className="mvp-report-document-meta">
            <div><dt>문서 번호</dt><dd>{report.reportId}</dd></div>
            <div><dt>버전</dt><dd>{report.revision || "기본 발행본"}</dd></div>
            <div><dt>발행일</dt><dd>{formatTimestamp(report.generatedAt)}</dd></div>
            <div><dt>Project</dt><dd>{model.context.projectName}</dd></div>
            <div><dt>Dataset</dt><dd>{model.context.datasetVersionId}</dd></div>
            <div><dt>대상 이벤트</dt><dd>{displayEventLabel(selectedEvent)}</dd></div>
          </dl>
        </header>

        <section className="mvp-report-executive-summary">
          <div><span>DECISION SUMMARY</span><h2>{displayEventAssetName(selectedEvent)}을 우선 대응 대상으로 관리합니다.</h2><p>{selectedEvent.status === "data_quality_hold" ? "데이터 품질 문제로 고장 판단을 보류하고 원천 데이터 확인 업무를 우선합니다." : `현재 위험도는 ${formatProbability(selectedEvent.failureProbability)}이며, 예상 생산 영향은 ${formatMinutes(selectedEvent.estimatedDowntimeMinutes)}입니다. 모델 확률은 실제 고장 확정이 아닙니다.`}</p></div>
          <aside><MvpStatusBadge status={selectedEvent.status} /><strong>{DECISION_LABEL[selectedEvent.recommendedDecision]}</strong><small>최근 사람 결정: {latestDecision?.decision ? DECISION_LABEL[latestDecision.decision] : "아직 기록 없음"}</small><small>판단 기록은 Operations에서 관리</small></aside>
        </section>

        <section className="mvp-report-agent-summary">
          <header><Bot size={17} /><span>AI 저장 요약</span><strong>{reportAgentSummaryStatusLabel(agentSummary)}</strong></header>
          {agentSummaryLoading ? <p>저장된 AI 요약을 조회하는 중입니다.</p> : null}
          {!agentSummaryLoading && agentSummaryError ? <p>{agentSummaryError}</p> : null}
          {!agentSummaryLoading && agentSummary ? (
            <>
              <div>
                <strong>{agentSummary.summary.title}</strong>
                <p>{agentSummary.summary.summary}</p>
              </div>
              {agentSummary.summary.role_summaries.length ? (
                <div className="mvp-report-agent-quotes">
                  {agentSummary.summary.role_summaries.map((item) => (
                    <figure key={`${agentSummary.summary.asset_id}-${item.role}`}>
                      <figcaption>{item.label}</figcaption>
                      <blockquote>{item.quote}</blockquote>
                    </figure>
                  ))}
                </div>
              ) : null}
              {agentSummary.summary.data_footnotes.length ? (
                <ol>
                  {agentSummary.summary.data_footnotes.map((item, index) => (
                    <li key={`${item.code}-${index}`}><sup>{index + 1}</sup>{item.note}</li>
                  ))}
                </ol>
              ) : null}
              <small>{agentSummary.summary.boundary_note}</small>
            </>
          ) : null}
        </section>

        <section className="mvp-report-kpis">
          <article><span>Critical</span><strong>{model.metrics.critical}</strong><small>전체 {model.metrics.totalAssets} 설비</small></article>
          <article><span>Warning</span><strong>{model.metrics.warning}</strong><small>현장 점검 필요</small></article>
          <article><span>Average risk</span><strong>{formatProbability(model.metrics.averageRisk)}</strong><small>품질 보류 제외</small></article>
          <article><span>예상 정지 영향</span><strong>{formatMinutes(model.metrics.estimatedDowntimeMinutes)}</strong><small>이벤트 합산</small></article>
          <article><span>Pending decisions</span><strong>{model.metrics.pendingDecisions}</strong><small>사람 판단 대기</small></article>
        </section>

        <div className="mvp-report-content-grid">
          <main className="mvp-report-narrative">
            {report.sections.map((section, index) => (
              <section key={section.id}>
                <header><span>{String(index + 1).padStart(2, "0")}</span><h2>{section.title}</h2></header>
                <p>{section.body}</p>
                {section.evidenceFieldIds.length ? <div className="mvp-report-evidence-ids"><span>근거 항목</span>{section.evidenceFieldIds.map((field) => <code key={field}>{field}</code>)}</div> : null}
              </section>
            ))}

            <section>
              <header><span>{String(report.sections.length + 1).padStart(2, "0")}</span><h2>대응 상태와 미결정 사항</h2></header>
              {unresolved.length ? <table className="mvp-report-table"><thead><tr><th>설비</th><th>상태</th><th>권장 결정</th><th>담당자</th><th>영향</th></tr></thead><tbody>{unresolved.map((event) => <tr key={event.eventId}><td><strong>{displayEventAssetName(event)}</strong><small>{displayEventLabel(event)}</small></td><td><MvpStatusBadge status={event.status} /></td><td>{DECISION_LABEL[event.recommendedDecision]}</td><td>{event.assignedEngineer ?? "미배정"}</td><td>{formatMinutes(event.estimatedDowntimeMinutes)}</td></tr>)}</tbody></table> : <p>현재 미결정 이벤트가 없습니다.</p>}
            </section>

            <section className="mvp-report-limitations">
              <header><span>{String(report.sections.length + 2).padStart(2, "0")}</span><h2>불확실성·데이터 품질·한계</h2></header>
              {dataQualityEvents.length ? <p><strong>{dataQualityEvents.length}개 이벤트</strong>는 데이터 품질 문제로 고장 수치 대신 확인 필요 상태를 표시합니다.</p> : <p>현재 품질 보류 이벤트는 없습니다.</p>}
              <ul>{report.limitations.map((item) => <li key={item}>{item}</li>)}{detail.dataQualityWarnings.map((warning) => <li key={`${warning.code}-${warning.field}`}>{warning.message}</li>)}</ul>
            </section>
          </main>

          <aside className="mvp-report-evidence-column">
            <section><span>주요 위험 설비</span><div className="mvp-report-asset-list">{topAssets.map((asset, index) => <article key={asset.assetId}><b>{String(index + 1).padStart(2, "0")}</b><div><strong>{displayAssetName(asset)}</strong><small>{asset.line}</small></div><span>{formatProbability(asset.failureProbability)}</span></article>)}</div></section>
            <section><span>선택 이벤트 근거</span><dl><div><dt>고장 확률</dt><dd>{formatProbability(selectedEvent.failureProbability)}</dd></div><div><dt>신뢰도</dt><dd>{CONFIDENCE_LABEL[selectedEvent.confidence]}</dd></div><div><dt>고장 유형</dt><dd>{fieldFailureLabel(selectedEvent.predictedFailureType)}</dd></div><div><dt>중요도</dt><dd>{detail.assetCriticality ?? selectedEvent.criticality ?? "확인 필요"}</dd></div><div><dt>검토 우선순위</dt><dd>{detail.reviewPriority?.level ?? "확인 필요"}</dd></div><div><dt>담당자</dt><dd>{selectedEvent.assignedEngineer ?? "미배정"}</dd></div></dl></section>
            <section><span>근거 참조</span>{detail.topFactors.length ? <dl>{detail.topFactors.slice(0, 5).map((factor) => <div key={factor.id}><dt>{fieldFactorItem(factor)}</dt><dd>{factor.id}</dd></div>)}</dl> : <p>제공된 설명 요인이 없습니다.</p>}{detail.reviewPriority?.sourceFields.length ? <div className="mvp-report-evidence-ids"><span>Review fields</span>{detail.reviewPriority.sourceFields.map((field) => <code key={field}>{field}</code>)}</div> : null}{detail.evidenceGaps.length ? <ul>{detail.evidenceGaps.map((gap) => <li key={`${gap.ownerDomain}-${gap.field}`}>{gap.field} · {gap.reason}</li>)}</ul> : null}</section>
            <section><span>출처</span><MvpProvenanceView provenance={detail.provenance} compact /></section>
          </aside>
        </div>

        <footer className="mvp-report-footer"><span>{model.context.datasetLabel}</span><span>{report.reportId} · {formatTimestamp(report.generatedAt)}</span><strong>Ontology Dashboard · 근거 기반 보고서</strong></footer>
      </article>
    </div>
  );
}

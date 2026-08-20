import { ArrowLeft, ExternalLink, FileText, ShieldCheck } from "lucide-react";
import type {
  MvpBootstrapModel,
  MvpEvent,
  MvpEventDetailModel,
  MvpFactor,
  MvpSensorValue,
} from "../api/mvpContracts";
import {
  DECISION_LABEL,
  MvpConfidenceBadge,
  MvpPanel,
  MvpProvenanceView,
  MvpState,
  MvpStatusBadge,
  formatMinutes,
  formatProbability,
  formatTimestamp,
} from "../components/MvpUi";

interface InspectionReportViewModel {
  title: string;
  subtitle: string;
  requestedDecision: string;
  inspectionSummary: string;
  fieldChecks: string[];
  safetyLimits: string[];
  sensors: MvpSensorValue[];
  evidenceTrace: MvpFactor[];
}

function sensorValueLabel(sensor: MvpSensorValue): string {
  if (sensor.value === null || sensor.value === undefined || sensor.value === "") return "근거 부족";
  const raw = typeof sensor.value === "number"
    ? sensor.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 })
    : String(sensor.value);
  return sensor.unit ? `${raw} ${sensor.unit}` : raw;
}

function buildInspectionReportViewModel(event: MvpEvent, detail: MvpEventDetailModel): InspectionReportViewModel {
  const primaryFactor = detail.topFactors[0] ?? null;
  const factorText = primaryFactor
    ? `${primaryFactor.label} (${primaryFactor.feature}) 신호를 우선 확인합니다.`
    : "검증된 top factor가 없으므로 원천 센서와 현장 상태를 먼저 확인합니다.";
  const checklist = detail.report.sections.find((section) => section.id.includes("response") || section.id.includes("evidence"));
  return {
    title: `${event.assetName} 예지보전 점검 요청`,
    subtitle: `${event.line} · ${event.eventId}`,
    requestedDecision: DECISION_LABEL[event.recommendedDecision],
    inspectionSummary: event.status === "data_quality_hold"
      ? "데이터 품질 문제로 모델 판단을 보류하고 원천 데이터 재확인부터 진행합니다."
      : `현재 위험도는 ${formatProbability(event.failureProbability)}이며, ${event.assignedEngineer ?? "미배정 담당자"} 기준 현장 확인이 필요합니다.`,
    fieldChecks: [
      factorText,
      `예상 생산 영향 ${formatMinutes(event.estimatedDowntimeMinutes)} 범위를 운영 담당자와 확인합니다.`,
      checklist?.body ?? "점검 결과는 Operations의 Event note/activity로 남기고 자동 Work Order를 만들지 않습니다.",
    ],
    safetyLimits: [
      "이 화면은 고장 확정이나 원인 확정을 표시하지 않습니다.",
      "review_shutdown은 자동 정지 명령이 아니라 사람의 검토 요청입니다.",
      "Prototype 화면 구조만 이식했으며 raw producer payload나 외부 prototype 코드를 런타임 dependency로 사용하지 않습니다.",
    ],
    sensors: detail.sensors,
    evidenceTrace: detail.topFactors,
  };
}

export function MvpInspectionReportPage({
  model,
  selectedEvent,
  detail,
  detailLoading,
  detailError,
  onBackToOverview,
  onOpenOperations,
  onOpenExecutiveReport,
  onRetryDetail,
}: {
  model: MvpBootstrapModel;
  selectedEvent: MvpEvent | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  onBackToOverview: () => void;
  onOpenOperations: (event: MvpEvent) => void;
  onOpenExecutiveReport: (event: MvpEvent) => void;
  onRetryDetail: () => void;
}) {
  if (!selectedEvent) {
    return <div className="mvp-page" data-testid="mvp-inspection-report"><MvpState kind="empty" title="점검 요청 대상 Event를 선택하세요" detail="Overview 또는 Operations에서 Event를 선택하면 대시보드 사이드탭 보고서로 표시합니다." /></div>;
  }
  if (detailLoading) return <div className="mvp-page" data-testid="mvp-inspection-report"><MvpState kind="loading" title="점검 요청 보고서 준비 중" detail="선택 Event의 Evidence, sensor card, report grounding을 typed ViewModel로 구성하고 있습니다." /></div>;
  if (detailError) return <div className="mvp-page" data-testid="mvp-inspection-report"><MvpState kind="error" title="점검 요청 보고서를 준비하지 못했습니다" detail={detailError} onRetry={onRetryDetail} /></div>;
  if (!detail) return <div className="mvp-page" data-testid="mvp-inspection-report"><MvpState kind="empty" title="점검 요청 근거가 없습니다" detail="선택 Event의 Evidence projection 또는 legacy Evidence fallback을 확인할 수 없습니다." /></div>;

  const report = buildInspectionReportViewModel(selectedEvent, detail);
  const sourceState = detail.loadedSources.evidence ? "Evidence 연결" : "Template fallback";

  return (
    <div className="mvp-page mvp-inspection-report-page" data-testid="mvp-inspection-report">
      <div className="mvp-report-toolbar">
        <button type="button" className="mvp-button secondary" onClick={onBackToOverview}><ArrowLeft size={14} />Overview</button>
        <div><span className="mvp-report-mode mode-deterministic-fallback">{sourceState}</span><strong>선택 Event 기준 점검 요청 화면입니다.</strong></div>
        <button type="button" className="mvp-button secondary" onClick={() => onOpenExecutiveReport(selectedEvent)}><FileText size={15} />Executive Brief</button>
      </div>

      {detail.warnings.length ? <div className="mvp-inline-warning"><strong>연결 경고</strong><ul>{detail.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}

      <section className="mvp-inspection-hero">
        <div>
          <span>MAP-REPORT PROTOTYPE PATTERN · DASHBOARD SIDE TAB</span>
          <h2>{report.title}</h2>
          <p>{report.subtitle}</p>
        </div>
        <aside>
          <MvpStatusBadge status={selectedEvent.status} />
          <MvpConfidenceBadge confidence={selectedEvent.confidence} />
          <strong>{report.requestedDecision}</strong>
        </aside>
      </section>

      <section className="mvp-inspection-summary-grid" aria-label="점검 요청 요약">
        <article><span>위험도</span><strong>{formatProbability(selectedEvent.failureProbability)}</strong><small>임계값 {detail.threshold === null ? "근거 부족" : formatProbability(detail.threshold)}</small></article>
        <article><span>생산 영향</span><strong>{formatMinutes(selectedEvent.estimatedDowntimeMinutes)}</strong><small>{selectedEvent.criticality} criticality</small></article>
        <article><span>담당자</span><strong>{selectedEvent.assignedEngineer ?? "미배정"}</strong><small>Operations note로 후속 기록</small></article>
        <article><span>관측 시각</span><strong>{formatTimestamp(selectedEvent.observedAt)}</strong><small>{model.context.datasetVersionId}</small></article>
      </section>

      <div className="mvp-inspection-layout">
        <main className="mvp-inspection-main">
          <MvpPanel title="점검 요청" eyebrow="Inspection request">
            <p className="mvp-inspection-lead">{report.inspectionSummary}</p>
            <ol className="mvp-inspection-checklist">{report.fieldChecks.map((item) => <li key={item}>{item}</li>)}</ol>
            <button type="button" className="mvp-button primary" onClick={() => onOpenOperations(selectedEvent)}>Operations에서 기록하기 <ExternalLink size={13} /></button>
          </MvpPanel>

          <MvpPanel title="센서 참고값" eyebrow="Sensor evidence">
            {report.sensors.length ? (
              <dl className="mvp-inspection-sensor-grid">
                {report.sensors.map((sensor) => (
                  <div key={sensor.id}>
                    <dt>{sensor.label}</dt>
                    <dd>{sensorValueLabel(sensor)}</dd>
                    <code>{sensor.id}</code>
                  </div>
                ))}
              </dl>
            ) : <p className="mvp-muted">표시 가능한 sensor card가 없습니다. Evidence gap으로 처리합니다.</p>}
          </MvpPanel>
        </main>

        <aside className="mvp-inspection-side">
          <MvpPanel title="근거 추적" eyebrow="Evidence trace">
            {report.evidenceTrace.length ? (
              <div className="mvp-inspection-trace-list">
                {report.evidenceTrace.map((factor) => (
                  <article key={factor.id}>
                    <header><strong>{factor.label}</strong><span>{Math.round(factor.contribution * 100)}%</span></header>
                    <p>{factor.feature} · {factor.direction === "risk_up" ? "위험 상승 근거" : "위험 완화 근거"}</p>
                    <code>{factor.id}</code>
                  </article>
                ))}
              </div>
            ) : <p className="mvp-muted">검증된 evidence trace가 없습니다.</p>}
          </MvpPanel>

          <MvpPanel title="한계와 provenance" eyebrow="Boundary">
            <div className="mvp-inspection-limitations">
              <header><ShieldCheck size={15} /><strong>표현 경계</strong></header>
              <ul>{report.safetyLimits.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
            <MvpProvenanceView provenance={detail.provenance} compact />
          </MvpPanel>
        </aside>
      </div>
    </div>
  );
}

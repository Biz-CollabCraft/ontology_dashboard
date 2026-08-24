import { ArrowRight, CheckCircle2, ClipboardCheck, DatabaseZap, Eye, FileText, MessageSquarePlus, PauseCircle, Save, ShieldAlert, ShieldCheck, Wrench } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type {
  MvpBootstrapModel,
  MvpDecision,
  MvpEvent,
  MvpEventDetailModel,
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

const DECISION_OPTIONS: Array<{
  decision: MvpDecision;
  category: string;
  title: string;
  detail: string;
  tone: "calm" | "work" | "warning" | "hold";
  Icon: typeof CheckCircle2;
}> = [
  {
    decision: "request_inspection",
    category: "점검",
    title: DECISION_LABEL.request_inspection,
    detail: "현장 담당자에게 확인 업무를 넘깁니다.",
    tone: "work",
    Icon: ClipboardCheck,
  },
  {
    decision: "hold_for_data_check",
    category: "데이터",
    title: DECISION_LABEL.hold_for_data_check,
    detail: "근거가 부족하면 판단을 보류하고 데이터부터 확인합니다.",
    tone: "hold",
    Icon: DatabaseZap,
  },
  {
    decision: "review_shutdown",
    category: "정지 검토",
    title: DECISION_LABEL.review_shutdown,
    detail: "자동 정지가 아니라 승인권자 검토 안건으로 올립니다.",
    tone: "warning",
    Icon: ShieldAlert,
  },
  {
    decision: "continue_monitoring",
    category: "관찰",
    title: DECISION_LABEL.continue_monitoring,
    detail: "추가 조치 없이 같은 관측 기준으로 계속 봅니다.",
    tone: "calm",
    Icon: PauseCircle,
  },
];

const QUICK_NOTES: Record<MvpDecision, string[]> = {
  request_inspection: ["현장 점검 요청", "센서와 부품 상태 확인", "교대 전 확인 필요"],
  hold_for_data_check: ["근거 부족으로 보류", "센서 신뢰도 재확인", "데이터 갱신 후 재판단"],
  review_shutdown: ["생산 영향 확인 필요", "승인권자 정지 검토", "안전 확인 후 진행"],
  continue_monitoring: ["추가 조치 없이 관찰", "다음 관측까지 유지", "이상 변화 시 재검토"],
};

export function MvpOperationsPage({
  model,
  selectedEventId,
  detail,
  detailLoading,
  detailError,
  canDecide,
  canNote,
  onSelectEvent,
  onOpenAsset,
  onOpenReport,
  onDecision,
  onNote,
  onRetryDetail,
}: {
  model: MvpBootstrapModel;
  selectedEventId: string | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  canDecide: boolean;
  canNote: boolean;
  onSelectEvent: (event: MvpEvent) => void;
  onOpenAsset: (event: MvpEvent) => void;
  onOpenReport: (event: MvpEvent) => void;
  onDecision: (decision: MvpDecision, note: string) => Promise<void>;
  onNote: (body: string) => Promise<void>;
  onRetryDetail: () => void;
}) {
  const selectedEvent = model.events.find((item) => item.eventId === selectedEventId) ?? null;
  const [decision, setDecision] = useState<MvpDecision>(selectedEvent?.recommendedDecision ?? "request_inspection");
  const [decisionNote, setDecisionNote] = useState("");
  const [fieldNote, setFieldNote] = useState("");
  const [savingDecision, setSavingDecision] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [message, setMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const queue = useMemo(() => model.events.filter((item) => item.recommendedDecision !== "continue_monitoring" || item.status !== "normal"), [model.events]);
  const latestDecision = detail?.activity.find((activity) => activity.kind === "decision") ?? null;
  const selectedDecisionOption = DECISION_OPTIONS.find((option) => option.decision === decision) ?? DECISION_OPTIONS[0];
  const SelectedDecisionIcon = selectedDecisionOption.Icon;
  const recommendedOption = selectedEvent
    ? DECISION_OPTIONS.find((option) => option.decision === selectedEvent.recommendedDecision) ?? DECISION_OPTIONS[0]
    : DECISION_OPTIONS[0];
  const gapCount = detail?.evidenceGaps.length ?? 0;
  const evidenceStatus = detailLoading
    ? "근거 확인 중"
    : detailError
      ? "근거 확인 실패"
      : detail
        ? "근거 연결됨"
        : "근거 대기";
  const limitationStatus = gapCount > 0
    ? `${gapCount}개 확인 필요`
    : detailLoading
      ? "확인 중"
      : "주요 제한 없음";
  const decisionStatus = latestDecision?.decision
    ? DECISION_LABEL[latestDecision.decision]
    : "사람 결정 대기";

  useEffect(() => {
    if (!selectedEvent) return;
    setDecision(selectedEvent.recommendedDecision);
    setDecisionNote("");
  }, [selectedEvent?.eventId, selectedEvent?.recommendedDecision]);

  async function saveDecision() {
    setSavingDecision(true);
    setMessage(null);
    try {
      await onDecision(decision, decisionNote);
      setDecisionNote("");
      setMessage({ kind: "success", text: `${DECISION_LABEL[decision]} 기록이 저장됐습니다.` });
    } catch (reason) {
      setMessage({ kind: "error", text: reason instanceof Error ? reason.message : "운영 판단 저장에 실패했습니다." });
    } finally {
      setSavingDecision(false);
    }
  }

  async function saveNote() {
    if (!fieldNote.trim()) return;
    setSavingNote(true);
    setMessage(null);
    try {
      await onNote(fieldNote.trim());
      setFieldNote("");
      setMessage({ kind: "success", text: "현장 메모가 저장됐습니다." });
    } catch (reason) {
      setMessage({ kind: "error", text: reason instanceof Error ? reason.message : "현장 메모 저장에 실패했습니다." });
    } finally {
      setSavingNote(false);
    }
  }

  return (
    <div className="mvp-page mvp-operations-page" data-testid="mvp-operations">
      <div className="mvp-operations-layout">
        <MvpPanel title={`검토 업무 · ${queue.length}`} eyebrow="업무 목록" className="mvp-operation-queue-panel">
          {queue.length ? <div className="mvp-operation-queue">{queue.map((event) => (
            <button type="button" key={event.eventId} className={event.eventId === selectedEventId ? "is-selected" : ""} onClick={() => { setDecision(event.recommendedDecision); onSelectEvent(event); }}>
              <div><MvpStatusBadge status={event.status} /><strong>{event.assetName}</strong><code>{event.eventId}</code></div>
              <dl><div><dt>위험</dt><dd>{formatProbability(event.failureProbability)}</dd></div><div><dt>영향</dt><dd>{formatMinutes(event.estimatedDowntimeMinutes)}</dd></div></dl>
              <span>{DECISION_LABEL[event.recommendedDecision]}</span>
              <small>{event.assignedEngineer ?? "미배정"}</small>
            </button>
          ))}</div> : <MvpState kind="empty" title="검토할 업무가 없습니다" detail="현재 관측 기준으로 즉시 판단할 위험 Event가 없습니다." />}
        </MvpPanel>

        <section className="mvp-operation-detail">
          {!selectedEvent ? (
            <MvpState kind="empty" title="검토할 업무를 선택하세요" detail={selectedEventId ? `요청한 Event ${selectedEventId}를 현재 데이터에서 찾지 못했습니다.` : "왼쪽 목록에서 업무를 선택하면 근거 상태와 판단 기록을 확인할 수 있습니다."} />
          ) : (
            <>
              <MvpPanel title={selectedEvent.assetName} eyebrow={`검토 업무 · ${selectedEvent.eventId}`} actions={<><button type="button" className="mvp-button secondary" onClick={() => onOpenAsset(selectedEvent)}><Wrench size={14} />전체 근거 보기</button><button type="button" className="mvp-button secondary" onClick={() => onOpenReport(selectedEvent)}><FileText size={14} />보고서 보기</button></>}>
                <div className="mvp-guided-action">
                  <div>
                    <span>다음 액션</span>
                    <strong>{recommendedOption.title}</strong>
                    <p>{gapCount > 0 ? `${gapCount}개 제한을 확인한 뒤 기록하세요.` : "추천 판단을 바로 기록하거나, 근거와 보고서를 먼저 확인할 수 있습니다."}</p>
                  </div>
                  <div>
                    {canDecide ? (
                      <button type="button" className="mvp-button primary" onClick={saveDecision} disabled={savingDecision}>
                        <Save size={14} />{savingDecision ? "기록 중" : `${DECISION_LABEL[decision]} 기록`}
                      </button>
                    ) : (
                      <button type="button" className="mvp-button primary" onClick={() => onOpenAsset(selectedEvent)}><Eye size={14} />근거 확인</button>
                    )}
                    <button type="button" className="mvp-button secondary" onClick={() => onOpenReport(selectedEvent)}><FileText size={14} />보고서 보기</button>
                  </div>
                </div>
                <div className="mvp-operation-hero">
                  <div><MvpStatusBadge status={selectedEvent.status} /><MvpConfidenceBadge confidence={selectedEvent.confidence} /></div>
                  <dl><div><dt>고장 확률</dt><dd>{formatProbability(selectedEvent.failureProbability)}</dd></div><div><dt>추천 상태</dt><dd>{DECISION_LABEL[selectedEvent.recommendedDecision]}</dd></div><div><dt>최근 사람 결정</dt><dd>{latestDecision?.decision ? DECISION_LABEL[latestDecision.decision] : "기록 없음"}</dd></div><div><dt>담당자</dt><dd>{selectedEvent.assignedEngineer ?? "미배정"}</dd></div><div><dt>부품</dt><dd>{selectedEvent.sparePartAvailable === null ? "확인 필요" : selectedEvent.sparePartAvailable ? "확보" : "미확보"}</dd></div></dl>
                </div>
                <ol className="mvp-decision-flow" aria-label="업무 진행 상태">
                  <li className={detailError ? "is-warning" : "is-complete"}><span>1</span><div><strong>{evidenceStatus}</strong><small>근거 확인</small></div></li>
                  <li className={gapCount > 0 ? "is-warning" : "is-complete"}><span>2</span><div><strong>{limitationStatus}</strong><small>제한 확인</small></div></li>
                  <li className={latestDecision ? "is-complete" : "is-current"}><span>3</span><div><strong>{decisionStatus}</strong><small>판단 기록</small></div></li>
                </ol>
                {selectedEvent.status === "data_quality_hold" ? <div className="mvp-quality-callout"><strong>추론 억제 상태</strong><p>필수 데이터 품질 검증 전까지 고장 확률과 정지 판단을 확정하지 않습니다. 권장 결정은 데이터 확인 보류입니다.</p></div> : null}
              </MvpPanel>

              {detailLoading ? <MvpPanel title="업무 상세" eyebrow="LOADING"><MvpState kind="loading" title="업무 상세 로딩" detail="선택 업무의 근거, 보고서, 활동 이력을 확인하고 있습니다." /></MvpPanel> : detailError ? <MvpPanel title="업무 상세" eyebrow="ERROR"><MvpState kind="error" title="업무 상세를 불러오지 못했습니다" detail={detailError} onRetry={onRetryDetail} /></MvpPanel> : detail ? (
                <>
                  {detail.warnings.length ? <div className="mvp-inline-warning" role="status"><strong>부분 연결 경고</strong><ul>{detail.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div> : null}
                  <div className="mvp-operation-evidence-grid">
                    <MvpPanel title="판단 선택" eyebrow="액션 선택">
                      <div className="mvp-recommendation"><span>추천</span><strong>{DECISION_LABEL[selectedEvent.recommendedDecision]}</strong><p>버튼 하나를 고르면 아래 기록 액션에 바로 반영됩니다.</p></div>
                      <div className="mvp-decision-option-grid" role="radiogroup" aria-label="판단 종류">
                        {DECISION_OPTIONS.map((option) => {
                          const Icon = option.Icon;
                          return (
                            <button
                              type="button"
                              key={option.decision}
                              className={`mvp-decision-option tone-${option.tone}${decision === option.decision ? " is-selected" : ""}`}
                              onClick={() => setDecision(option.decision)}
                              aria-checked={decision === option.decision}
                              role="radio"
                              disabled={!canDecide}
                            >
                              <Icon size={17} />
                              <span>{option.category}</span>
                              <strong>{option.title}</strong>
                              <small>{option.detail}</small>
                            </button>
                          );
                        })}
                      </div>
                    </MvpPanel>

                    <MvpPanel title="판단 전 요약" eyebrow="확인">
                      <dl className="mvp-sensor-grid">
                        <div><dt>위험</dt><dd>{formatProbability(selectedEvent.failureProbability)} · {selectedEvent.predictedFailureType}</dd></div>
                        <div><dt>운영 영향</dt><dd>{selectedEvent.criticality ?? "중요도 근거 부족"} · {formatMinutes(selectedEvent.estimatedDowntimeMinutes)}</dd></div>
                        <div><dt>결정 전 확인</dt><dd>{detail.evidenceGaps.length ? `${detail.evidenceGaps.length}개 항목 확인 필요` : detail.threshold === null ? "임계값 근거 부족" : `임계값 ${formatProbability(detail.threshold)}`}</dd></div>
                        <div><dt>상세 근거</dt><dd><button type="button" className="mvp-link-button" onClick={() => onOpenAsset(selectedEvent)}>전체 근거 보기</button></dd></div>
                      </dl>
                      {detail.evidenceGaps.length ? <ul className="mvp-gap-list">{detail.evidenceGaps.slice(0, 3).map((gap) => <li key={`${gap.ownerDomain}-${gap.field}`}><strong>{gap.field}</strong><span>{gap.ownerDomain} · {gap.reason}</span></li>)}</ul> : null}
                    </MvpPanel>

                    <MvpPanel title="기록하기" eyebrow="사람 판단">
                      <div className="mvp-write-status"><ShieldCheck size={16} /><div><strong>{canDecide ? "결정 기록 가능" : "읽기 전용"}</strong><span>{canDecide ? "현재 역할로 이 업무의 결정을 남길 수 있습니다." : "현재 역할에는 결정 기록 권한이 없습니다."}</span></div></div>
                      <div className={`mvp-selected-decision tone-${selectedDecisionOption.tone}`}>
                        <SelectedDecisionIcon size={18} />
                        <div><span>선택한 판단</span><strong>{selectedDecisionOption.title}</strong><small>{selectedDecisionOption.detail}</small></div>
                      </div>
                      <div className="mvp-quick-note-list" aria-label="빠른 메모">
                        {QUICK_NOTES[decision].map((note) => (
                          <button type="button" key={note} onClick={() => setDecisionNote(note)} disabled={!canDecide} className={decisionNote === note ? "is-selected" : ""}>{note}</button>
                        ))}
                      </div>
                      <label className="mvp-field"><span>추가 메모 선택 입력</span><textarea value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} placeholder="필요할 때만 짧게 남기세요." disabled={!canDecide} /></label>
                      {decision === "review_shutdown" ? <div className="mvp-safety-note"><strong>자동 정지 아님</strong><span>권한 있는 담당자의 정지 검토를 요청할 뿐 설비 제어 명령을 실행하지 않습니다.</span></div> : null}
                      <button type="button" className="mvp-button primary mvp-wide-action" onClick={saveDecision} disabled={!canDecide || savingDecision}><Save size={14} />{savingDecision ? "기록 중" : `${selectedDecisionOption.title} 기록하기`}</button>
                    </MvpPanel>
                  </div>

                  <div className="mvp-operation-bottom-grid">
                    <MvpPanel title="현장 메모" eyebrow="FIELD NOTE">
                      <div className="mvp-write-status"><MessageSquarePlus size={16} /><div><strong>{canNote ? "메모 기록 가능" : "읽기 전용"}</strong><span>{canNote ? "현장 확인 내용과 전달 사항을 남길 수 있습니다." : "현재 역할에는 메모 작성 권한이 없습니다."}</span></div></div>
                      <label className="mvp-field"><span>점검 결과 또는 전달 사항</span><textarea value={fieldNote} onChange={(event) => setFieldNote(event.target.value)} placeholder="공구 상태, 센서 확인, 작업 가능 여부를 기록하세요." disabled={!canNote} /></label>
                      <button type="button" className="mvp-button secondary" onClick={saveNote} disabled={!canNote || savingNote || !fieldNote.trim()}><Save size={14} />{savingNote ? "저장 중" : "메모 저장"}</button>
                    </MvpPanel>

                    <MvpPanel title="Activity · Audit" eyebrow="SHARED EVENT HISTORY">
                      {detail.activity.length ? <div className="mvp-activity-list">{detail.activity.map((activity) => <article key={activity.id}><span className={`activity-${activity.kind}`} /><div><strong>{activity.decision ? DECISION_LABEL[activity.decision] : activity.title}</strong><p>{activity.detail || "상세 기록 없음"}</p><small>{activity.actor} · {formatTimestamp(activity.createdAt)}</small></div></article>)}</div> : <MvpState kind="empty" title="기록된 Activity가 없습니다" detail="판단 또는 현장 메모가 저장되면 이 Event 이력에 표시됩니다." />}
                    </MvpPanel>
                  </div>

                  <MvpPanel title="근거 위치" eyebrow="TRACEABILITY"><p className="mvp-muted">관측 묶음 {detail.provenance.datasetVersionId} · 모델 {detail.provenance.modelVersion ?? "사용 불가"} · 자세한 센서, 요인, 출처는 전체 근거 화면에서 확인합니다.</p></MvpPanel>
                </>
              ) : null}
              {message ? <div className={`mvp-action-message is-${message.kind}`} role="status"><strong>{message.kind === "success" ? "저장 완료" : "저장 실패"}</strong><span>{message.text}</span></div> : null}
              <button type="button" className="mvp-report-bridge" onClick={() => onOpenReport(selectedEvent)}><div><FileText size={18} /><span>보고서 보기</span><strong>같은 관측 시점의 위험, 제한, 대응 상태를 공유용 문서로 확인합니다.</strong></div><ArrowRight size={17} /></button>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

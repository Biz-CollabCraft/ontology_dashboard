import { useEffect, useState } from "react";
import type { OperationsEventDetailModel } from "../api/operationsContracts";
import { formatTimestamp } from "../components/OperationsUi";
import { fieldText } from "./decisionLabels";
import { DECISION_ACTION_LABELS, loadDecisionProposal, proposalActions, proposalExecution, validateDecisionState, type DecisionAction, type DecisionFact, type DecisionConflict, type DecisionProposalState, type DecisionScope, type PlanningCondition } from "./decisionProposalAdapter";

export function useDecisionProposal(scope: DecisionScope, detail: OperationsEventDetailModel, roles: string[] = [], requestRevision = "") {
  const role = roles.find(r => ["process_manager","process_engineer","maintenance_technician"].includes(r));
  const blocked = Boolean(detail.assetDetailStatus?.isStale || detail.assetDetailStatus?.isDataQualityHold || detail.evidenceContext?.temporalStatus === "stale");
  const key = JSON.stringify([scope, detail.snapshotBasis, role, blocked, requestRevision]);
  const [result, setResult] = useState<{ key: string; state: DecisionProposalState } | null>(null);
  const [, refreshExpiry] = useState(0);
  const expiry = result?.key === key && result.state.status === "ready" ? result.state.session.expires_at : null;
  useEffect(() => {
    if (!expiry) return;
    const delay = Date.parse(expiry) - Date.now();
    if (!Number.isFinite(delay) || delay <= 0) return;
    const timer = setTimeout(() => refreshExpiry(n => n + 1), Math.min(delay + 1, 2147483647));
    return () => clearTimeout(timer);
  }, [expiry, key]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let sessionId: string | undefined;
    let keepPolling = true;
    const read = async () => {
      try {
        const state = blocked || !role ? { status: "unavailable" as const, reason: "최신 근거와 담당 역할을 확인해 주세요." }
          : await loadDecisionProposal({ ...scope, snapshotBasis: detail.snapshotBasis, role, sessionId }, controller.signal);
        if (state.status === "ready") sessionId = state.session.session_id;
        keepPolling = state.status === "ready";
        if (!controller.signal.aborted) setResult({ key, state });
      } catch {
        if (!controller.signal.aborted) setResult({ key, state: { status: "unavailable", reason: "판단 후보를 불러오지 못했습니다." } });
      } finally {
        if (!controller.signal.aborted && keepPolling) timer = setTimeout(() => void read(), 15000);
      }
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [key]);
  return validateDecisionState(result?.key === key ? result.state : { status: "loading" }, scope, detail);
}
function decisionNote(text: string): string {
  if (text.startsWith("Agent Review Packet is read-only")) return "판단 결과는 추천이며 작업 생성·승인·실행을 포함하지 않습니다.";
  if (text.startsWith("SOP grounding supports")) return "점검 절차는 검토 참고 근거이며 정비 작업 지시를 의미하지 않습니다.";
  if (text === "No matching scoped operational snapshot at the selected as-of; values withheld.") return "선택한 관측 시점에 맞는 운영 정보가 연결되지 않았습니다.";
  const owner = text.match(/'owner_domain': '(production|maintenance_readiness|quality_delivery)'/);
  if (owner && /'status': '(not_connected|missing)'/.test(text)) {
    return ({production:"생산 영향", maintenance_readiness:"정비 준비 상태", quality_delivery:"품질·납기"} as Record<string,string>)[owner[1]] + " 정보 확인 필요 · 선택한 관측 시점의 정보가 연결되지 않았습니다.";
  }
  return fieldText(text);
}
function FactGroup({ title, items, empty }: { title: string; items: DecisionConflict[]; empty: string }) {
  return <section className="dw-fact-group"><h3>{title}</h3>{items.length ? <ul>{items.map((f,i) => {
    const label = decisionNote(f.text);
    const comparison = f.comparison;
    return <li key={i}><span>{label}</span>{comparison && <p>생산 영향 산정: {comparison.planningMinutes}분 · 예상 정비 작업: {comparison.maintenanceMinutes}분</p>}{f.as_of && <small> · {formatTimestamp(f.as_of)}</small>}
      {label !== f.text && label !== fieldText(f.text) && <details><summary>원문</summary><p>{f.text}</p></details>}
      {f.evidence_refs.length > 0 && <details><summary>근거 출처</summary>{f.evidence_refs.map(ref => <p key={ref}>{ref}</p>)}</details>}</li>;
  })}</ul> : <p className="dw-muted">{empty}</p>}</section>;
}
export function DecisionConditions({ state, detail }: { state: DecisionProposalState; detail: OperationsEventDetailModel }) {
  const p = state.status === "ready" && ["ready_for_review", "abstained"].includes(state.session.status) ? state.session.proposal : null;
  const boundary = (f: DecisionFact) => f.text.startsWith("Agent Review Packet is read-only") || f.text.startsWith("SOP grounding supports");
  const uncertainties = p ? [...p.uncertainties, ...p.additional_information_needed] : detail.evidenceGaps.map(g => ({ text: g.reason, evidence_refs: [] }));
  return <div className="dw-decision-conditions" aria-label="구조화된 판단 조건">
    <p className="dw-muted">{p ? "AI가 확인한 판단 조건" : "운영 근거 · AI 확인 결과 미연결"}</p>
    <FactGroup title="확인됨" items={p?.confirmed_facts ?? []} empty="AI가 확인한 사실이 아직 없습니다." />
    <FactGroup title="미확인" items={uncertainties.filter(f => !boundary(f))} empty="등록된 미확인 항목이 없습니다." />
    <FactGroup title="충돌" items={p?.conflicts ?? []} empty={p ? "보고된 충돌이 없습니다." : "AI의 충돌 확인 결과가 아직 없습니다."} />
    {uncertainties.some(boundary) && <details><summary>판단 범위</summary><FactGroup title="검토 범위" items={uncertainties.filter(boundary)} empty="" /></details>}
  </div>;
}
const planningLabels: Record<PlanningCondition, string> = {
  production_impact: "생산 영향", expected_downtime: "예상 정지시간", maintenance_window: "가능 정비 시간",
  required_parts: "필요 부품·확보 상태", technician_readiness: "정비 인력 준비", concurrent_work: "동시 작업",
};
export function DecisionProposalPanel({ state, detail, roles, permissions, refreshing, onReview, onRetry }: {
  state: DecisionProposalState; detail: OperationsEventDetailModel; roles: string[]; permissions: string[]; refreshing: boolean;
  onReview: (actionId: string) => void; onRetry?: () => void;
}) {
  const [selection, setSelection] = useState<{ action: DecisionAction; revision: string } | null>(null);
  const revision = JSON.stringify([state, detail.snapshotBasis, detail.closedLoop?.availableActions, roles, permissions]);
  const selected = selection?.revision === revision ? selection.action : null;
  const options = proposalActions(state, roles, permissions);
  const session = state.status === "ready" ? state.session : null;
  const p = session && ["ready_for_review", "abstained"].includes(session.status) ? session.proposal : null;
  const execution = selected ? proposalExecution(state, selected, detail, roles, permissions) : null;
  return <section className="dw-proposal" aria-label="Decision Proposal">
    <h2>다음 판단</h2>
    {state.status === "loading" && <p role="status">판단 후보 연결을 확인하고 있습니다.</p>}
    {(state.status === "unavailable" || state.status === "stale") && <p role="status">{state.reason}</p>}
    {onRetry && (state.status === "unavailable" || state.status === "stale") && <button disabled={refreshing} onClick={onRetry}>다시 판단</button>}
    {session && <section aria-label="AI 판단 준비"><h3>{session.status === "ready_for_review" ? "조사 완료" : session.status === "abstained" ? "판단 보류" : session.status === "failed" ? "조사 확인 필요" : "AI 판단 준비"}</h3>
      <ul>{session.steps.map(step => <li key={step.id}>{({ completed: "✓", running: "→", pending: "○", failed: "!" })[step.status]} {step.label}</li>)}</ul>
      {session.status === "ready_for_review" && <p className="dw-muted">{session.steps.filter(s => s.status === "completed").length}개 운영 정보를 확인했습니다.</p>}
    </section>}
    {p && <>{p.abstain_reason && <p role="status">{fieldText(p.abstain_reason)}</p>}<p>{p.reasoning_summary}</p>{p.recommended_action && <p className="dw-muted">추천 신뢰도 · {({ low: "낮음", medium: "보통", high: "높음" })[p.confidence]}</p>}
      {options.map(o => <div key={o.action}><h3>{o.recommended ? "추천" : "대안"}</h3><button className={o.recommended ? "dw-primary" : ""} disabled={Boolean(o.reason) || refreshing} onClick={() => setSelection({ action: o.action, revision })}>{o.label}</button>{o.reason && <p className="dw-muted">{o.reason}</p>}</div>)}
      <FactGroup title="아직 확인 필요" items={p.additional_information_needed} empty="추가 요청된 정보가 없습니다." />
      <details><summary>추천 근거</summary>{p.evidence_refs.map(ref => <p key={ref}>{ref}</p>)}</details>
    </>}
    {selected && p && <section className="dw-human-review" aria-label="사용자 검토">
      <h3>사용자 검토 · {DECISION_ACTION_LABELS[selected]}</h3>
      <p>{p.reasoning_summary}</p>
      <p>관측 기준 · {formatTimestamp(detail.snapshotBasis?.observedAt ?? null)}</p>
      <p>사용자 승인 후 요청을 진행합니다. 요청 내용은 다음 작업 화면에서 확인하고 승인해 주세요.</p>
      {selected === "REVIEW_PLANNED_MAINTENANCE" && <dl>{Object.entries(planningLabels).map(([key,label]) => <div key={key}><dt>{label}</dt><dd>{p.planning_conditions?.[key as PlanningCondition]?.text ?? "추가 확인 필요"}</dd></div>)}</dl>}
      {selected === "REQUEST_MAINTENANCE" && <p>부품 교체는 정비 요청의 작업 범위에서 검토합니다.</p>}
      {execution ? <button disabled={refreshing} onClick={() => { if (!refreshing && execution) { onReview(execution.actionId); setSelection(null); } }}>검토 후 요청 내용 확인</button> : <p role="status">이 판단을 업무 요청으로 연결하는 승인 절차가 아직 연결되지 않았습니다.</p>}
      <button onClick={() => setSelection(null)}>선택 취소</button>
    </section>}
    {selection && !selected && <p role="status">판단 조건이 변경되었습니다. 후보를 다시 선택해 주세요.</p>}
  </section>;
}

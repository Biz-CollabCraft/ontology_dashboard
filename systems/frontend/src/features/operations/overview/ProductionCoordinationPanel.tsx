import { useCallback, useEffect, useRef, useState } from "react";
import { listInspectionCoordinations, requestInspectionCoordination, respondInspectionCoordination, type InspectionCoordination } from "../../../api";
import "./ProductionCoordinationPanel.css";
import "./ProductionReviewLayout.css";

const labels = { pending: "생산 관리자 확인 대기", confirmed: "생산 관리자 확인 완료", changes_requested: "재협의 필요" };
export function ProductionCoordinationPanel({ projectId, workspaceId, mode, workOrderId, canRequest = false, onStateChange, onConnectionChange, requestFormId, onRequestBusyChange }: {
  projectId: string; workspaceId: string; mode: "maintenance" | "production";
  workOrderId?: string; canRequest?: boolean; onStateChange?: (value: InspectionCoordination | null) => void;
  onConnectionChange?: (value: { workOrderId: string; state: "loading" | "online" | "offline" }) => void;
  requestFormId?: string; onRequestBusyChange?: (busy: boolean) => void;
}) {
  const [items, setItems] = useState<InspectionCoordination[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (workOrderId) onConnectionChange?.({ workOrderId, state: loading ? "loading" : error ? "offline" : "online" });
  }, [workOrderId, loading, error, onConnectionChange]);
  useEffect(() => {
    let alive = true;
    let inflight = false;
    async function load() {
      if (inflight) return;
      inflight = true;
      try {
        const data = await listInspectionCoordinations({ projectId, workspaceId });
        if (!alive) return;
        setItems(data.items); setError(false);
        onStateChange?.(data.items.find((entry) => entry.work_order_id === workOrderId) ?? null);
      } catch {
        if (alive) { setError(true); onStateChange?.(null); }
      } finally { inflight = false; if (alive) setLoading(false); }
    }
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => { alive = false; clearInterval(timer); };
  }, [projectId, workspaceId, workOrderId, revision, onStateChange]);
  const selected = mode === "maintenance" ? items.find((item) => item.work_order_id === workOrderId)
    : items.find((item) => item.work_order_id === selectedId) ?? items[0];
  const reload = useCallback(() => { onStateChange?.(null); setRevision((value) => value + 1); }, [onStateChange]);
  return <section className="production-coordination" aria-label="생산 협의 현황">
    <header><strong>정비 승인·작업 일정</strong>{!onConnectionChange ? <span role="status">{loading ? "연결 확인 중" : error ? "연결 확인 필요" : "연결 정상"}</span> : null}{mode === "production" ? <button type="button" onClick={reload}>새로고침</button> : null}</header>
    {error ? <p role="status">협의 현황을 불러오지 못했습니다. 저장된 이력은 유지됩니다.</p> : null}
    <div className="production-coordination-content">
      {mode === "production" ? <div className="production-coordination-list">
        {items.map((item) => <button type="button" key={item.work_order_id} aria-pressed={selected?.work_order_id === item.work_order_id} onClick={() => setSelectedId(item.work_order_id)}>
          <b>{item.asset_id}</b><span>{labels[item.status]} · {item.work_order_status === "completed" ? "점검 완료" : item.work_order_status === "in_progress" ? "작업 중" : "착수 전"}</span>
        </button>)}
        {!loading && !error && !items.length ? <p>현재 정비 승인 요청이 없습니다.</p> : null}
      </div> : null}
      {selected ? <article>
        <strong>{selected.asset_id} · {labels[selected.status]}</strong>
        <p>요청자 {selected.requested_by_name} · {new Date(selected.requested_at).toLocaleString("ko-KR")}</p>
        <dl><div><dt>정비 내용</dt><dd>{selected.request.work_summary}</dd></div><div><dt>예상 정지 시간</dt><dd>{selected.request.downtime_minutes}분</dd></div><div><dt>영향 품목</dt><dd>{selected.request.affected_items}</dd></div><div><dt>요청 메모</dt><dd>{selected.request.note || "없음"}</dd></div></dl>
        {selected.response ? <div className="coordination-response"><b>{labels[selected.status]}</b><p>생산 관리자 {selected.responded_by_name} · {new Date(selected.responded_at!).toLocaleString("ko-KR")}</p><p>일정: {selected.response.scheduled_window}</p><p>생산 대응: {selected.response.production_response}</p></div> : null}
        {selected.work_order_status === "in_progress" ? <p>보전팀 작업 진행 중</p> : null}
        {selected.inspection_result ? <div className="coordination-response"><b>점검 결과 반영 완료</b>{selected.inspection_result.findings.map((finding, index) => <p key={index}>{finding}</p>)}<p>{selected.inspection_result.note}</p></div> : null}
        {selected.history && selected.history.length > 1 ? <details><summary>협의 이력 {selected.history.length}건</summary>{selected.history.map((entry, index) => <p key={index}>{labels[entry.status]} · {entry.responded_by_name || entry.requested_by_name} · {entry.response?.production_response || entry.request.work_summary}</p>)}</details> : null}
      </article> : mode === "maintenance" && !loading && !error ? <p>접수 후 생산 관리자와 작업·정지 일정을 협의해 주세요.</p> : null}
      {mode === "maintenance" && canRequest && !loading && !error && selected?.status !== "pending" ? <CoordinationRequestForm key={workOrderId} projectId={projectId} workspaceId={workspaceId} workOrderId={workOrderId!} onSaved={reload} hasConfirmation={selected?.status === "confirmed"} externalFormId={requestFormId} onBusyChange={onRequestBusyChange} /> : null}
      {mode === "production" && selected?.status === "pending" && !error ? <CoordinationReplyForm key={selected.request_id} item={selected} projectId={projectId} workspaceId={workspaceId} onSaved={reload} /> : null}
    </div>
  </section>;
}

function useCommand() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const active = useRef(false);
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);
  async function run(payload: unknown, command: (key: string) => Promise<unknown>, saved: () => void) {
    if (active.current) return;
    active.current = true; setBusy(true); setMessage("");
    const fingerprint = JSON.stringify(payload);
    if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: Array.from(crypto.getRandomValues(new Uint32Array(4)), (v) => v.toString(16).padStart(8, "0")).join("") };
    try { await command(attempt.current.key); setMessage("저장했습니다. 상대 화면에도 반영됩니다."); saved(); }
    catch { setMessage("저장하지 못했습니다. 입력 내용은 유지됩니다. 최신 협의 상태를 확인한 뒤 다시 시도하세요."); }
    finally { active.current = false; setBusy(false); }
  }
  return { busy, message, run };
}

function CoordinationRequestForm({ projectId, workspaceId, workOrderId, onSaved, hasConfirmation, externalFormId, onBusyChange }: {
  projectId: string; workspaceId: string; workOrderId: string; onSaved: () => void; hasConfirmation: boolean;
  externalFormId?: string; onBusyChange?: (busy: boolean) => void;
}) {
  const [summary, setSummary] = useState("");
  const [downtime, setDowntime] = useState("");
  const [affected, setAffected] = useState("");
  const [note, setNote] = useState("");
  const { busy, message, run } = useCommand();
  const [validationMessage, setValidationMessage] = useState("");
  useEffect(() => { onBusyChange?.(busy); return () => onBusyChange?.(false); }, [busy, onBusyChange]);
  const payload = { work_summary: summary.trim(), downtime_minutes: Number(downtime), affected_items: affected.trim(), note: note.trim() };
  const valid = Boolean(summary.trim() && affected.trim() && downtime.trim() && Number.isInteger(Number(downtime)) && Number(downtime) >= 0 && Number(downtime) <= 43200);
  return <details className="coordination-request-form" open={!hasConfirmation}><summary>{hasConfirmation ? "작업 내용 변경·재협의 요청" : "정비 승인 요청 내용"}</summary>
    <form id={externalFormId} onSubmit={(event) => {
      event.preventDefault();
      if (!valid) { setValidationMessage("정비 내용, 예상 정지 시간, 영향 품목을 확인해 주세요."); return; }
      setValidationMessage("");
      void run(payload, (idempotencyKey) => requestInspectionCoordination({ projectId, workspaceId, workOrderId, payload, idempotencyKey }), onSaved);
    }}>
    {hasConfirmation ? <p>새 요청을 보내면 기존 확인은 이력으로 남고, 새 회신 전까지 시작할 수 없습니다.</p> : null}
    <label>정비 내용<textarea required maxLength={2000} value={summary} onChange={(e) => setSummary(e.target.value)} placeholder="어떤 부품을 어떻게 정비할지 작성하세요." disabled={busy}/></label>
    <label>예상 정지 시간(분)<input required type="number" min={0} max={43200} step={1} value={downtime} onChange={(e) => setDowntime(e.target.value)} disabled={busy}/></label>
    <label>영향 품목·생산 영향<textarea required maxLength={2000} value={affected} onChange={(e) => setAffected(e.target.value)} placeholder="영향이 없으면 '없음'을 명시하세요." disabled={busy}/></label>
    <label>협의 메모<textarea maxLength={4000} value={note} onChange={(e) => setNote(e.target.value)} disabled={busy}/></label>
    {!externalFormId ? <button type="submit" disabled={busy || !valid}>{busy ? "저장 중…" : "정비 승인 요청"}</button> : null}
    <p role="status">{validationMessage || message}</p>
    </form>
  </details>;
}

function CoordinationReplyForm({ item, projectId, workspaceId, onSaved }: {
  item: InspectionCoordination; projectId: string; workspaceId: string; onSaved: () => void;
}) {
  const [decision, setDecision] = useState<"confirmed" | "changes_requested" | "">("");
  const [window, setWindow] = useState("");
  const [response, setResponse] = useState("");
  const { busy, message, run } = useCommand();
  return <section className="coordination-reply-form">
    <strong>생산 관리자 회신</strong>
    <label>협의 결과<select value={decision} onChange={(e) => setDecision(e.target.value as typeof decision)} disabled={busy}><option value="">선택하세요</option><option value="confirmed">작업·정지 일정 확인</option><option value="changes_requested">재협의 요청</option></select></label>
    <label>협의된 일정·변경 요청 일정<input maxLength={1000} value={window} onChange={(e) => setWindow(e.target.value)} disabled={busy} placeholder="날짜·시각 또는 무정지 작업 여부"/></label>
    <label>생산 대응·회신 내용<textarea maxLength={4000} value={response} onChange={(e) => setResponse(e.target.value)} disabled={busy}/></label>
    <button type="button" disabled={busy || !decision || !window.trim() || !response.trim()} onClick={() => {
      if (!decision) return;
      const payload = { request_id: item.request_id, decision, scheduled_window: window.trim(), production_response: response.trim() };
      void run(payload, (idempotencyKey) => respondInspectionCoordination({ projectId, workspaceId, workOrderId: item.work_order_id, payload, idempotencyKey }), onSaved);
    }}>{busy ? "저장 중…" : "생산 대응·일정 회신 저장"}</button><p role="status">{message}</p>
  </section>;
}

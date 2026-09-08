import { useEffect, useRef, useState } from "react";
import { createOperationsAgentReviewSummary, getOperationsAgentReviewSummary } from "../../../api";
import type { OperationsAgentReviewSummary, OperationsAgentReviewSummaryResponse } from "../api/operationsContracts";
import { briefRows, relativeRecordTime, referenceLabels, readerLimitations } from "../../../standalone/briefFormat.js";
import "./NaturalBriefing.css";

type Props = {
  projectId: string; workspaceId: string; assetId: string; eventId: string | null;
  datasetVersionId?: string | null; observedAt?: string | null;
  role: "process_engineer" | "maintenance_technician" | "process_manager";
  canGenerate?: boolean; revision?: string;
  providedResponse?: OperationsAgentReviewSummaryResponse;
};

// A new selection is a new instance: old prose and pending responses cannot cross it.
export function NaturalBriefing(props: Props) {
  const revealed = useRef(new Set<string>());
  return <Briefing revealed={revealed.current} key={JSON.stringify([props.projectId, props.workspaceId, props.assetId, props.eventId,
    props.datasetVersionId, props.observedAt, props.role, props.revision, props.canGenerate, props.providedResponse?.trace.materialization?.summary_key, props.providedResponse?.trace.materialization?.status])} {...props}/>;
}

function accepted(response: OperationsAgentReviewSummaryResponse, assetId: string) {
  const summary = response.summary;
  return summary?.asset_id === assetId && summary.mode === "llm" && !response.trace.fallback
    && response.trace.materialization?.status === "ready" ? summary : null;
}

function Briefing(props: Props & { revealed: Set<string> }) {
  const supported = props.workspaceId === "manufacturing-demo" && Boolean(props.eventId);
  const [summary, setSummary] = useState<OperationsAgentReviewSummary | null>(null);
  const [status, setStatus] = useState(supported ? "브리핑 조회 중" : "선택한 근거에 연결된 브리핑이 없습니다.");
  const [busy, setBusy] = useState(supported);
  const controllerRef = useRef<AbortController | null>(null);
  const input = { assetId: props.assetId, eventId: props.eventId, projectId: props.projectId,
    datasetVersionId: props.datasetVersionId, historyWindow: "24h" };

  async function read(controller: AbortController) {
    const response = await getOperationsAgentReviewSummary({ ...input, signal: controller.signal });
    if (controller.signal.aborted) return;
    const next = accepted(response, props.assetId);
    setSummary(next);
    setStatus(next ? "저장된 브리핑" : response.trace.fallback ? "검증된 자연어 브리핑이 없습니다. 아래 판단 근거를 확인하세요." : "현재 근거의 브리핑이 아직 없습니다.");
  }
  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    if (props.providedResponse) {
      const next = accepted(props.providedResponse, props.assetId);
      setSummary(next); setBusy(false);
      setStatus(next ? "내용 검사 통과 · 기록된 응답" : props.providedResponse.trace.fallback ? "검증을 통과하지 못한 응답입니다. 판단 근거를 직접 확인하세요." : "현재 근거의 브리핑 검증을 기다리고 있습니다.");
    } else if (supported) void read(controller).catch(() => {
      if (!controller.signal.aborted) setStatus("브리핑을 불러오지 못했습니다. 판단 근거는 계속 확인할 수 있습니다.");
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, []);

  async function generate() {
    const controller = controllerRef.current;
    if (busy || !props.canGenerate || !supported || !controller || controller.signal.aborted) return;
    setBusy(true); setSummary(null); setStatus("현재 근거로 자연어 브리핑을 작성하고 있습니다.");
    try {
      const result = await createOperationsAgentReviewSummary({ ...input, signal: controller.signal });
      if (controller.signal.aborted) return;
      if (!accepted(result, props.assetId)) {
        setStatus("자연어 브리핑이 검증을 통과하지 못했습니다. 판단 근거를 확인하세요.");
      } else await read(controller);
    } catch {
      if (!controller.signal.aborted) setStatus("브리핑을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally { if (!controller.signal.aborted) setBusy(false); }
  }

  const quote = summary?.role_summaries.find(item => item.role === props.role)?.quote?.trim() || summary?.summary || "";
  const rows = briefRows(quote, summary?.source_refs ?? []);
  return <section className="natural-briefing" aria-label="AI 자연어 브리핑" aria-busy={busy}>
    <div className="natural-briefing-heading"><strong>AI 브리핑</strong>
      {supported && props.canGenerate ? <button type="button" disabled={busy} onClick={() => void generate()}>{busy ? "처리 중" : summary ? "다시 생성" : "브리핑 생성"}</button> : null}
    </div>
    <p className="natural-briefing-status" role="status">{status}</p>
    {summary ? <StreamingProse key={JSON.stringify([props.assetId, props.eventId, props.role, quote])}
      rows={rows} identity={JSON.stringify([props.projectId, props.workspaceId, props.assetId, props.eventId, props.role, quote])}
      revealed={props.revealed}/> : null}
    {summary ? <div className="natural-briefing-basis">{props.assetId}{props.observedAt ? <> · 관측 기준 <time dateTime={props.observedAt}>{relativeRecordTime(props.observedAt)}</time></> : null}
      {summary.limitations.length ? <details><summary>해석 시 유의사항</summary>{readerLimitations(summary.limitations).map((text, i) => <p key={i}>{text}</p>)}</details> : null}
    </div> : null}
  </section>;
}

// Reveal already validated prose locally; this does not stream unvalidated model tokens.
function StreamingProse({ rows, identity, revealed }: {
  rows: ReturnType<typeof briefRows>; identity: string; revealed: Set<string>;
}) {
  const total = rows.reduce((n, row) => n + row.parts.reduce((m, part) => m + Array.from(part.text).length, 0), 0);
  const [count, setCount] = useState(() => revealed.has(identity) || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? total : 0);
  useEffect(() => {
    const preference = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    let frame = 0;
    const finish = () => { cancelAnimationFrame(frame); revealed.add(identity); setCount(total); };
    const onPreference = () => { if (preference?.matches) finish(); };
    if (revealed.has(identity) || preference?.matches) { finish(); return; }
    const duration = Math.min(4800, Math.max(900, total * 12));
    let start: number | null = null;
    const step = (now: number) => {
      start ??= now;
      const progress = Math.min(1, (now - start) / duration);
      setCount(Math.floor(total * progress));
      if (progress < 1) frame = requestAnimationFrame(step);
      else revealed.add(identity);
    };
    frame = requestAnimationFrame(step);
    preference?.addEventListener("change", onPreference);
    return () => { cancelAnimationFrame(frame); preference?.removeEventListener("change", onPreference); };
  }, [identity, total, revealed]);
  let offset = 0;
  return <div className="natural-briefing-prose" data-streaming={count < total}>
    <div className="natural-briefing-accessible">{rows.map((row, i) => <p key={i}>{row.parts.map(p => p.text).join("")}</p>)}</div>
    {rows.map((row, index) => {
      const beginning = offset;
      const length = row.parts.reduce((n, part) => n + Array.from(part.text).length, 0);
      const end = beginning + length;
      const cursorHere = count >= beginning && (count < end || (index === rows.length - 1 && count === total));
      return <div className="natural-briefing-line" key={index}>
        <p aria-hidden="true">{row.parts.map((part, i) => {
          const letters = Array.from(part.text);
          const visible = Math.max(0, Math.min(letters.length, count - offset));
          const cursor = cursorHere && count >= offset && (count < offset + letters.length || (i === row.parts.length - 1 && count === end));
          offset += letters.length;
          const Tag = part.weight === "700" ? "strong" : "span";
          return <Tag key={i}>{letters.slice(0, visible).join("")}{cursor ? <span className="natural-briefing-cursor"/> : null}<span style={{visibility:"hidden"}}>{letters.slice(visible).join("")}</span></Tag>;
        })}</p>
        {row.refs.map((ref, i) => <details key={i} style={{visibility:count >= end ? "visible" : "hidden"}}><summary>근거</summary><p>{referenceLabels(ref.text).join(" · ")}</p></details>)}
      </div>;
    })}
  </div>;
}

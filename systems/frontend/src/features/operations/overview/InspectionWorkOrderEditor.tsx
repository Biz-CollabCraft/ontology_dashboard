import { useCallback, useEffect, useRef, useState, type ReactNode, type FormEvent } from "react";
import { executeInspectedMaintenance, acceptInspectionWorkOrder, startInspectionWorkOrder, completeInspectionWorkOrder, type OpenInspectionWorkOrderReadModel, type InspectionCompletionPayload, type InspectionOutcome, type InspectionChecklistStatus } from "../../../api";
import "./InspectionWorkOrderEditor.css";
import { ProductionCoordinationPanel } from "./ProductionCoordinationPanel";
import type { InspectionCoordination } from "../../../api";
import type { NaturalBriefingRefreshState } from "./NaturalBriefing";

// Retained for future maintenance-method recommendation input; hidden in the current UI.
const SHOW_RECOMMENDATION_INFO_REQUEST = false;

const checks = [
  ["equipment-condition", "설비 외관·이상 징후"],
  ["sensor-verification", "센서 값·현장 상태 대조"],
  ["parts-condition", "관련 부품 상태"],
] as const;

export function InspectionWorkOrderEditor({ briefing, item, currentUserId, projectId, workspaceId, onRefresh, onConnectionChange, onBriefingRefreshState }: {
  briefing?: ReactNode;
  item: OpenInspectionWorkOrderReadModel;
  currentUserId: string;
  projectId: string;
  workspaceId: string;
  onRefresh: () => void;
  onConnectionChange?: (value: { workOrderId: string; state: "loading" | "online" | "offline" }) => void;
  onBriefingRefreshState?: (state: NaturalBriefingRefreshState) => void;
}) {
  const [status, setStatus] = useState<string>(item.status);
  const [inspectionResult, setInspectionResult] = useState(item.inspection_result);
  const [coordination, setCoordination] = useState<InspectionCoordination | null>(null);
  const [coordinationConnection, setCoordinationConnection] = useState<"loading" | "online" | "offline">("loading");
  const [requestBusy, setRequestBusy] = useState(false);
  const requestFormId = `approval-request-${item.work_order_id}`;
  const handleConnectionChange = useCallback((value: { workOrderId: string; state: "loading" | "online" | "offline" }) => {
    setCoordinationConnection(value.state);
    onConnectionChange?.(value);
  }, [onConnectionChange]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [outcome, setOutcome] = useState<InspectionOutcome | "">("");
  const [checklist, setChecklist] = useState<Record<string, InspectionChecklistStatus | "">>({});
  const [findings, setFindings] = useState("");
  const [note, setNote] = useState("");
  const [measurements, setMeasurements] = useState<Record<string, string>>({});
  const [costBasis, setCostBasis] = useState<Record<string, string>>({});
  const isCnc = item.asset_type.toLowerCase() === "cnc" || item.asset_id.startsWith("CNC-");
  const equipmentChecks: ReadonlyArray<readonly [string, string]> = isCnc ? [["tool-wear", "공구 마모 상태"], ["cooling-path", "냉각 경로 상태"]] : checks;
  const measurementFields = isCnc ? [["tool_wear_min", "공구 누적 사용 시간", "min"], ["coolant_temperature_c", "냉각수 온도", "C"]] : [];
  const costFields = isCnc ? [["cost-basis-in-house", "사내 정비 수행 가능"], ["cost-basis-spare-part-available", "교체용 인서트 확보"], ["cost-basis-vendor-dispatch-required", "외부 업체 출동 필요"], ["cost-basis-component-replacement-required", "냉각 계통 부품 교체 필요"]] : [];
  const locked = useRef(false);
  // A retry of the same command keeps its key; edited results get a new key.
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);
  useEffect(() => { setStatus(item.status); }, [item.status]);
  useEffect(() => { setInspectionResult(item.inspection_result); }, [item.inspection_result]);
  const mine = Boolean(currentUserId && item.assigned_to === currentUserId);
  const canAct = Boolean(currentUserId && (status === "requested" || mine));
  const inspected = inspectionResult?.outcome === "maintenance_recommended";
  const canComplete = canAct && status === "in_progress" && !inspected;
  const approvalStage = inspected && status === "approved";
  const approvalUnavailable = approvalStage && coordinationConnection !== "online";
  const needsApprovalRequest = approvalStage && !approvalUnavailable && (!coordination || coordination.status === "changes_requested");
  const awaitingProduction = approvalStage && coordination?.status === "pending";
  const valid = Boolean(outcome && findings.trim() && equipmentChecks.every(([id]) => checklist[id]) && Object.values(measurements).every((value) => !value || Number.isFinite(Number(value))));
  const label = status === "completed" ? "결과 저장 완료" : status === "in_progress" ? (inspected ? "정비 진행 중" : "점검 진행 중") : status === "approved" ? (!inspected ? "접수 완료 · 점검 시작 대기" : approvalUnavailable ? "점검 완료 · 승인 상태 확인 필요" : needsApprovalRequest ? "점검 완료 · 정비 승인 요청 필요" : awaitingProduction ? "점검 완료 · 정비 승인 대기" : "정비 승인 완료 · 착수 대기") : "요청 접수 대기";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (locked.current || requestBusy || !canAct || approvalUnavailable || awaitingProduction || status === "completed" || (status === "in_progress" && (inspected ? !note.trim() : !valid))) return;
    // Approval fields have their own form and API; never start maintenance here.
    if (needsApprovalRequest) return;
    locked.current = true;
    setBusy(true);
    setMessage("");
    const payload: InspectionCompletionPayload = {
      outcome: outcome || "data_check_required",
      checklist: [
        ...equipmentChecks.map(([id, name]) => ({ item_id: id, status: checklist[id] || "not_checked" as InspectionChecklistStatus, note: name })),
        ...costFields.filter(([id]) => costBasis[id]).map(([id, name]) => ({ item_id: id, status: costBasis[id] as InspectionChecklistStatus, note: name })),
      ],
      measurements: measurementFields.filter(([id]) => measurements[id]?.trim()).map(([id, , unit]) => ({ name: id, value: Number(measurements[id]), unit })),
      findings: findings.split("\n").map((line) => line.trim()).filter(Boolean),
      note: note.trim(),
    };
    const fingerprint = JSON.stringify([item.work_order_id, status, status === "in_progress" ? payload : null]);
    if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: Array.from(crypto.getRandomValues(new Uint32Array(4)), (value) => value.toString(16).padStart(8, "0")).join("") };
    const input = { projectId, workspaceId, workOrderId: item.work_order_id, idempotencyKey: attempt.current.key };
    onBriefingRefreshState?.({ token: Date.now(), state: "pending" });
    try {
      let result: unknown;
      if (inspected) {
        result = await executeInspectedMaintenance({ ...input, payload: { action: status === "approved" ? "start" : "complete", note: note.trim() } });
        setStatus(status === "approved" ? "in_progress" : "completed");
        setMessage(status === "approved" ? "정비를 시작했습니다." : "정비 수행 결과를 저장하고 완료했습니다.");
      } else if (status === "requested") {
        result = await acceptInspectionWorkOrder(input);
        setMessage("요청을 접수했습니다. 목록 갱신 후 담당자와 작업 시작 상태를 확인하세요.");
      } else if (status === "approved") {
        result = await startInspectionWorkOrder(input);
        setStatus("in_progress");
        setMessage("현장 점검을 시작했습니다. 실제 확인한 결과를 아래에 작성하세요.");
      } else {
        result = await completeInspectionWorkOrder({ ...input, payload });
        setInspectionResult({ outcome: payload.outcome, findings: payload.findings, note: payload.note });
        setNote("");
        setStatus(outcome === "maintenance_recommended" ? "approved" : "completed");
        setMessage(outcome === "maintenance_recommended" ? "점검 결과를 저장했습니다. 정비 내용과 예상 정지 시간, 생산 영향을 작성한 뒤 정비 승인 요청을 보내세요." : "점검 결과를 저장했습니다. 조치 불필요로 종결하며 생산 관리자에게 승인 요청을 보내지 않습니다.");
      }
      onBriefingRefreshState?.({ token: Date.now(), state: briefingRefreshFailed(result) ? "failed" : "completed" });
      onRefresh();
    } catch {
      onBriefingRefreshState?.({ token: Date.now(), state: "failed" });
      setMessage("처리를 완료하지 못했습니다. 입력 내용은 유지됩니다. 연결 및 최신 담당·진행 상태를 확인한 뒤 다시 시도해 주세요.");
      onRefresh();
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }

  return <section className="inspection-work-editor" aria-label="작업 결과 작성">
    <header><strong>{item.equipment_id || item.asset_id}</strong><span>#{item.work_order_id.slice(-8)} · {label}</span></header>
    {briefing}
    <p>담당 {item.assigned_to_display_name || (item.assigned_to ? "담당 보전팀" : "배정 대기")}</p>
    {message ? <p role="status" className="inspection-work-message">{message}</p> : null}
    {!canAct && status !== "completed" ? <p>이 작업은 배정된 보전팀 담당자만 시작하고 결과를 기록할 수 있습니다.</p> : null}
    {inspectionResult ? <section aria-label="점검 결과"><strong>{inspected ? "점검 완료 · 정비 필요" : "점검 종결 · 조치 불필요"}</strong><p>{inspectionResult.findings.join(" / ")}</p></section> : null}
    {inspected ? <ProductionCoordinationPanel projectId={projectId} workspaceId={workspaceId} mode="maintenance" workOrderId={item.work_order_id} canRequest={mine && needsApprovalRequest} onStateChange={setCoordination} onConnectionChange={handleConnectionChange} requestFormId={requestFormId} onRequestBusyChange={setRequestBusy} onBriefingRefreshState={onBriefingRefreshState} /> : null}
    {approvalStage && !approvalUnavailable && coordination?.status === "confirmed" ? <p>생산 관리자 승인 완료 · 승인 일정과 착수 조건을 확인하고 정비를 시작하세요.</p> : null}
    <form onSubmit={(event) => void submit(event)}>
    {inspected && status === "in_progress" ? <label>정비 수행 결과<textarea required value={note} onChange={e => setNote(e.target.value)} placeholder="실제 수행한 정비와 결과를 작성하세요." /></label> : null}
    {canComplete ? <fieldset disabled={busy}>
      <legend>점검 결과</legend>
      <label>점검 판단<select required value={outcome} onChange={(event) => setOutcome(event.target.value as InspectionOutcome)}>
        <option value="">판단 선택</option>
        <option value="no_action_required">조치 불필요 · 점검 종결</option>
        <option value="maintenance_recommended">정비 필요 · 생산 관리자 승인 요청</option>
        {SHOW_RECOMMENDATION_INFO_REQUEST ? <option value="data_check_required">정비 방법 추천을 위한 정보 필요</option> : null}
      </select></label>
      {SHOW_RECOMMENDATION_INFO_REQUEST && outcome === "data_check_required" ? <p className="inspection-outcome-help">정비 방법 추천에 필요한 정보를 작성합니다.</p> : null}
      {equipmentChecks.map(([id, name]) => <label key={id}>{name}<select required value={checklist[id] || ""} onChange={(event) => setChecklist((previous) => ({ ...previous, [id]: event.target.value as InspectionChecklistStatus }))}>
        <option value="">점검 결과 선택</option><option value="pass">이상 없음</option><option value="fail">이상 확인</option><option value="not_checked">미점검</option>
      </select></label>)}
      {measurementFields.map(([id, name, unit]) => <label key={id}>{name} ({unit}, 선택 입력)<input type="number" step="any" value={measurements[id] || ""} onChange={(event) => setMeasurements((previous) => ({ ...previous, [id]: event.target.value }))} /></label>)}
      {costFields.map(([id, name]) => <label key={id}>{name}<select value={costBasis[id] || ""} onChange={(event) => setCostBasis((previous) => ({ ...previous, [id]: event.target.value }))}><option value="">미확인 · 산정에서 제외</option><option value="pass">예</option><option value="fail">아니요</option></select></label>)}
      <label>점검 확인 내용<textarea required value={findings} onChange={(event) => setFindings(event.target.value)} placeholder="점검에서 확인한 현상과 판단 근거를 작성하세요." /></label>
      <label>추가 메모<textarea maxLength={4000} value={note} onChange={(event) => setNote(event.target.value)} /></label>
      <p>점검 결과 기록이며, 실제 정비 완료나 효과 확인을 자동 처리하지 않습니다.</p>
    </fieldset> : null}
    {status !== "completed" ? <button type="submit" form={needsApprovalRequest ? requestFormId : undefined} disabled={busy || requestBusy || !canAct || approvalUnavailable || awaitingProduction || (status === "in_progress" && (inspected ? !note.trim() : !valid))}>
      {busy || requestBusy ? "처리 중…" : status === "requested" ? "점검 요청 접수" : approvalUnavailable ? "승인 상태 확인 필요" : needsApprovalRequest ? "정비 승인 요청" : awaitingProduction ? "정비 승인 확인 대기" : status === "approved" ? (inspected ? "정비 시작" : "점검 시작") : inspected ? "정비 완료" : outcome === "no_action_required" ? "점검 결과 저장 · 종결" : "점검 결과 저장"}
    </button> : null}
    </form>
  </section>;
}

function briefingRefreshFailed(value: unknown) {
  const refresh = (value as { agent_review_summary_refresh?: { status?: string } } | null)?.agent_review_summary_refresh;
  return Boolean(refresh && refresh.status === "failed");
}

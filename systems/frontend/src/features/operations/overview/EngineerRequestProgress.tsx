import { useEffect, useState } from "react";
import { listInspectionCoordinations, type InspectionCoordination, type OpenInspectionWorkOrderReadModel } from "../../../api";
import "./EngineerRequestProgress.css";

export function EngineerRequestProgress({ projectId, workspaceId, order, busy, connectionError }: {
  projectId: string; workspaceId: string; order?: OpenInspectionWorkOrderReadModel | null; busy: boolean; connectionError: boolean;
}) {
  const key = projectId + "|" + workspaceId + "|" + (order?.work_order_id ?? "");
  const [state, setState] = useState<{ key: string; status: InspectionCoordination["status"] | null; error: boolean } | null>(null);
  useEffect(() => {
    if (order?.status !== "approved") return;
    let alive = true, pending = false;
    async function load() {
      if (pending) return;
      pending = true;
      try {
        const result = await listInspectionCoordinations({ projectId, workspaceId });
        if (alive) setState({ key, status: result.items.find(item => item.work_order_id === order?.work_order_id)?.status ?? null, error: false });
      } catch { if (alive) setState({ key, status: null, error: true }); }
      finally { pending = false; }
    }
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => { alive = false; clearInterval(timer); };
  }, [key, order?.status]);
  const current = state?.key === key ? state : null;
  let title = "요청 전", next = "왼쪽에서 정비 승인 요청을 보낼 수 있습니다.", tone = "idle", step = "";
  if (busy) { title = "요청 전송 중"; next = "서버 접수 결과를 확인하고 있습니다."; tone = "waiting"; }
  else if (connectionError) { title = "진행 상태 확인 필요"; next = "연결 복구 후 최신 상태를 확인합니다."; tone = "attention"; }
  else if (order?.status === "requested") { title = "보전팀 접수 대기"; next = "요청 등록 완료 · 보전팀이 접수할 차례입니다."; tone = "waiting"; step = "1 / 4"; }
  else if (order?.status === "in_progress") { title = "보전팀 작업 진행 중"; next = "작업·점검 결과를 기록하는 단계입니다."; tone = "active"; step = "4 / 4"; }
  else if (order?.status === "approved") {
    step = "2 / 4"; tone = "waiting";
    if (!current) { title = "보전팀 접수 완료"; next = "생산 협의 상태를 확인하고 있습니다."; }
    else if (current.error) { title = "협의 상태 확인 필요"; next = "보전팀 접수 완료 · 생산관리자 연결 확인 필요"; tone = "attention"; }
    else if (current.status === "confirmed") { title = "작업 승인 완료"; next = "보전팀 착수 조건 확인 · 작업 시작 대기"; tone = "ready"; step = "3 / 4"; }
    else if (current.status === "changes_requested") { title = "생산 일정 재협의"; next = "보전팀이 수정된 협의안을 보낼 차례입니다."; tone = "attention"; step = "3 / 4"; }
    else if (current.status === "pending") { title = "생산관리자 확인 대기"; next = "작업·정지 일정 협의 요청이 전달됐습니다."; step = "3 / 4"; }
    else { title = "보전팀 접수 완료"; next = "생산관리자에게 작업·정지 일정을 협의할 차례입니다."; }
  }
  return <div className={"engineer-request-progress tone-" + tone} role="status" aria-live="polite" aria-label="정비 진행 상태">
    <span className="engineer-progress-caption">현재 단계 {step}</span><strong><i aria-hidden="true"/>{title}</strong><small>{next}</small>
  </div>;
}

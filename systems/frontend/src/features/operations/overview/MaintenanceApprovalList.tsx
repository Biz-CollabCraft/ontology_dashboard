import { useEffect, useState } from "react";
import { listInspectionCoordinations, type InspectionCoordination, type OpenInspectionWorkOrderReadModel } from "../../../api";
import "./MaintenanceRequestList.css";

export function MaintenanceApprovalList({ projectId, workspaceId, workOrders, workOrderError, selectedId, onSelect }: {
  projectId: string; workspaceId: string; workOrders: OpenInspectionWorkOrderReadModel[];
  workOrderError: boolean; selectedId?: string; onSelect: (id: string) => void;
}) {
  const [items, setItems] = useState<InspectionCoordination[]>([]);
  const [state, setState] = useState<"loading" | "online" | "offline">("loading");
  useEffect(() => {
    let alive = true, inflight = false;
    setItems([]); setState("loading");
    async function load() {
      if (inflight) return;
      inflight = true;
      try {
        const data = await listInspectionCoordinations({projectId, workspaceId});
        if (alive) {setItems(data.items);setState("online");}
      } catch {if (alive) setState("offline");}
      finally {inflight = false;}
    }
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => {alive = false;clearInterval(timer);};
  }, [projectId, workspaceId]);
  const approved = workOrders.filter(w => w.inspection_result?.outcome === "maintenance_recommended"
    && (w.status === "approved" || w.status === "in_progress")).map(order => ({order,
      coordination: items.find(c => c.work_order_id === order.work_order_id && c.asset_id === order.asset_id)}))
    .sort((a, b) => (a.order.created_at || "").localeCompare(b.order.created_at || "")
    || a.order.work_order_id.localeCompare(b.order.work_order_id));
  const connection = workOrderError ? "offline" : state;
  return <aside className="engineer-factory-card role-work-queue maintenance-approval-list" aria-label="정비 승인 목록">
    <header><strong>정비 승인 목록</strong><div className="maintenance-work-status"><span>요청 시간순</span>
      <span role="status" className={`maintenance-connection is-${connection}`}><i/>{connection === "online" ? "연결 정상" : connection === "loading" ? "연결 확인 중" : "연결 확인 필요"}</span>
    </div></header>
    <div>{connection === "loading" ? <p className="role-empty-state">승인 목록을 불러오는 중입니다.</p>
      : connection === "offline" ? <p className="role-empty-state">승인 목록 연결을 확인해 주세요.</p>
      : !approved.length ? <p className="role-empty-state">현재 정비가 필요한 점검 완료 건이 없습니다.</p>
      : approved.map(({order, coordination: c}) => <button type="button" className="maintenance-request-item" key={order.work_order_id}
        aria-pressed={selectedId === order.work_order_id} onClick={() => onSelect(order.work_order_id)}>
        <b>{order.equipment_id || order.asset_id}</b>
        <span className="maintenance-request-owner">담당 {order.assigned_to_display_name || (order.assigned_to ? "담당 보전팀" : "배정 대기")}</span>
        <small>#{order.work_order_id.slice(-8)}</small>
        <span className={`maintenance-request-state state-${order.status}`}>{order.status === "in_progress" ? "정비 진행 중" : !c ? "정비 필요 · 승인 요청 작성" : c.status === "pending" ? "생산 관리자 승인 대기" : c.status === "changes_requested" ? "재협의 요청 · 내용 수정 필요" : "정비 승인 완료 · 시작 대기"}</span>
        {c?.status === "confirmed" ? <small className="maintenance-approval-detail">승인 {c.responded_by_name || "생산 관리자"}{c.responded_at ? ` · ${new Date(c.responded_at).toLocaleString("ko-KR")}` : ""}</small> : null}
        <small className="maintenance-approval-detail">{c?.status === "confirmed" ? `승인 일정: ${c.response?.scheduled_window || "일정 확인 필요"}` : c ? `요청 정지 시간: ${c.request.downtime_minutes}분` : "점검 결과에 따른 정비 내용과 정지 시간을 작성하세요."}</small>
      </button>)}</div>
  </aside>;
}

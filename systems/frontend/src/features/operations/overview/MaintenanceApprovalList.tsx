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
  const approved = items.filter(c => c.status === "confirmed").flatMap(c => {
    const order = workOrders.find(w => w.work_order_id === c.work_order_id && w.asset_id === c.asset_id
      && (w.status === "approved" || w.status === "in_progress"));
    return order ? [{order, coordination: c}] : [];
  }).sort((a, b) => (a.coordination.responded_at || "").localeCompare(b.coordination.responded_at || "")
    || a.order.work_order_id.localeCompare(b.order.work_order_id));
  const connection = workOrderError ? "offline" : state;
  return <aside className="engineer-factory-card role-work-queue maintenance-approval-list" aria-label="보전 승인 목록">
    <header><strong>보전 승인 목록</strong><div className="maintenance-work-status"><span>승인 시간순</span>
      <span role="status" className={`maintenance-connection is-${connection}`}><i/>{connection === "online" ? "연결 정상" : connection === "loading" ? "연결 확인 중" : "연결 확인 필요"}</span>
    </div></header>
    <div>{connection === "loading" ? <p>승인 목록을 불러오는 중입니다.</p>
      : connection === "offline" ? <p>승인 목록 연결을 확인해 주세요.</p>
      : !approved.length ? <p>현재 생산 관리자가 승인한 작업이 없습니다.</p>
      : approved.map(({order, coordination: c}) => <button type="button" className="maintenance-request-item" key={order.work_order_id}
        aria-pressed={selectedId === order.work_order_id} onClick={() => onSelect(order.work_order_id)}>
        <b>{order.equipment_id || order.asset_id}</b>
        <span className="maintenance-request-owner">담당 {order.assigned_to_display_name || (order.assigned_to ? "담당 보전팀" : "배정 대기")}</span>
        <small>#{order.work_order_id.slice(-8)}</small>
        <span className={`maintenance-request-state state-${order.status}`}>{order.status === "in_progress" ? "작업 진행 중" : "생산 승인 완료"}</span>
        <small className="maintenance-approval-detail">승인 {c.responded_by_name || "생산 관리자"}{c.responded_at ? ` · ${new Date(c.responded_at).toLocaleString("ko-KR")}` : ""}</small>
        <small className="maintenance-approval-detail">작업 일정: {c.response?.scheduled_window || "일정 확인 필요"}</small>
      </button>)}</div>
  </aside>;
}

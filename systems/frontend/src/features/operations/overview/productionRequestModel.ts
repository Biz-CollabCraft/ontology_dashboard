import type { InspectionCoordination, MaintenanceCostAnalysisReadModel, OpenInspectionWorkOrderReadModel } from "../../../api";
export interface ProductionQueueItem {
  id: string; assetId: string; eventId: string; status: string; requestedAt: string | null;
  assignee: string; coordination: InspectionCoordination | null;
}
export function productionQueue(orders: OpenInspectionWorkOrderReadModel[], consultations: InspectionCoordination[]): ProductionQueueItem[] {
  const items = new Map<string, ProductionQueueItem>();
  for (const order of orders) items.set(order.work_order_id, {
    id: order.work_order_id, assetId: order.asset_id, eventId: order.event_id, status: order.status,
    requestedAt: order.assigned_at ?? null, assignee: order.assigned_to_display_name || "배정 대기", coordination: null,
  });
  for (const c of consultations) {
    const original = items.get(c.work_order_id);
    items.set(c.work_order_id, { id: c.work_order_id, assetId: c.asset_id, eventId: c.event_id,
      status: c.work_order_status ?? original?.status ?? "approved", requestedAt: c.requested_at,
      assignee: original?.assignee ?? c.requested_by_name, coordination: c });
  }
  return [...items.values()].sort((a,b) =>
    Number(a.status === "completed") - Number(b.status === "completed") ||
    (a.requestedAt ?? "9999").localeCompare(b.requestedAt ?? "9999") || a.id.localeCompare(b.id));
}
export function queueStatus(item: ProductionQueueItem) {
  if (item.status === "completed") return "점검 완료";
  if (item.status === "in_progress") return "작업 중";
  if (item.coordination?.status === "confirmed") return "작업 승인 완료";
  if (item.coordination?.status === "changes_requested") return "재협의 대기";
  if (item.coordination?.status === "pending") return "작업 승인 대기";
  return item.status === "requested" ? "보전팀 접수 대기" : "생산 협의 요청 대기";
}
export function matchingCostAnalysis(items: MaintenanceCostAnalysisReadModel[], selected: ProductionQueueItem) {
  return items.filter(a => a.asset_id === selected.assetId && a.based_on.inspection_work_order_id === selected.id)
    .sort((a,b) => b.calculated_at.localeCompare(a.calculated_at))[0] ?? null;
}
export function numeric(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
export function amount(value: number | null | undefined, analysis: MaintenanceCostAnalysisReadModel) {
  if (!numeric(value)) return "미산정";
  const major = value / 10 ** analysis.currency_minor_unit;
  try { return new Intl.NumberFormat("ko-KR", { style: "currency", currency: analysis.currency, maximumFractionDigits: analysis.currency_minor_unit }).format(major); }
  catch { return major.toLocaleString("ko-KR") + " " + analysis.currency; }
}

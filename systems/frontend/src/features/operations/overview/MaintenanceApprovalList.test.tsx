// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { MaintenanceApprovalList } from "./MaintenanceApprovalList";
import { listInspectionCoordinations } from "../../../api";
import type { ComponentProps } from "react";
vi.mock("../../../api", () => ({listInspectionCoordinations: vi.fn()}));
const order = (id: string) => ({work_order_id: id, asset_id: id, equipment_id: id, status:"approved", assigned_to_display_name:"김보전", inspection_result:{outcome:"maintenance_recommended",findings:["정비 필요"],note:""}});
const coordination = (id: string, status="confirmed") => ({work_order_id:id, asset_id:id, status, request:{downtime_minutes:30}, responded_by_name:"생산 담당자", responded_at:"2026-09-07T10:00:00Z", response:{scheduled_window:"오늘 14시"}});
let host: HTMLDivElement, root: Root;
const onSelect = vi.fn();
const props = {projectId:"p", workspaceId:"w", workOrders:[order("A"),order("B"),order("C")],workOrderError:false,onSelect} as unknown as ComponentProps<typeof MaintenanceApprovalList>;
beforeEach(() => {
  vi.useFakeTimers();vi.clearAllMocks();
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
});
afterEach(async () => {await act(async () => root.unmount());host.remove();vi.useRealTimers();});
async function render() {await act(async () => root.render(<MaintenanceApprovalList {...props}/>));}
it("shows drafting, pending and approved maintenance with exact asset matching", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValue({items:[coordination("A"),coordination("B","pending"),{...coordination("C"),asset_id:"wrong"},coordination("completed")]} as never);
  await render();
  expect(host.querySelectorAll(".maintenance-request-item")).toHaveLength(3);
  expect(host.textContent).toContain("정비 승인 완료 · 시작 대기");
  expect(host.textContent).toContain("생산 관리자 승인 대기");
  expect(host.textContent).toContain("정비 필요 · 승인 요청 작성");
  expect(host.textContent).toContain("오늘 14시");
  await act(async () => (host.querySelector(".maintenance-request-state") as HTMLElement).click());
  expect(onSelect).toHaveBeenCalledWith("A");
});
it("changes approval to reconsultation without losing the request", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValueOnce({items:[coordination("A")]} as never)
    .mockResolvedValue({items:[coordination("A","changes_requested")]} as never);
  await render();
  await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
  expect(host.querySelectorAll(".maintenance-request-item")).toHaveLength(3);
  expect(host.textContent).toContain("재협의 요청 · 내용 수정 필요");
  expect(host.textContent).not.toContain("정비 승인 완료 · 시작 대기");
});
it("does not expose stale approvals as actionable when disconnected", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValueOnce({items:[coordination("A")]} as never).mockRejectedValue(new Error("offline"));
  await render();await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
  expect(host.querySelectorAll(".maintenance-request-item")).toHaveLength(0);
  expect(host.textContent).toContain("연결 확인 필요");
});

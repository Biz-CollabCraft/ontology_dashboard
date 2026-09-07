// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { MaintenanceApprovalList } from "./MaintenanceApprovalList";
import { listInspectionCoordinations } from "../../../api";
import type { ComponentProps } from "react";
vi.mock("../../../api", () => ({listInspectionCoordinations: vi.fn()}));
const order = (id: string) => ({work_order_id: id, asset_id: id, equipment_id: id, status:"approved", assigned_to_display_name:"김보전"});
const coordination = (id: string, status="confirmed") => ({work_order_id:id, asset_id:id, status, responded_by_name:"생산 담당자", responded_at:"2026-09-07T10:00:00Z", response:{scheduled_window:"오늘 14시"}});
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
it("only shows production-confirmed open jobs matched by both job and asset", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValue({items:[coordination("A"),coordination("B","pending"),{...coordination("C"),asset_id:"wrong"},coordination("completed")]} as never);
  await render();
  expect(host.querySelectorAll(".maintenance-request-item")).toHaveLength(1);
  expect(host.textContent).toContain("생산 승인 완료");
  expect(host.textContent).toContain("오늘 14시");
  await act(async () => (host.querySelector(".maintenance-request-state") as HTMLElement).click());
  expect(onSelect).toHaveBeenCalledWith("A");
});
it("removes revoked approvals on automatic refresh", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValueOnce({items:[coordination("A")]} as never)
    .mockResolvedValue({items:[coordination("A","changes_requested")]} as never);
  await render();
  await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
  expect(host.querySelectorAll(".maintenance-request-item")).toHaveLength(0);
  expect(host.textContent).toContain("현재 생산 관리자가 승인한 작업이 없습니다");
});
it("does not expose stale approvals as actionable when disconnected", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValueOnce({items:[coordination("A")]} as never).mockRejectedValue(new Error("offline"));
  await render();await act(async () => {await vi.advanceTimersByTimeAsync(10000);});
  expect(host.querySelectorAll(".maintenance-request-item")).toHaveLength(0);
  expect(host.textContent).toContain("연결 확인 필요");
});

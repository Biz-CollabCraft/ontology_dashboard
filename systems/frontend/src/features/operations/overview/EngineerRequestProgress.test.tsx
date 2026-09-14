// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EngineerRequestProgress } from "./EngineerRequestProgress";
import { listInspectionCoordinations, type OpenInspectionWorkOrderReadModel, type InspectionCoordination } from "../../../api";
vi.mock("../../../api", () => ({ listInspectionCoordinations: vi.fn() }));
const order = { work_order_id: "job1", status: "approved", asset_id: "CNC1" } as OpenInspectionWorkOrderReadModel;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks(); vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [] });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function render(item: OpenInspectionWorkOrderReadModel | null = order, connectionError = false, busy = false) {
  await act(async () => root.render(<EngineerRequestProgress projectId="project" workspaceId="workspace" order={item} connectionError={connectionError} busy={busy}/>));
}
it("renders status text rather than an action button before a request", async () => {
  await render(null); expect(host.textContent).toContain("요청 전");
  expect(host.querySelector("button")).toBeNull();
  expect(host.querySelector('[role="status"]')).not.toBeNull();
  expect(listInspectionCoordinations).not.toHaveBeenCalled();
});
it.each([["requested", "보전팀 접수 대기"], ["in_progress", "보전팀 작업 진행 중"]] as const)("shows %s directly without an unnecessary consultation request", async (status, label) => {
  await render({ ...order, status }); expect(host.textContent).toContain(label);
  expect(listInspectionCoordinations).not.toHaveBeenCalled();
});
it.each([["pending", "생산관리자 확인 대기"], ["confirmed", "작업 승인 완료"], ["changes_requested", "생산 일정 재협의"]] as const)("distinguishes production state %s", async (status,label) => {
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [{ work_order_id: "job1", status } as InspectionCoordination] });
  await render(); expect(host.textContent).toContain(label);
  expect(listInspectionCoordinations).toHaveBeenCalledWith({ projectId: "project", workspaceId: "workspace" });
  expect(host.querySelector("button")).toBeNull();
});
it("does not mislabel technician acceptance as production approval", async () => {
  await render(); expect(host.textContent).toContain("보전팀 접수 완료"); expect(host.textContent).not.toContain("작업 승인 완료");
});
it("keeps connection failures separate from approval state", async () => {
  vi.mocked(listInspectionCoordinations).mockRejectedValue(new Error("private 503"));
  await render(); expect(host.textContent).toContain("협의 상태 확인 필요"); expect(host.textContent).not.toContain("private");
  await render(null, true); expect(host.textContent).toContain("진행 상태 확인 필요");
});

// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InspectionWorkOrderEditor } from "./InspectionWorkOrderEditor";
import { acceptInspectionWorkOrder, startInspectionWorkOrder, completeInspectionWorkOrder, type OpenInspectionWorkOrderReadModel } from "../../../api";
vi.mock("../../../api", () => ({ acceptInspectionWorkOrder: vi.fn(), startInspectionWorkOrder: vi.fn(), completeInspectionWorkOrder: vi.fn() }));
const order: OpenInspectionWorkOrderReadModel = { work_order_id: "INSPECTION-12345678", event_id: "FILE#observation", asset_id: "CMP-S01-L01-01", equipment_id: "압축기 1", asset_type: "COMPRESSOR", work_type: "inspection", status: "approved", assigned_to: "technician", assigned_to_display_name: "보전 담당자" };
let host: HTMLDivElement;
let root: Root;
const refresh = vi.fn();
async function render(item = order, currentUserId = "technician") {
  await act(async () => root.render(<InspectionWorkOrderEditor item={item} currentUserId={currentUserId} projectId="project" workspaceId="workspace" onRefresh={refresh}/>));
}
async function submit() {
  await act(async () => { host.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
}
async function fill() {
  await act(async () => {
    host.querySelectorAll("select").forEach((select, index) => {
      select.value = index === 0 ? "maintenance_recommended" : "pass";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const textarea = host.querySelector("textarea")!;
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea, "현장 압력 확인 및 필터 점검");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks();
  vi.mocked(acceptInspectionWorkOrder).mockResolvedValue({});
  vi.mocked(startInspectionWorkOrder).mockResolvedValue({});
  vi.mocked(completeInspectionWorkOrder).mockResolvedValue({});
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
describe("inspection result workflow", () => {
  it("accepts a new request through the scoped API", async () => {
    await render({ ...order, status: "requested", assigned_to: null }); await submit();
    expect(acceptInspectionWorkOrder).toHaveBeenCalledWith(expect.objectContaining({ projectId: "project", workspaceId: "workspace", workOrderId: order.work_order_id }));
    expect(refresh).toHaveBeenCalled();
  });
  it("opens result entry only after an assigned approved job is started", async () => {
    await render(); expect(host.querySelector("textarea")).toBeNull(); await submit();
    expect(startInspectionWorkOrder).toHaveBeenCalledOnce();
    expect(host.querySelector("textarea")).not.toBeNull();
    expect(completeInspectionWorkOrder).not.toHaveBeenCalled();
  });
  it("prevents another technician from starting or completing the job", async () => {
    await render(order, "other"); await submit(); expect(startInspectionWorkOrder).not.toHaveBeenCalled();
    await render({ ...order, status: "in_progress" }, "other"); await submit();
    expect(completeInspectionWorkOrder).not.toHaveBeenCalled(); expect(host.textContent).toContain("배정된 보전팀");
  });
  it("requires explicit findings, outcome and checklist before submitting", async () => {
    await render({ ...order, status: "in_progress" }); await submit();
    expect(completeInspectionWorkOrder).not.toHaveBeenCalled();
    await fill(); await submit();
    expect(completeInspectionWorkOrder).toHaveBeenCalledWith(expect.objectContaining({ workOrderId: order.work_order_id, payload: expect.objectContaining({ outcome: "maintenance_recommended", findings: ["현장 압력 확인 및 필터 점검"], measurements: [], checklist: expect.arrayContaining([expect.objectContaining({ item_id: "equipment-condition", status: "pass" })]) }) }));
    expect(host.textContent).toContain("결과를 저장했습니다");
  });
  it("keeps drafts on polling refresh and failed saves, reusing the retry key", async () => {
    await render({ ...order, status: "in_progress" }); await fill();
    await render({ ...order, status: "in_progress" });
    expect(host.querySelector("textarea")!.value).toContain("현장 압력");
    vi.mocked(completeInspectionWorkOrder).mockRejectedValueOnce(new Error("private internal 503"));
    await submit();
    expect(host.textContent).not.toContain("private internal");
    expect(host.querySelector("textarea")!.value).toContain("현장 압력");
    const firstKey = vi.mocked(completeInspectionWorkOrder).mock.calls[0][0].idempotencyKey;
    await submit();
    expect(vi.mocked(completeInspectionWorkOrder).mock.calls[1][0].idempotencyKey).toBe(firstKey);
  });
  it("does not send duplicate completion commands while a save is pending", async () => {
    await render({ ...order, status: "in_progress" }); await fill();
    let finish!: (value: Record<string, unknown>) => void;
    vi.mocked(completeInspectionWorkOrder).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    await submit(); await submit(); expect(completeInspectionWorkOrder).toHaveBeenCalledOnce();
    await act(async () => finish({}));
  });
  it("preserves CNC checklist and cost-basis contract keys", async () => {
    await render({ ...order, asset_id: "CNC-S02-L02-04", asset_type: "cnc", status: "in_progress" });
    await fill(); await submit();
    expect(completeInspectionWorkOrder).toHaveBeenCalledWith(expect.objectContaining({ payload: expect.objectContaining({ checklist: expect.arrayContaining([expect.objectContaining({ item_id: "tool-wear", status: "pass" }), expect.objectContaining({ item_id: "cooling-path", status: "pass" }), expect.objectContaining({ item_id: "cost-basis-in-house", status: "pass" })]) }) }));
  });
  it("records additional-data findings as a completed inspection, not an unfinished checklist", async () => {
    await render({ ...order, status: "in_progress" });
    await fill();
    await act(async () => {
      const selects = host.querySelectorAll("select");
      selects[0].value = "data_check_required";
      selects[0].dispatchEvent(new Event("change", { bubbles: true }));
      selects[1].value = "not_checked";
      selects[1].dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.textContent).toContain("추가 데이터 확인 필요");
    expect(host.textContent).not.toContain("데이터·센서 재확인 필요");
    expect(host.textContent).toContain("정비 승인이나 실제 정비 완료를 의미하지 않습니다");
    await submit();
    expect(completeInspectionWorkOrder).toHaveBeenCalledWith(expect.objectContaining({
      payload: expect.objectContaining({ outcome: "data_check_required", checklist: expect.arrayContaining([expect.objectContaining({ status: "not_checked" })]) })
    }));
    expect(host.textContent).toContain("결과 저장 완료");
    expect(startInspectionWorkOrder).not.toHaveBeenCalled();
    expect(acceptInspectionWorkOrder).not.toHaveBeenCalled();
  });
  it("does not pretend a failed start entered the in-progress state", async () => {
    vi.mocked(startInspectionWorkOrder).mockRejectedValueOnce(new Error("conflict"));
    await render(); await submit(); expect(host.querySelector("textarea")).toBeNull();
    expect(host.textContent).toContain("입력 내용은 유지");
  });
});

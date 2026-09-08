// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductionCoordinationPanel } from "./ProductionCoordinationPanel";
import { listInspectionCoordinations, requestInspectionCoordination, respondInspectionCoordination, type InspectionCoordination } from "../../../api";
vi.mock("../../../api", () => ({ listInspectionCoordinations: vi.fn(), requestInspectionCoordination: vi.fn(), respondInspectionCoordination: vi.fn() }));
const entry: InspectionCoordination = {
  work_order_id: "inspection-1", asset_id: "CNC-1", event_id: "event-1", request_id: "request-1",
  status: "pending", work_order_status: "approved",
  request: { work_summary: "공구 점검", downtime_minutes: 30, affected_items: "품목 A", note: "교대 시간" },
  requested_by: "technician", requested_by_name: "보전 담당", requested_at: "2026-09-07T01:00:00Z",
  response: null, responded_by: null, responded_by_name: null, responded_at: null,
};
let host: HTMLDivElement;
let root: Root;
const changed = vi.fn();
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks();
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [] });
  vi.mocked(requestInspectionCoordination).mockResolvedValue({ ...entry });
  vi.mocked(respondInspectionCoordination).mockResolvedValue({ ...entry });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function render(mode: "maintenance" | "production" = "maintenance") {
  await act(async () => root.render(<ProductionCoordinationPanel mode={mode} projectId="project" workspaceId="workspace" workOrderId="inspection-1" canRequest onStateChange={changed}/>));
}
async function input(text: string, value: string) {
  const label = Array.from(host.querySelectorAll("label")).find((node) => node.textContent?.startsWith(text))!;
  const field = label.querySelector("input,textarea,select") as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value")!.set!.call(field, value);
    field.dispatchEvent(new Event(field.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
}
async function click(text: string) {
  const button = Array.from(host.querySelectorAll("button")).find((node) => node.textContent === text)!;
  await act(async () => button.click());
}
it("sends a scoped request, keeps input on failure and reuses its retry key", async () => {
  await render();
  await input("작업 내용", "공구 점검"); await input("예상 정지", "30"); await input("영향 품목", "품목 A");
  vi.mocked(requestInspectionCoordination).mockRejectedValueOnce(new Error("private failure"));
  await click("정비 승인 요청");
  expect(host.textContent).not.toContain("private failure");
  expect((host.querySelector("textarea") as HTMLTextAreaElement).value).toBe("공구 점검");
  const first = vi.mocked(requestInspectionCoordination).mock.calls[0][0];
  expect(first).toEqual(expect.objectContaining({ projectId: "project", workspaceId: "workspace", workOrderId: "inspection-1", payload: { work_summary: "공구 점검", downtime_minutes: 30, affected_items: "품목 A", note: "" } }));
  await click("정비 승인 요청");
  expect(vi.mocked(requestInspectionCoordination).mock.calls[1][0].idempotencyKey).toBe(first.idempotencyKey);
});
it("saves an explicit production reply bound to the selected request revision", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [entry] });
  await render("production");
  const save = Array.from(host.querySelectorAll("button")).find((node) => node.textContent === "생산 대응·일정 회신 저장")!;
  expect(save.disabled).toBe(true);
  await input("협의 결과", "confirmed"); await input("협의된 일정", "9월 8일 13:00"); await input("생산 대응", "대체 라인 생산");
  await click("생산 대응·일정 회신 저장");
  expect(respondInspectionCoordination).toHaveBeenCalledWith(expect.objectContaining({
    workOrderId: "inspection-1", projectId: "project", workspaceId: "workspace",
    payload: { request_id: "request-1", decision: "confirmed", scheduled_window: "9월 8일 13:00", production_response: "대체 라인 생산" },
  }));
});
it("reloads completed work and its saved confirmation and result", async () => {
  const confirmed = { ...entry, status: "confirmed" as const, work_order_status: "completed",
    response: { request_id: entry.request_id, decision: "confirmed" as const, scheduled_window: "13:00", production_response: "대체 생산" },
    responded_by: "manager", responded_by_name: "생산 담당", responded_at: "2026-09-07T02:00:00Z",
    history: [entry], inspection_result: { outcome: "no_action_required" as const, findings: ["현장 이상 없음"], note: "점검 완료" } };
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [confirmed] });
  await render("production");
  expect(host.textContent).toContain("생산 관리자 확인 완료");
  expect(host.textContent).toContain("생산 담당");
  expect(host.textContent).toContain("현장 이상 없음");
  expect(host.querySelector(".coordination-reply-form")).toBeNull();
});
it("fails closed when consultation connection cannot be checked", async () => {
  vi.mocked(listInspectionCoordinations).mockRejectedValue(new Error("internal 503"));
  await render();
  expect(changed).toHaveBeenLastCalledWith(null);
  expect(host.textContent).toContain("연결 확인 필요");
  expect(host.textContent).not.toContain("internal 503");
  expect(host.querySelector(".coordination-request-form")).toBeNull();
});

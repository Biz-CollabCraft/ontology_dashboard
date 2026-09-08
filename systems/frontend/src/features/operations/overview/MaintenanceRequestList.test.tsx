// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { RoleFactoryStandalone } from "./RoleFactoryStandalone";
import type { ComponentProps } from "react";
vi.mock("./ProductionRequestBoard", () => ({ ProductionRequestBoard: () => null }));
vi.mock("./InspectionWorkOrderEditor", () => ({ InspectionWorkOrderEditor: (props: { item: {work_order_id: string}; onConnectionChange: (value: unknown) => void }) =>
  <div data-editor={props.item.work_order_id}><span>협의 요청서 {props.item.work_order_id}</span><button onClick={() => props.onConnectionChange({workOrderId: props.item.work_order_id, state: "offline"})}>연결 실패 모의</button></div>
}));
let host: HTMLDivElement, root: Root;
const props = {
  persona: "maintenance", projectId: "p", workspaceId: "w", currentUserId: "user",
  currentUser: {displayName: "현장 관리자", title: "보전팀"},
  model: { context: {workspaceName: "공장"}, assets: [], metrics: {estimatedDowntimeMinutes: null}},
  workOrders: [
    {work_order_id:"job-11111111",asset_id:"CNC-1",equipment_id:"CNC-1",status:"approved",assigned_to:"user",assigned_to_display_name:"현장 관리자"},
    {work_order_id:"job-22222222",asset_id:"CMP-2",equipment_id:"CMP-2",status:"approved",assigned_to:"user",assigned_to_display_name:"김보전"},
  ], workOrderError: false, onRefresh: vi.fn(), onLogout: vi.fn(),
} as unknown as ComponentProps<typeof RoleFactoryStandalone>;
beforeEach(async () => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  host = document.createElement("div");document.body.append(host);root = createRoot(host);
  await act(async () => root.render(<RoleFactoryStandalone {...props}/>));
});
afterEach(async () => {await act(async () => root.unmount());host.remove();});
it("uses a full-row selection control, right-side owner and non-button status", async () => {
  expect(host.textContent).toContain("점검 요청 목록");
  expect(host.textContent).not.toContain("보전 요청 큐");
  expect(host.querySelector(".engineer-factory-header")?.textContent).toContain("새로고침");
  expect(host.querySelector("[data-editor]")).toBeNull();
  const rows = host.querySelectorAll<HTMLButtonElement>(".maintenance-request-item");
  expect(rows).toHaveLength(2);
  expect(rows[1].querySelector("button")).toBeNull();
  expect(rows[1].querySelector(".maintenance-request-owner")?.textContent).toBe("담당 김보전");
  expect(rows[1].querySelector(".maintenance-request-state")?.tagName).toBe("SPAN");
  await act(async () => (rows[1].querySelector("b") as HTMLElement).click());
  expect(host.querySelector("[data-editor]")?.getAttribute("data-editor")).toBe("job-22222222");
  expect(rows[1].getAttribute("aria-pressed")).toBe("true");
  await act(async () => (rows[0].querySelector(".maintenance-request-state") as HTMLElement).click());
  expect(host.querySelector("[data-editor]")?.getAttribute("data-editor")).toBe("job-11111111");
});
it("places connection feedback after the workflow caption and reflects failure", async () => {
  const header = host.querySelector(".role-primary-work>header")!;
  expect(header.textContent).toContain("업무 단계별 확인연결 정상");
  await act(async () => host.querySelector<HTMLButtonElement>(".maintenance-request-item")!.click());
  expect(header.textContent).toContain("업무 단계별 확인연결 확인 중");
  await act(async () => host.querySelector<HTMLButtonElement>("[data-editor] button")!.click());
  expect(header.querySelector('[role="status"]')?.textContent).toBe("연결 확인 필요");
  expect(header.querySelector(".is-offline")).not.toBeNull();
});

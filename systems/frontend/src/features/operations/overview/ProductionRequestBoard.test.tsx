// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
// These workflow fixtures render outside the application preferences provider.
vi.mock("../../../ui/foundry/displayPreferences", () => ({ useDisplayPreferences: () => ({ preferences: { theme: "light" }, setTheme: vi.fn() }) }));
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ProductionRequestBoard } from "./ProductionRequestBoard";
import { listInspectionCoordinations, getMaintenanceEventLineage, respondInspectionCoordination, type InspectionCoordination, type MaintenanceCostAnalysisReadModel, type OpenInspectionWorkOrderReadModel } from "../../../api";
import { loadOperationsAssetDetail } from "../api/operationsApi";
import type { OperationsBootstrapModel, AssetDetailViewModel } from "../api/operationsContracts";
import { amount, matchingCostAnalysis, productionQueue, sortProductionQueue } from "./productionRequestModel";
vi.mock("../../../api", () => ({ listInspectionCoordinations: vi.fn(), getMaintenanceEventLineage: vi.fn(), respondInspectionCoordination: vi.fn() }));
vi.mock("../api/operationsApi", () => ({ loadOperationsAssetDetail: vi.fn() }));
const first: InspectionCoordination = {
  work_order_id: "inspection-11111111", asset_id: "CNC-A", event_id: "event-A", request_id: "request-A", status: "pending", work_order_status: "approved",
  request: { work_summary: "공구 점검 A", downtime_minutes: 30, affected_items: "품목 A", note: "" }, requested_by: "tech", requested_by_name: "김보전", requested_at: "2026-09-07T01:00:00Z",
  response: null, responded_at: null, responded_by: null, responded_by_name: null,
};
const second = { ...first, work_order_id: "inspection-22222222", asset_id: "CMP-B", event_id: "event-B", request_id: "request-B", requested_at: "2026-09-07T02:00:00Z",
  request: { ...first.request, work_summary: "압축기 점검 B", affected_items: "품목 B" } };
const model = { context: { workspaceName: "생산", datasetVersionId: "dataset" }, assets: [
  { assetId: "CNC-A", displayName: "정상 CNC", status: "normal", failureProbability: .1, riskHistory: [{ value: .1 }] },
  { assetId: "CMP-B", displayName: "압축기 B", status: "normal", failureProbability: .2, riskHistory: [{ value: .2 }] },
  { assetId: "unrequested-risk-A", displayName: "위험 설비 A", status: "critical", line: "S01", failureProbability: .9 },
  { assetId: "unrequested-risk-B", displayName: "위험 설비 B", status: "attention", line: "S01", failureProbability: .5 },
] , metrics: { estimatedDowntimeMinutes: 105 } } as unknown as OperationsBootstrapModel;
function detail(assetId = "CNC-A", units = 111): AssetDetailViewModel {
  return { asset: { asset_id: assetId, observed_at: "2026-09-07T01:00:00Z" }, risk: { current: .1 }, risk_series: [], features: [],
    operation_context: { production_plan: { planned_units: units, plan_date: "2026-09-07" }, capacity_model: { asset_units_per_hour: 60 }, event_impact: { estimated_lost_units: 40, product_variant: "A" } }
  } as unknown as AssetDetailViewModel;
}
const lineage = { event_id: "event-A", work_orders: [], inspection_results: [], recommendations: [], cost_analyses: [] };
let host: HTMLDivElement, root: Root;
const refresh = vi.fn();
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks();
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [first, second] });
  vi.mocked(getMaintenanceEventLineage).mockResolvedValue(lineage);
  vi.mocked(loadOperationsAssetDetail).mockImplementation(async (_p,_w,id) => detail(id, id === "CNC-A" ? 111 : 222));
  vi.mocked(respondInspectionCoordination).mockImplementation(async input => ({ ...first, status: input.payload.decision, response: input.payload, responded_by_name: "박생산", responded_at: "2026-09-07T03:00:00Z" }));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function render(orders: OpenInspectionWorkOrderReadModel[] = []) {
  await act(async () => root.render(<ProductionRequestBoard projectId="project" workspaceId="workspace" model={model} workOrders={orders} workOrderError={false} currentUser={{ displayName: "박생산", title: "생산관리자" }} onRefresh={refresh} onLogout={vi.fn()}/>));
}
async function click(name: string) {
  await act(async () => Array.from(host.querySelectorAll("button")).find(b => b.textContent === name)!.click());
}
async function fill(label: string, value: string) {
  const field = Array.from(host.querySelectorAll("label")).find(n => n.textContent?.startsWith(label))!.querySelector("input,textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value")!.set!.call(field,value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function chooseB() { await act(async () => Array.from(host.querySelectorAll<HTMLButtonElement>(".prb-queue-item")).find(b => b.textContent?.includes("압축기 B"))!.click()); }
it("shows the request list with risk above sensor trends and approval review at right", async () => {
  await render();
  expect(host.querySelector(".prb-queue-item")?.textContent).toContain("정상 CNC");
  expect(host.textContent).not.toContain("생산 영향 우선순위");
  expect(host.querySelector(".prb-monitoring-stack")?.firstElementChild?.className).toBe("prb-risk");
  expect(host.querySelector(".prb-monitoring-stack")?.children).toHaveLength(1);
  expect(host.querySelector('[aria-label="가정 기반 비용 참고"]')).toBeNull();
  expect(host.querySelector(".prb-queue>header strong")?.textContent).toBe("정비 승인 요청 목록");
  expect(host.querySelector(".prb-actions>header strong")?.textContent).toBe("작업 승인 검토");
  expect(host.querySelector(".prb-action-buttons")?.children[0].textContent).toBe("선택 설비 영향 확인");
  expect(host.querySelector(".prb-action-buttons")?.children[1].textContent).toBe("작업 승인");
  expect(host.textContent).toContain("30개");
  expect(host.textContent).toContain("박생산");
});
it("changes the queue, impact drawer and approval target together without opening the drawer on selection", async () => {
  await render(); await chooseB();
  expect(host.querySelector('[role="dialog"]')).toBeNull();
  await click("선택 설비 영향 확인");
  expect(host.querySelector('[role="dialog"]')?.getAttribute("aria-label")).toContain("압축기 B");
  expect(host.querySelector('[role="dialog"]')?.textContent).toContain("222개");
  expect(loadOperationsAssetDetail).toHaveBeenLastCalledWith("project", "workspace", "CMP-B", "event-B", "dataset", "24h");
  expect(respondInspectionCoordination).not.toHaveBeenCalled();
});
it("never shows the previous equipment numbers while a new detail request is pending", async () => {
  await render();
  expect(host.querySelector(".prb-impact-kpis")?.textContent).toContain("111개");
  vi.mocked(loadOperationsAssetDetail).mockImplementation(() => new Promise(() => {}));
  await chooseB();
  expect(host.querySelector(".prb-impact-kpis")?.textContent).not.toContain("111개");
  expect(host.querySelector(".prb-impact-kpis")?.textContent).toContain("조회 중");
});
it("requires explicit schedule and note, preserves failed input and retries with the same idempotency key", async () => {
  await render(); await chooseB();
  const button = host.querySelector<HTMLButtonElement>(".prb-approve")!;
  expect(button.disabled).toBe(true);
  await fill("작업·정지 일정", "9월 8일 13시"); await fill("생산 대응·승인 근거", "대체 라인으로 생산");
  vi.mocked(respondInspectionCoordination).mockRejectedValueOnce(new Error("private 503"));
  await click("작업 승인");
  expect(host.textContent).not.toContain("private 503");
  expect(host.querySelector("textarea")?.value).toBe("대체 라인으로 생산");
  const sent = vi.mocked(respondInspectionCoordination).mock.calls[0][0];
  expect(sent).toEqual(expect.objectContaining({ workOrderId: second.work_order_id, payload: { request_id: "request-B", decision: "confirmed", scheduled_window: "9월 8일 13시", production_response: "대체 라인으로 생산" } }));
  await click("작업 승인");
  expect(vi.mocked(respondInspectionCoordination).mock.calls[1][0].idempotencyKey).toBe(sent.idempotencyKey);
});
it("prevents duplicate approval while saving and keeps change requests separate", async () => {
  await render(); await fill("작업·정지 일정", "내일 오전"); await fill("생산 대응·승인 근거", "납기 확인 필요");
  let finish!: (value: Record<string,unknown>) => void;
  vi.mocked(respondInspectionCoordination).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  await click("재협의 요청"); await click("저장 중…");
  expect(respondInspectionCoordination).toHaveBeenCalledOnce();
  expect(vi.mocked(respondInspectionCoordination).mock.calls[0][0].payload.decision).toBe("changes_requested");
  await act(async () => finish({ ...first, status: "changes_requested" }));
});
it("cannot approve a request without a production consultation or when connection fails", async () => {
  vi.mocked(listInspectionCoordinations).mockRejectedValue(new Error("private error"));
  await render([{ work_order_id: first.work_order_id, asset_id: first.asset_id, event_id: first.event_id, status: "approved", work_type: "inspection", equipment_id: first.asset_id, asset_type: "cnc" }]);
  expect(host.querySelector<HTMLButtonElement>(".prb-approve")).toBeNull();
  expect(host.textContent).toContain("연결");
  expect(host.textContent).not.toContain("private error");
});
it("retains saved approvals and completed findings when completed history is included", async () => {
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [{ ...first, status: "confirmed", work_order_status: "completed",
    responded_by_name: "박생산", responded_at: "2026-09-07T03:00:00Z", response: { request_id: "request-A", decision: "confirmed", scheduled_window: "오후 1시", production_response: "대체 생산" },
    inspection_result: { outcome: "no_action_required", findings: ["정상 확인"], note: "점검 종료" } }] });
  await render();
  expect(host.textContent).toContain("현재 정비 요청이 없습니다");
  await act(async () => {
    const filter = host.querySelector<HTMLSelectElement>('select[aria-label="정비 요청 상태"]')!;
    filter.value = "completed"; filter.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("작업 승인 완료");
  expect(host.textContent).toContain("정상 확인");
  expect(host.querySelector<HTMLButtonElement>(".prb-approve")!.disabled).toBe(true);
});
it("renders saved same-request cost components and avoided cost without inventing profit", async () => {
  const band = (n: number) => ({ low_minor: n, base_minor: n, high_minor: n });
  const common = { action_candidate_id: "candidate", action_code: "TOOL_REPLACEMENT", calculation_status: "calculated",
    parts_cost: band(1000), labor_cost: band(2000), external_service_cost: band(0), production_loss: band(3000),
    expected_failure_loss: band(4000), total_expected_cost: band(10000), expected_downtime: { low_minutes: 30, base_minutes: 30, high_minutes: 30 }, confidence: "low", missing_inputs: [] };
  const analysis = { schema_version: "maintenance-cost-scenario-v1.0", analysis_id: "cost-A", asset_id: "CNC-A",
    calculated_at: "2026-09-07T02:00:00Z", based_on: { inspection_work_order_id: first.work_order_id },
    currency: "KRW", currency_minor_unit: 0, price_version: "demo-v1", assumptions: ["가정 기반 참고값"], missing_inputs: [], limitations: [],
    options: [{ ...common, option_id: "now", execution_timing: "immediate" }, { ...common, option_id: "baseline", execution_timing: "no_action_baseline", total_expected_cost: band(20000) }]
  } as unknown as MaintenanceCostAnalysisReadModel;
  vi.mocked(getMaintenanceEventLineage).mockResolvedValue({ ...lineage, cost_analyses: [analysis] });
  await render();
  expect(host.querySelector(".prb-cost table")).toBeNull();
  await click("선택 설비 영향 확인");
  expect(host.querySelector('[role="dialog"] .prb-cost table')?.textContent).toContain("즉시 정비");
  expect(host.querySelector(".prb-cost table")?.textContent).toContain("10,000");
  expect(host.querySelector(".prb-action-summary")?.textContent).toContain("20,000");
  expect(host.textContent).toContain("비용 절감액을 영업이익으로 표시하지 않습니다");
});
it("places the status select to the right of time order and filters active, completed and all", async () => {
  const done = { ...second, work_order_status: "completed" };
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [first, done] });
  await render();
  const tools = host.querySelector(".prb-queue-tools")!;
  expect(tools.children[0].tagName).toBe("SELECT");
  expect((tools.children[0] as HTMLSelectElement).value).toBe("time");
  expect(tools.children[0].textContent).toBe("시간순위험 점수순");
  const filter = tools.children[1] as HTMLSelectElement;
  expect(filter.tagName).toBe("SELECT");
  expect(filter.value).toBe("active");
  expect(host.querySelector('input[type="checkbox"]')).toBeNull();
  expect(host.querySelectorAll(".prb-queue-item")).toHaveLength(1);
  await act(async () => { filter.value = "completed"; filter.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(host.querySelector(".prb-queue-item")?.textContent).toContain("압축기 B");
  await act(async () => { filter.value = "all"; filter.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(host.querySelectorAll(".prb-queue-item")).toHaveLength(2);
});
it("preserves overall fleet KPIs independently of the selected request and completed filter", async () => {
  await render();
  const kpis = host.querySelector('[aria-label="전체 생산 영향 현황"]')!;
  expect(kpis.textContent).toContain("생산 영향 검토 설비");
  expect(kpis.textContent).toContain("2대");
  expect(kpis.textContent).toContain("1개");
  expect(kpis.textContent).toContain("1시간 45분");
  const original = kpis.textContent;
  await chooseB();
  expect(kpis.textContent).toBe(original);
  await act(async () => {
    const filter = host.querySelector<HTMLSelectElement>('select[aria-label="정비 요청 상태"]')!;
    filter.value = "completed"; filter.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(kpis.textContent).toBe(original);
  expect(host.textContent).toContain("현재 정비 요청이 없습니다");
});

it("sorts by current equipment risk, pins selection, and returns to time order", async () => {
  await render();
  const before = host.querySelector(".prb-queue-item[aria-pressed=true]")?.textContent;
  const sort = host.querySelector<HTMLSelectElement>('select[aria-label="정비 요청 정렬"]')!;
  await act(async () => { sort.value = "risk"; sort.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(host.querySelector(".prb-queue-item")?.textContent).toContain("압축기 B");
  expect(host.querySelector(".prb-queue-item[aria-pressed=true]")?.textContent).toBe(before);
  expect(host.querySelector(".prb-risk header b")?.textContent).toBe("10%");
  expect(respondInspectionCoordination).not.toHaveBeenCalled();
  await act(async () => { sort.value = "time"; sort.dispatchEvent(new Event("change", { bubbles: true })); });
  expect(host.querySelector(".prb-queue-item")?.textContent).toContain("정상 CNC");
});
it("places the four selected impact metrics directly below overall KPIs without duplicating them in the central review", async () => {
  await render();
  const row = host.querySelector(".prb-impact-kpis")!;
  expect(host.querySelector(".prb-kpis")?.nextElementSibling).toBe(row);
  expect(row.querySelectorAll(".prb-metric")).toHaveLength(4);
  expect(row.textContent).toContain("111개");
  expect(host.querySelector(".prb-review .prb-metric-grid")).toBeNull();
  await chooseB();
  expect(row.textContent).toContain("압축기 B");
  expect(row.textContent).toContain("222개");
  expect(row.textContent).not.toContain("111개");
  await click("선택 설비 영향 확인");
  expect(host.querySelectorAll('[role="dialog"] .prb-metric-grid .prb-metric')).toHaveLength(4);
});
it("orders by original request time, not later assignment or consultation time", () => {
  const orders = [{ work_order_id: first.work_order_id, asset_id: first.asset_id, event_id: first.event_id, status: "requested", created_at: "2026-09-06T00:00:00Z", assigned_at: null }] as OpenInspectionWorkOrderReadModel[];
  const c = { ...first, requested_at: "2026-09-08T00:00:00Z" };
  const queue = productionQueue(orders, [c, second]);
  expect(sortProductionQueue(queue, "time", new Map())[0].id).toBe(first.work_order_id);
  expect(queue.find(q => q.id === first.work_order_id)?.requestedAt).toBe(orders[0].created_at);
  const completed = productionQueue([], [{ ...c, work_order_status: "completed", work_order_created_at: "2026-09-05T00:00:00Z" }]);
  expect(completed[0].requestedAt).toBe("2026-09-05T00:00:00Z");
});
it("ranks zero ahead of unknown or invalid scores, breaks ties by time, and does not mutate inputs", () => {
  const queue = productionQueue([], [first, second, { ...first, work_order_id: "unknown", asset_id: "UNKNOWN" }, { ...second, work_order_id: "zero", asset_id: "ZERO" }]);
  const assets = new Map(model.assets.map(a => [a.assetId, a]));
  assets.set("ZERO", { ...model.assets[0], assetId: "ZERO", failureProbability: 0 });
  const original = queue.map(q => q.id);
  expect(sortProductionQueue(queue, "risk", assets).map(q => q.assetId)).toEqual(["CMP-B", "CNC-A", "ZERO", "UNKNOWN"]);
  assets.set("CNC-A", { ...model.assets[0], failureProbability: .2 });
  expect(sortProductionQueue(queue, "risk", assets)[0].assetId).toBe("CNC-A");
  assets.set("CNC-A", { ...model.assets[0], failureProbability: NaN });
  expect(sortProductionQueue(queue, "risk", assets).findIndex(q => q.assetId === "ZERO")).toBeLessThan(sortProductionQueue(queue, "risk", assets).findIndex(q => q.assetId === "CNC-A"));
  expect(queue.map(q => q.id)).toEqual(original);
});
it("uses all live equipment, not the planning subset or historical detail risk, and keeps original request cost lineage", async () => {
  const liveAsset = { ...model.assets[1], assetId: "LIVE-ONLY", displayName: "실제 압축기", failureProbability: .87, status: "critical" as const,
    observedAt: "2026-09-07T03:00:00Z", eventId: "FILE#latest",
    riskHistory: [{ observedAt: "2026-09-07T03:00:00Z", value: .87 }],
    sensorHistory: [{ feature: "pressure", label: "압력", unit: "bar", points: [{ observedAt: "2026-09-07T03:00:00Z", value: 12 }] }] };
  vi.mocked(listInspectionCoordinations).mockResolvedValue({ items: [{ ...first, asset_id: "LIVE-ONLY" }] });
  const liveModel = { ...model, equipmentOverview: { context: model.context, assets: [liveAsset] } };
  await act(async () => root.render(<ProductionRequestBoard projectId="project" workspaceId="workspace" model={liveModel} workOrders={[]} workOrderError={false} currentUser={{ displayName: "생산", title: "관리자" }} onRefresh={refresh} onLogout={vi.fn()}/>));
  expect(host.querySelector(".prb-queue-item")?.textContent).toContain("실제 압축기");
  expect(host.querySelector(".prb-queue-item")?.textContent).toContain("긴급 · 87%");
  expect(host.querySelector(".prb-risk header b")?.textContent).toBe("87%");
  expect(host.querySelectorAll(".prb-sensor-row")).toHaveLength(0);
  expect(host.querySelector(".prb-monitoring-sensors")).toBeNull();
  expect(getMaintenanceEventLineage).toHaveBeenCalledWith("project", "workspace", "event-A");
  await click("선택 설비 영향 확인");
  expect(host.querySelector(".prb-sensor")?.textContent).toContain("12 bar");
  expect(host.querySelector(".prb-sensor-svg")).not.toBeNull();
});
it("does not substitute planning fixture data when live equipment is absent or its API fails", async () => {
  for (const equipmentOverview of [null, { context: model.context, assets: [] }]) {
    await act(async () => root.render(<ProductionRequestBoard projectId="project" workspaceId="workspace" model={{ ...model, equipmentOverview }} workOrders={[]} workOrderError={false} currentUser={{ displayName: "생산", title: "관리자" }} onRefresh={refresh} onLogout={vi.fn()}/>));
    expect(host.querySelector(".prb-queue-item")?.textContent).toContain("현황 미연결");
    expect(host.querySelector(".prb-risk header b")?.textContent).toBe("정보 없음");
    expect(host.querySelector(".prb-risk svg")).toBeNull();
  }
});

it("does not substitute another request's cost and handles missing money and minor units", () => {
  const item = productionQueue([], [first])[0];
  const cost = { asset_id: "CNC-A", based_on: { inspection_work_order_id: "other" }, calculated_at: "2026-09-07", currency: "KRW", currency_minor_unit: 0 } as MaintenanceCostAnalysisReadModel;
  expect(matchingCostAnalysis([cost], item)).toBeNull();
  expect(amount(null,cost)).toBe("미산정");
  expect(amount(0,cost)).toContain("0");
  expect(amount(12345,{ ...cost, currency: "USD", currency_minor_unit: 2 })).toContain("123.45");
});

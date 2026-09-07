// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { EngineerFactoryStandalone } from "./EngineerFactoryStandalone";
import type { OperationsAsset, OperationsBootstrapModel } from "../api/operationsContracts";
vi.mock("../../../api", () => ({ requestInspectionWorkOrder: vi.fn(), listInspectionCoordinations: vi.fn() }));
const asset = (assetId: string, line: string, status: OperationsAsset["status"]): OperationsAsset => ({
  assetId, assetType: assetId.startsWith("CMP") ? "compressor" : "cnc", line, cell: line + "-L01",
  displayName: assetId, status, failureProbability: status === "normal" ? .1 : .9, eventId: "event",
  topFactors: [], sensorHistory: [], riskHistory: [], observedAt: "2026-09-07T10:00:00Z",
} as unknown as OperationsAsset);
const model = { context: { projectId: "project", workspaceId: "workspace", workspaceName: "공장", observedAt: "2026-09-07T10:00:00Z" },
  assets: [asset("CMP-S01-L01-01", "S01", "normal"), asset("CNC-S01-L01-01", "S01", "critical"), asset("CNC-S02-L01-01", "S02", "normal")],
  metrics: { estimatedDowntimeMinutes: null }
} as OperationsBootstrapModel;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  localStorage.setItem("engineer.monitoring.acknowledged.v1", JSON.stringify(model.assets.map(a => a.assetId + ":event")));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); localStorage.clear(); });
async function render() {
  await act(async () => root.render(<EngineerFactoryStandalone model={model} selectedAssetId={model.assets[0].assetId} onSelectAsset={vi.fn()} onRefresh={vi.fn()}/>));
}
async function choose(index: number, value: string) {
  await act(async () => {
    const select = host.querySelectorAll<HTMLSelectElement>(".engineer-monitoring-toolbar select")[index];
    select.value = value; select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
const highlighted = () => host.querySelectorAll(".engineer-equipment-cell button.is-highlighted").length;
it("removes the unread checkbox and ignores old read-state storage without deleting it", async () => {
  const previous = localStorage.getItem("engineer.monitoring.acknowledged.v1");
  await render();
  expect(host.textContent).not.toContain("미확인 알림만");
  expect(host.querySelector('.engineer-monitoring-toolbar input[type="checkbox"]')).toBeNull();
  expect(host.querySelectorAll(".engineer-monitoring-toolbar select")).toHaveLength(3);
  expect(highlighted()).toBe(3);
  expect(localStorage.getItem("engineer.monitoring.acknowledged.v1")).toBe(previous);
});
it("retains combined zone, equipment and status highlighting and resets all remaining filters", async () => {
  await render();
  await choose(0, "S01"); expect(highlighted()).toBe(2);
  await choose(1, "cnc"); expect(highlighted()).toBe(1);
  await choose(2, "normal"); expect(highlighted()).toBe(0);
  expect(host.querySelectorAll(".engineer-equipment-cell button")).toHaveLength(3);
  await act(async () => host.querySelector<HTMLButtonElement>(".engineer-monitoring-toolbar>button")!.click());
  expect(highlighted()).toBe(3);
  expect([...host.querySelectorAll<HTMLSelectElement>(".engineer-monitoring-toolbar select")].every(s => s.value === "all")).toBe(true);
});

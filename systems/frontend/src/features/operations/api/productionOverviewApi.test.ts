import { beforeEach, expect, it, vi } from "vitest";
import { loadProductionOverview } from "./productionOverviewApi";
import { loadEngineerFilesystemOverview, loadOperationsBootstrap } from "./operationsApi";
import type { OperationsBootstrapModel } from "./operationsContracts";
vi.mock("./operationsApi", () => ({ loadEngineerFilesystemOverview: vi.fn(), loadOperationsBootstrap: vi.fn() }));
const production = { context: { datasetVersionId: "production" }, assets: [{ assetId: "fixture" }], metrics: { estimatedDowntimeMinutes: 105 } } as OperationsBootstrapModel;
const live = { context: { datasetVersionId: "live" }, assets: [{ assetId: "current", failureProbability: .8 }] } as OperationsBootstrapModel;
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(loadOperationsBootstrap).mockResolvedValue(production);
  vi.mocked(loadEngineerFilesystemOverview).mockResolvedValue(live);
});
it("uses the same scoped APIs and retains live-only equipment without changing planning KPIs", async () => {
  const result = await loadProductionOverview("project", "workspace", "request-event");
  expect(loadOperationsBootstrap).toHaveBeenCalledWith("project", "workspace", "request-event");
  expect(loadEngineerFilesystemOverview).toHaveBeenCalledWith("project", "workspace");
  expect(result.equipmentOverview?.assets).toEqual(live.assets);
  expect(result.metrics).toBe(production.metrics);
  expect(result.context).toBe(production.context);
});
it("marks live connection failure instead of substituting fixture equipment", async () => {
  vi.mocked(loadEngineerFilesystemOverview).mockRejectedValue(new Error("503"));
  const result = await loadProductionOverview("project", "workspace", null);
  expect(result.equipmentOverview).toBeNull();
  expect(result.metrics).toBe(production.metrics);
});
it("uses live fleet instead of fallback fixtures when planning APIs are unavailable", async () => {
  vi.mocked(loadOperationsBootstrap).mockResolvedValue({...production,context:{...production.context,sourceMode:"gold-fixture-fallback"}});
  const result = await loadProductionOverview("project","workspace",null);
  expect(result.assets).toBe(live.assets);
  expect(result.context.datasetVersionId).toBe("live");
  expect(result.context.warnings).toContain("생산계획 연결 확인 필요 · 설비 현황은 최신 관측 기준입니다.");
});
it("keeps live fleet available when production bootstrap throws", async () => {
  vi.mocked(loadOperationsBootstrap).mockRejectedValue(new Error("unavailable"));
  expect((await loadProductionOverview("project","workspace",null)).assets).toBe(live.assets);
});

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

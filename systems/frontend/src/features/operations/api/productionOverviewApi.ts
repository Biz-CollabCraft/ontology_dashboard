import { loadEngineerFilesystemOverview, loadOperationsBootstrap } from "./operationsApi";
import type { OperationsBootstrapModel } from "./operationsContracts";

export async function loadProductionOverview(projectId: string, workspaceId: string, eventId: string | null): Promise<OperationsBootstrapModel> {
  const [production, live] = await Promise.all([
    loadOperationsBootstrap(projectId, workspaceId, eventId),
    loadEngineerFilesystemOverview(projectId, workspaceId).catch(() => null),
  ]);
  // Keep the overall planning KPIs, but never restrict the live fleet to the
  // planning snapshot's asset list. Both are scoped by the same API parameters.
  return { ...production, equipmentOverview: live ? { context: live.context, assets: live.assets } : null };
}

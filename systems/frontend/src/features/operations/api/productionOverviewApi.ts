import { loadEngineerFilesystemOverview, loadOperationsBootstrap } from "./operationsApi";
import type { OperationsBootstrapModel } from "./operationsContracts";

export async function loadProductionOverview(projectId: string, workspaceId: string, eventId: string | null): Promise<OperationsBootstrapModel> {
  const [productionState, liveState] = await Promise.allSettled([
    loadOperationsBootstrap(projectId, workspaceId, eventId),
    loadEngineerFilesystemOverview(projectId, workspaceId),
  ]);
  const live = liveState.status === "fulfilled" ? liveState.value : null;
  const production = productionState.status === "fulfilled" ? productionState.value : null;
  if (live && (!production || production.context.sourceMode === "gold-fixture-fallback")) {
    // Failed planning APIs must not replace the actual fleet with fixture data.
    // Keep financial planning unavailable rather than inventing plan values.
    return { ...live, equipmentOverview: { context: live.context, assets: live.assets },
      context: { ...live.context, warnings: [...(live.context.warnings ?? []), "생산계획 연결 확인 필요 · 설비 현황은 최신 관측 기준입니다."] } };
  }
  if (!production) throw new Error("생산 현황을 불러오지 못했습니다. 연결 상태를 확인해 주세요.");
  // Keep the overall planning KPIs, but never restrict the live fleet to the
  // planning snapshot's asset list. Both are scoped by the same API parameters.
  return { ...production, equipmentOverview: live ? { context: live.context, assets: live.assets } : null };
}

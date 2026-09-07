import { useCallback, useEffect, useState } from "react";
import {
  getOpenInspectionWorkOrders,
  type OpenInspectionWorkOrderReadModel,
} from "../../../api";
import type { OperationsBootstrapModel } from "../api/operationsContracts";
import {
  loadEngineerFilesystemOverview,
} from "../api/operationsApi";
import {
  EngineerFactoryLoading,
  EngineerFactoryStandalone,
} from "./EngineerFactoryStandalone";
import { RoleFactoryStandalone } from "./RoleFactoryStandalone";
import { loadProductionOverview } from "../api/productionOverviewApi";
import { useAuth } from "../../auth/AuthContext";
import { navigate } from "../../../routing";
import "../operations.css";

const REFRESH_INTERVAL_MS = 10_000;


function readSelection() {
  const query = new URLSearchParams(window.location.search);
  return {
    workspaceId: query.get("workspace_id") ?? "manufacturing-demo",
    assetId: query.get("asset_id"),
    eventId: query.get("event_id"),
  };
}

export default function EngineerFactoryApplication({
  projectId,
}: {
  projectId: string;
}) {
  const { user, logout } = useAuth();
  const roles = user?.active_project_roles.length
    ? user.active_project_roles
    : (user?.roles ?? []);
  const persona = roles.includes("process_manager")
    ? "production"
    : roles.includes("maintenance_technician")
      ? "maintenance"
      : "engineering";
  const [selection, setSelection] = useState(readSelection);
  const [model, setModel] = useState<OperationsBootstrapModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [maintenanceDirectives, setMaintenanceDirectives] = useState<
    OpenInspectionWorkOrderReadModel[]
  >([]);
  const [maintenanceDirectiveError, setMaintenanceDirectiveError] =
    useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey((value) => value + 1), []);

  useEffect(() => {
    // Do not let the live timer cancel a slow first request. The 10-second
    // cadence starts only after the first complete snapshot is on screen.
    if (!model) return;
    const timer = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [model, refresh]);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    const loadOverview =
      persona === "production"
        ? loadProductionOverview(
            projectId,
            selection.workspaceId ?? "manufacturing-demo",
            selection.eventId,
          )
        : loadEngineerFilesystemOverview(
            projectId,
            selection.workspaceId ?? "manufacturing-demo",
          );
    loadOverview
      .then((payload) => {
        if (cancelled) return;
        const highestRiskAsset = [...payload.assets].sort(
          (a, b) => (b.failureProbability ?? -1) - (a.failureProbability ?? -1),
        )[0];
        setModel(payload);
        setSelection((current) => ({
          workspaceId: current.workspaceId ?? payload.context.workspaceId,
          assetId: payload.assets.some(
            (asset) => asset.assetId === current.assetId,
          )
            ? current.assetId
            : (highestRiskAsset?.assetId ?? null),
          eventId: current.eventId,
        }));
      })
      .catch((reason: unknown) => {
        if (!cancelled)
          setError(
            reason instanceof Error
              ? reason.message
              : "공장 현황 데이터를 불러오지 못했습니다.",
          );
      });
    return () => {
      cancelled = true;
    };
  }, [
    persona,
    projectId,
    refreshKey,
    selection.eventId,
    selection.workspaceId,
  ]);

  useEffect(() => {
    let cancelled = false;
    setMaintenanceDirectiveError(false);
    getOpenInspectionWorkOrders(
      projectId,
      selection.workspaceId ?? "manufacturing-demo",
    )
      .then((payload) => {
        if (!cancelled) setMaintenanceDirectives(payload.items);
      })
      .catch(() => {
        if (!cancelled) setMaintenanceDirectiveError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, refreshKey, selection.workspaceId]);

  const selectAsset = useCallback((assetId: string, eventId: string | null) => {
    const query = new URLSearchParams(window.location.search);
    query.set("asset_id", assetId);
    if (eventId) query.set("event_id", eventId);
    else query.delete("event_id");
    window.history.replaceState(
      {},
      "",
      `${window.location.pathname}?${query.toString()}`,
    );
    setSelection((current) => ({ ...current, assetId, eventId }));
  }, []);

  const signOut = useCallback(async () => {
    await logout();
    navigate("/login", { replace: true });
  }, [logout]);

  if (!model && !error) return <EngineerFactoryLoading />;
  if (!model) {
    return (
      <main className="engineer-lite-board">
        <section className="engineer-factory-card engineer-load-error">
          <strong>공장 현황을 불러오지 못했습니다</strong>
          <p>{error}</p>
          <button type="button" onClick={refresh}>
            다시 연결
          </button>
        </section>
      </main>
    );
  }
  if (persona !== "engineering") {
    return (
      <RoleFactoryStandalone
        projectId={projectId}
        workspaceId={selection.workspaceId ?? "manufacturing-demo"}
        persona={persona}
        model={model}
        workOrders={maintenanceDirectives}
        workOrderError={maintenanceDirectiveError}
        currentUserId={user?.user_id ?? ""}
        currentUser={{ displayName: user?.display_name ?? "사용자", title: persona === "production" ? "생산관리자" : "보전팀" }}
        onRefresh={refresh}
        onLogout={signOut}
      />
    );
  }
  return (
    <EngineerFactoryStandalone
      model={model}
      selectedAssetId={selection.assetId}
      maintenanceDirectives={maintenanceDirectives}
      maintenanceDirectiveError={maintenanceDirectiveError}
      currentUser={{
        displayName: user?.display_name ?? "사용자",
        title: "설비 엔지니어",
      }}
      onSelectAsset={selectAsset}
      onRefresh={refresh}
      onLogout={signOut}
    />
  );
}

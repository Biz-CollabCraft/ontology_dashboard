import { useCallback, useEffect, useState } from "react";
import type { OperationsBootstrapModel } from "../api/operationsContracts";
import { loadEngineerFilesystemOverview } from "../api/operationsApi";
import { EngineerFactoryLoading, EngineerFactoryStandalone } from "./EngineerFactoryStandalone";
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

export default function EngineerFactoryApplication({ projectId }: { projectId: string }) {
  const [selection, setSelection] = useState(readSelection);
  const [model, setModel] = useState<OperationsBootstrapModel | null>(null);
  const [error, setError] = useState<string | null>(null);
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
    loadEngineerFilesystemOverview(projectId, selection.workspaceId ?? "manufacturing-demo")
      .then((payload) => {
        if (cancelled) return;
        setModel(payload);
        setSelection((current) => ({
          workspaceId: current.workspaceId ?? payload.context.workspaceId,
          assetId: payload.assets.some((asset) => asset.assetId === current.assetId) ? current.assetId : payload.assets[0]?.assetId ?? null,
          eventId: current.eventId,
        }));
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "공장 현황 데이터를 불러오지 못했습니다.");
      });
    return () => { cancelled = true; };
  }, [projectId, refreshKey, selection.eventId, selection.workspaceId]);

  const selectAsset = useCallback((assetId: string, eventId: string | null) => {
    const query = new URLSearchParams(window.location.search);
    query.set("asset_id", assetId);
    if (eventId) query.set("event_id", eventId);
    else query.delete("event_id");
    window.history.replaceState({}, "", `${window.location.pathname}?${query.toString()}`);
    setSelection((current) => ({ ...current, assetId, eventId }));
  }, []);

  if (!model && !error) return <EngineerFactoryLoading />;
  if (!model) {
    return <main className="engineer-lite-board"><section className="engineer-factory-card engineer-load-error"><strong>공장 현황을 불러오지 못했습니다</strong><p>{error}</p><button type="button" onClick={refresh}>다시 연결</button></section></main>;
  }
  return <EngineerFactoryStandalone model={model} selectedAssetId={selection.assetId} onSelectAsset={selectAsset} onRefresh={refresh} />;
}

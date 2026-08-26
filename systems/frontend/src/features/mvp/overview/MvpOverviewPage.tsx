import type {
  MvpBootstrapModel,
  MvpDashboardMode,
  MvpEventDetailModel,
  MvpReportTab,
  MvpRoleLens,
} from "../api/mvpContracts";
import { MvpClassicOverviewPage } from "./MvpClassicOverviewPage";
import { MvpWorkflowOverviewPage } from "./MvpWorkflowOverviewPage";

export function MvpOverviewPage({
  model,
  role,
  dashboard,
  selectedAssetId,
  detail,
  detailLoading,
  detailError,
  onDashboardChange,
  onOpenAsset,
  onPreviewAsset,
  onOpenEvent,
  onOpenReport,
  onRefresh,
}: {
  model: MvpBootstrapModel;
  role: MvpRoleLens;
  dashboard: MvpDashboardMode;
  selectedAssetId: string | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  onDashboardChange: (dashboard: MvpDashboardMode) => void;
  onOpenAsset: (assetId: string, eventId: string | null) => void;
  onPreviewAsset: (assetId: string, eventId: string | null) => void;
  onOpenEvent: (eventId: string, assetId: string) => void;
  onOpenReport: (eventId: string | null, assetId: string | null, reportTab?: MvpReportTab) => void;
  onRefresh: () => void;
}) {
  return (
    <>
      <div className="mvp-dashboard-switch" role="group" aria-label="Overview dashboard mode">
        <button type="button" aria-pressed={dashboard === "workflow"} onClick={() => onDashboardChange("workflow")}>작업 흐름 대시보드</button>
        <button type="button" aria-pressed={dashboard === "classic"} onClick={() => onDashboardChange("classic")}>기본 대시보드</button>
      </div>
      {dashboard === "classic" ? (
        <MvpClassicOverviewPage
          model={model}
          onOpenAsset={onOpenAsset}
          onOpenEvent={onOpenEvent}
          onOpenReport={(eventId, assetId) => onOpenReport(eventId, assetId)}
          onRefresh={onRefresh}
        />
      ) : (
        <MvpWorkflowOverviewPage
          model={model}
          role={role}
          selectedAssetId={selectedAssetId}
          detail={detail}
          detailLoading={detailLoading}
          detailError={detailError}
          onPreviewAsset={onPreviewAsset}
          onOpenEvent={onOpenEvent}
          onOpenReport={onOpenReport}
          onRefresh={onRefresh}
        />
      )}
    </>
  );
}

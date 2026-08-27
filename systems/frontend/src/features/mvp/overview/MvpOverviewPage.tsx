import type {
  MvpBootstrapModel,
  MvpDashboardMode,
  MvpEventDetailModel,
  MvpReportTab,
  MvpRoleLens,
  MvpSensorWindowId,
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
  sensorWindow,
  onOpenAsset,
  onPreviewAsset,
  onOpenEvent,
  onOpenReport,
  onSensorWindowChange,
  onRefresh,
}: {
  model: MvpBootstrapModel;
  role: MvpRoleLens;
  dashboard: MvpDashboardMode;
  selectedAssetId: string | null;
  detail: MvpEventDetailModel | null;
  detailLoading: boolean;
  detailError: string | null;
  sensorWindow: MvpSensorWindowId;
  onOpenAsset: (assetId: string, eventId: string | null) => void;
  onPreviewAsset: (assetId: string, eventId: string | null) => void;
  onOpenEvent: (eventId: string, assetId: string) => void;
  onOpenReport: (eventId: string | null, assetId: string | null, reportTab?: MvpReportTab) => void;
  onSensorWindowChange: (windowId: MvpSensorWindowId) => void;
  onRefresh: () => void;
}) {
  return (
    <>
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
          sensorWindow={sensorWindow}
          onSensorWindowChange={onSensorWindowChange}
          onPreviewAsset={onPreviewAsset}
          onRefresh={onRefresh}
        />
      )}
    </>
  );
}

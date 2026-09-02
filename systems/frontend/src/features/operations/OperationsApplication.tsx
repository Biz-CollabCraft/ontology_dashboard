import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { navigate } from "../../routing";
import type {
  OperationsAsset,
  OperationsBootstrapModel,
  OperationsCompanyContext,
  OperationsDecision,
  OperationsEvent,
  OperationsEventDetailModel,
  OperationsReportTab,
  OperationsRoleLens,
  OperationsSensorWindowId,
  OperationsView,
} from "./api/operationsContracts";
import {
  loadOperationsBootstrap,
  loadOperationsCompanyContext,
  loadOperationsEventDetail,
  submitOperationsDecision,
  submitOperationsNote,
} from "./api/operationsApi";
import { OperationsState } from "./components/OperationsUi";
import { OperationsSelectionProvider, useOperationsSelection } from "./context/OperationsSelectionContext";
import { OperationsObjectsPage } from "./objects/OperationsObjectsPage";
import { OperationsOperationsPage } from "./operations/OperationsOperationsPage";
import { OperationsOverviewPage } from "./overview/OperationsOverviewPage";
import { OperationsReportsPage } from "./report/OperationsReportsPage";
import { OperationsShell } from "./shell/OperationsShell";
import { OperationsSystemAdminPage } from "./system/OperationsSystemAdminPage";
import {
  ReliabilityWorkspacePreview,
  ReliabilityWorkspaceLoadingPlaceholder,
  reliabilityWorkspacePreviewEnabled,
} from "../predictive-maintenance/ReliabilityWorkspacePreview";
import { resolveReliabilityRoleExperience } from "../predictive-maintenance/workspace/roleExperience";
import { RoleComposedWorkspace } from "../predictive-maintenance/workspace/RoleComposedWorkspace";
import {
  defaultReliabilitySurface,
  reliabilitySurfaceForView,
  reliabilitySurfaces,
} from "../predictive-maintenance/workspace/roleSurfaces";
import {
  canMaterializeAgentReviewSummary,
  canReadOperationsSystemLogs,
} from "./permissions";
import "./operations.css";

const Operations_REFRESH_INTERVAL_SECONDS = 10;

function defaultRoleLens(roles: string[]): OperationsRoleLens {
  return roles.some((role) => role === "process_engineer" || role === "maintenance_technician")
    ? "field_operator"
    : "process_manager";
}

export function OperationsApplication({ projectId, backupMode = false }: { projectId: string; backupMode?: boolean }) {
  const { user } = useAuth();
  const roles = user?.active_project_roles.length ? user.active_project_roles : user?.roles ?? [];
  const role = defaultRoleLens(roles);
  const experience = user ? resolveReliabilityRoleExperience(user) : null;
  const defaultSurface = experience ? defaultReliabilitySurface(experience.kind, backupMode) : null;
  const defaultView = defaultSurface?.view ?? experience?.defaultView ?? "overview";
  const defaultReportTab: OperationsReportTab = experience?.kind === "executive" ? "executive-brief" : "status-map";
  return (
    <OperationsSelectionProvider
      projectId={projectId}
      defaultRole={role}
      defaultView={defaultView}
      defaultSurface={defaultSurface?.id ?? null}
      defaultReportTab={defaultReportTab}
      storageScope={`${user?.user_id ?? "anonymous"}${backupMode ? ":backup-v1" : ""}`}
      navigationBasePath={backupMode ? "/backup" : null}
    >
      <OperationsApplicationController projectId={projectId} backupMode={backupMode} />
    </OperationsSelectionProvider>
  );
}
export default OperationsApplication;

function OperationsApplicationController({ projectId, backupMode }: { projectId: string; backupMode: boolean }) {
  const { user, logout } = useAuth();
  const { selection, updateSelection } = useOperationsSelection();
  const [model, setModel] = useState<OperationsBootstrapModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [detail, setDetail] = useState<OperationsEventDetailModel | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailVersion, setDetailVersion] = useState(0);
  const [sensorWindow, setSensorWindow] = useState<OperationsSensorWindowId>("24h");
  const [companyContext, setCompanyContext] = useState<OperationsCompanyContext | null>(null);
  const [companyContextError, setCompanyContextError] = useState<string | null>(null);
  const experienceKind = user
    ? resolveReliabilityRoleExperience(user).kind
    : selection.role === "field_operator"
      ? "engineering"
      : "operations";

  useEffect(() => {
    const surfaces = reliabilitySurfaces(experienceKind, backupMode);
    if (selection.surface && surfaces.some((item) => item.id === selection.surface)) return;
    const next = defaultReliabilitySurface(experienceKind, backupMode);
    updateSelection({ surface: next.id, view: next.view }, { replace: true });
  }, [backupMode, experienceKind, selection.surface, updateSelection]);

  const refresh = useCallback(() => setRefreshVersion((value) => value + 1), []);
  const retryDetail = useCallback(() => setDetailVersion((value) => value + 1), []);
  const workflowChanged = useCallback(() => {
    setDetailVersion((value) => value + 1);
    setRefreshVersion((value) => value + 1);
  }, []);
  const signOut = useCallback(async () => {
    await logout();
    navigate("/login", { replace: true });
  }, [logout]);

  useEffect(() => {
    document.documentElement.lang = "ko-KR";
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRefreshVersion((value) => value + 1);
    }, Operations_REFRESH_INTERVAL_SECONDS * 1_000);
    return () => window.clearInterval(timer);
  }, [projectId, selection.workspaceId]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    loadOperationsBootstrap(projectId, selection.workspaceId, selection.eventId)
      .then((payload) => {
        if (cancelled) return;
        setModel(payload);
        const selectedEvent = payload.events.find((item) => item.eventId === selection.eventId) ?? null;
        const selectedAsset = payload.assets.find((item) => item.assetId === selection.assetId) ?? null;
        const patch: Parameters<typeof updateSelection>[0] = {};
        if (!selection.workspaceId) patch.workspaceId = payload.context.workspaceId;
        if (selection.eventId && !selectedEvent && selectedAsset?.eventId) {
          patch.eventId = selectedAsset.eventId;
        }
        if (!selection.eventId && selectedAsset?.eventId) patch.eventId = selectedAsset.eventId;
        if (!selection.assetId && selectedEvent) patch.assetId = selectedEvent.assetId;
        if (!selection.assetId && !selection.eventId && payload.events[0]) {
          patch.eventId = payload.events[0].eventId;
          patch.assetId = payload.events[0].assetId;
        }
        if (Object.keys(patch).length) updateSelection(patch, { replace: true });
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setError(reason instanceof Error ? reason.message : "운영 데이터를 불러오지 못했습니다.");
      })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [projectId, refreshVersion, selection.workspaceId]);

  const selectedEvent = useMemo(
    () => model?.events.find((item) => item.eventId === selection.eventId) ?? null,
    [model, selection.eventId],
  );

  useEffect(() => {
    const workspaceId = model?.context.workspaceId;
    if (!workspaceId) return;
    let cancelled = false;
    setCompanyContextError(null);
    loadOperationsCompanyContext(projectId, workspaceId)
      .then((payload) => {
        if (!cancelled) setCompanyContext(payload);
      })
      .catch((reason: unknown) => {
        if (cancelled) return;
        setCompanyContextError(reason instanceof Error ? reason.message : "회사 운영 문맥을 불러오지 못했습니다.");
      });
    return () => { cancelled = true; };
  }, [model?.context.workspaceId, projectId]);

  useEffect(() => {
    if (!model || !selectedEvent) {
      setDetail(null);
      setDetailError(null);
      setDetailLoading(false);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    loadOperationsEventDetail({
      projectId,
      workspaceId: model.context.workspaceId,
      datasetVersionId: model.context.datasetVersionId,
      event: selectedEvent,
      role: selection.role,
      historyWindow: sensorWindow,
      metrics: model.metrics,
    })
      .then((payload) => !cancelled && setDetail(payload))
      .catch((reason: unknown) => {
        if (cancelled) return;
        setDetail(null);
        setDetailError(reason instanceof Error ? reason.message : "선택 Event 상세를 불러오지 못했습니다.");
      })
      .finally(() => !cancelled && setDetailLoading(false));
    return () => { cancelled = true; };
  }, [detailVersion, refreshVersion, model?.context.datasetVersionId, model?.context.workspaceId, projectId, selectedEvent?.eventId, selection.role, sensorWindow]);

  const openView = useCallback((view: OperationsView) => {
    const surface = reliabilitySurfaceForView(experienceKind, view, backupMode);
    const patch: Parameters<typeof updateSelection>[0] = { view, surface: surface.id };
    if ((view === "operations" || view === "reports") && !selection.eventId && model?.events[0]) {
      patch.eventId = model.events[0].eventId;
      patch.assetId = model.events[0].assetId;
    }
    updateSelection(patch);
  }, [backupMode, experienceKind, model?.events, selection.eventId, updateSelection]);

  const openSurface = useCallback((surfaceId: string, view: OperationsView) => {
    const patch: Parameters<typeof updateSelection>[0] = { surface: surfaceId, view };
    if ((view === "operations" || view === "reports") && !selection.eventId && model?.events[0]) {
      patch.eventId = model.events[0].eventId;
      patch.assetId = model.events[0].assetId;
    }
    updateSelection(patch);
  }, [model?.events, selection.eventId, updateSelection]);

  const openAsset = useCallback((assetId: string, eventId: string | null) => {
    updateSelection({ view: "objects", surface: reliabilitySurfaceForView(experienceKind, "objects", backupMode).id, assetId, eventId });
  }, [backupMode, experienceKind, updateSelection]);

  const openEvent = useCallback((eventId: string, assetId: string) => {
    updateSelection({ view: "operations", surface: reliabilitySurfaceForView(experienceKind, "operations", backupMode).id, eventId, assetId });
  }, [backupMode, experienceKind, updateSelection]);

  const openReport = useCallback((eventId: string | null, assetId: string | null, reportTab: OperationsReportTab = "executive-brief") => {
    const fallback = model?.events[0] ?? null;
    updateSelection({
      view: "reports",
      surface: reliabilitySurfaceForView(experienceKind, "reports", backupMode).id,
      reportTab,
      eventId: eventId ?? fallback?.eventId ?? null,
      assetId: assetId ?? fallback?.assetId ?? null,
    });
  }, [backupMode, experienceKind, model?.events, updateSelection]);

  const previewAsset = useCallback((assetId: string, eventId: string | null) => {
    updateSelection({ assetId, eventId });
  }, [updateSelection]);

  const selectAsset = useCallback((asset: OperationsAsset) => {
    updateSelection({ assetId: asset.assetId, eventId: asset.eventId });
  }, [updateSelection]);

  const openAssetOperations = useCallback((asset: OperationsAsset) => {
    if (!asset.eventId) return;
    updateSelection({ view: "operations", assetId: asset.assetId, eventId: asset.eventId });
  }, [updateSelection]);

  const openAssetReport = useCallback((asset: OperationsAsset) => {
    updateSelection({ view: "reports", reportTab: "executive-brief", assetId: asset.assetId, eventId: asset.eventId });
  }, [updateSelection]);

  const selectEvent = useCallback((event: OperationsEvent) => {
    updateSelection({ eventId: event.eventId, assetId: event.assetId });
  }, [updateSelection]);

  const openEventAsset = useCallback((event: OperationsEvent) => {
    updateSelection({ view: "objects", eventId: event.eventId, assetId: event.assetId });
  }, [updateSelection]);

  const openEventReport = useCallback((event: OperationsEvent) => {
    updateSelection({ view: "reports", reportTab: "executive-brief", eventId: event.eventId, assetId: event.assetId });
  }, [updateSelection]);

  const selectReportTab = useCallback((reportTab: OperationsReportTab) => {
    const patch: Parameters<typeof updateSelection>[0] = { view: "reports", reportTab };
    if (!selection.eventId && model?.events[0]) {
      patch.eventId = model.events[0].eventId;
      patch.assetId = model.events[0].assetId;
    }
    updateSelection(patch);
  }, [model?.events, selection.eventId, updateSelection]);

  const submitDecision = useCallback(async (decision: OperationsDecision, note: string) => {
    if (!selectedEvent || !user) throw new Error("저장할 Event 또는 사용자 문맥이 없습니다.");
    const workspaceId = model?.context.workspaceId ?? selection.workspaceId;
    if (!workspaceId) throw new Error("작업요청을 생성할 Workspace 문맥이 없습니다.");
    await submitOperationsDecision({
      projectId,
      workspaceId,
      eventId: selectedEvent.eventId,
      userId: user.user_id,
      actor: user.display_name,
      decision,
      note,
      snapshotBasis: detail?.event.eventId === selectedEvent.eventId ? detail.snapshotBasis : null,
    });
    retryDetail();
    refresh();
  }, [detail, model?.context.workspaceId, projectId, refresh, retryDetail, selectedEvent, selection.workspaceId, user]);

  const submitNote = useCallback(async (body: string) => {
    if (!selectedEvent || !user) throw new Error("저장할 Event 또는 사용자 문맥이 없습니다.");
    await submitOperationsNote({ eventId: selectedEvent.eventId, actor: user.display_name, body });
    retryDetail();
  }, [retryDetail, selectedEvent, user]);

  const useReliabilityPreview = backupMode || reliabilityWorkspacePreviewEnabled();

  if (loading && !model) return useReliabilityPreview
    ? <ReliabilityWorkspaceLoadingPlaceholder />
    : <div className="operations-route-state"><OperationsState kind="loading" title="예지보전 화면 구성 중" detail="Project, Workspace, 설비 판단 데이터를 연결하고 있습니다." /></div>;
  if (error && !model) return <div className="operations-route-state"><OperationsState kind="error" title="예지보전 화면을 열지 못했습니다" detail={error} onRetry={refresh} /></div>;
  if (!model) return <div className="operations-route-state"><OperationsState kind="empty" title="표시할 운영 데이터가 없습니다" detail="Project와 Workspace 연결 상태를 확인하세요." /></div>;

  const canDecide = Boolean(user?.permissions.includes("events.decision"));
  const canNote = Boolean(user?.permissions.includes("events.note"));
  const canExecuteFieldWorkflow = Boolean(user?.permissions.includes("field.tasks.update"));
  const canMaterializeAgentSummary = canMaterializeAgentReviewSummary(user?.permissions);
  const canReadSystemLogs = canReadOperationsSystemLogs(user?.permissions);
  const selectedAssetId = selection.assetId;
  let content;
  if (useReliabilityPreview && !backupMode && selection.surface === "factory-status") {
    content = <OperationsOverviewPage model={model} role={selection.role} experienceKind={experienceKind} dashboard={selection.dashboard} selectedAssetId={selection.assetId} detail={detail} detailLoading={detailLoading} detailError={detailError} sensorWindow={sensorWindow} canMaterializeAgentSummary={canMaterializeAgentSummary} canManageWorkflow={canDecide} canExecuteFieldWorkflow={canExecuteFieldWorkflow} onSensorWindowChange={setSensorWindow} onOpenAsset={openAsset} onPreviewAsset={previewAsset} onOpenEvent={openEvent} onOpenReport={openReport} onRefresh={refresh} />;
  } else if (useReliabilityPreview && selection.view !== "system") {
    content = <RoleComposedWorkspace
      experienceKind={experienceKind}
      view={selection.view}
      surfaceId={selection.surface}
      model={model}
      selectedEvent={selectedEvent}
      detail={detail}
      companyContext={companyContext}
      role={selection.role}
      canManageWorkflow={canDecide}
      canExecuteFieldWorkflow={canExecuteFieldWorkflow}
      canMaterializeAgentSummary={canMaterializeAgentSummary}
      onSelectEvent={selectEvent}
      onOpenAsset={openAsset}
      onOpenReport={openReport}
      onWorkflowChanged={workflowChanged}
    />;
  } else if (selection.view === "objects") {
    content = <OperationsObjectsPage model={model} selectedAssetId={selectedAssetId} detail={detail} detailLoading={detailLoading} detailError={detailError} onSelectAsset={selectAsset} onOpenOperations={openAssetOperations} onOpenReport={openAssetReport} onRetryDetail={retryDetail} />;
  } else if (selection.view === "operations") {
    content = <OperationsOperationsPage model={model} selectedEventId={selection.eventId} detail={detail} detailLoading={detailLoading} detailError={detailError} canDecide={canDecide} canNote={canNote} onSelectEvent={selectEvent} onOpenAsset={openEventAsset} onOpenReport={openEventReport} onDecision={submitDecision} onNote={submitNote} onRetryDetail={retryDetail} />;
  } else if (selection.view === "reports") {
    content = <OperationsReportsPage activeTab={selection.reportTab} model={model} selectedEvent={selectedEvent} detail={detail} detailLoading={detailLoading} detailError={detailError} canMaterializeAgentSummary={canMaterializeAgentSummary} experienceKind={experienceKind} userScope={user?.user_id ?? "anonymous"} onSelectTab={selectReportTab} onSelectEvent={selectEvent} onBackToOverview={() => openView("overview")} onOpenOperations={(event) => openEvent(event.eventId, event.assetId)} onRetryDetail={retryDetail} />;
  } else if (selection.view === "system") {
    content = canReadSystemLogs
      ? <OperationsSystemAdminPage model={model} refreshing={loading} onRefresh={refresh} />
      : <OperationsState kind="error" title="시스템 관리자 권한 필요" detail="AI 요약 처리 로그는 관리자 감사 권한이 있는 사용자만 조회할 수 있습니다." />;
  } else {
    content = <OperationsOverviewPage model={model} role={selection.role} experienceKind={experienceKind} dashboard={selection.dashboard} selectedAssetId={selection.assetId} detail={detail} detailLoading={detailLoading} detailError={detailError} sensorWindow={sensorWindow} canMaterializeAgentSummary={canMaterializeAgentSummary} canManageWorkflow={canDecide} canExecuteFieldWorkflow={canExecuteFieldWorkflow} onSensorWindowChange={setSensorWindow} onOpenAsset={openAsset} onPreviewAsset={previewAsset} onOpenEvent={openEvent} onOpenReport={openReport} onRefresh={refresh} />;
  }

  const body = <>
    {error ? <div className="operations-inline-warning" role="alert"><strong>새로고침 실패</strong><span>{error}</span></div> : null}
    {detailError && useReliabilityPreview ? <div className="operations-inline-warning" role="alert"><strong>상세 근거 조회 지연</strong><span>{detailError}</span></div> : null}
    {companyContextError && useReliabilityPreview ? <div className="operations-inline-warning" role="alert"><strong>회사 문맥 조회 지연</strong><span>{companyContextError}</span></div> : null}
    {detailLoading && useReliabilityPreview ? <div className="rw-composed-detail-loading">선택 설비 근거를 최신 상태로 동기화하고 있습니다.</div> : null}
    {content}
  </>;

  if (useReliabilityPreview && user) {
    return (
      <ReliabilityWorkspacePreview
        context={model.context}
        activeView={selection.view}
        activeSurface={selection.surface}
        user={user}
        selectedEvent={selectedEvent}
        detail={detail}
        onNavigate={openSurface}
        onRefresh={refresh}
        refreshing={loading}
        onLogout={signOut}
        backupMode={backupMode}
      >
        {body}
      </ReliabilityWorkspacePreview>
    );
  }

  return <OperationsShell
    context={model.context}
    activeView={selection.view}
    dashboard={selection.dashboard}
    role={selection.role}
    onNavigate={openView}
    onRoleChange={(role: OperationsRoleLens) => updateSelection({ role, view: "overview" })}
    onRefresh={refresh}
    refreshing={loading}
    refreshIntervalSeconds={Operations_REFRESH_INTERVAL_SECONDS}
    canReadSystemLogs={canReadSystemLogs}
    onLogout={signOut}
  >{body}</OperationsShell>;
}

import {
  API_BASE,
  ApiError,
  addNote,
  getEvidence,
  getPredictiveMaintenanceDashboard,
  getPredictiveMaintenanceLatestResults,
  getProject,
  getProjectEvents,
  getProjectWorkspaces,
  getReport,
  recordDecision,
  requestInspectionWorkOrder,
} from "../../../api";
import type { Evidence, Report } from "../../../types";
import {
  adaptEvent,
  applyAssetDetailViewModel,
  composeEventDetail,
  computeLineRisk,
  computeMetrics,
  mergeAssets,
  promoteRuntimeProductResultsToEvents,
  sortRisk,
} from "./operationsAdapters";
import type {
  AssetDetailViewModel,
  OperationsBootstrapModel,
  OperationsDecision,
  OperationsEvent,
  OperationsEventDetailModel,
  OperationsEvidenceSnapshotBasis,
  OperationsMetrics,
  OperationsRoleLens,
  OperationsSensorWindowId,
} from "./operationsContracts";

function idempotencyPart(value: string | null | undefined): string {
  return String(value ?? "none").replace(/[^A-Za-z0-9_.:-]/g, "_").slice(0, 80);
}

export function inspectionRequestIdempotencyKey(input: {
  eventId: string;
  userId: string;
  decision: OperationsDecision;
  snapshotBasis: OperationsEvidenceSnapshotBasis;
}): string {
  return [
    "operations-inspection",
    idempotencyPart(input.eventId),
    idempotencyPart(input.decision),
    idempotencyPart(input.userId),
    idempotencyPart(input.snapshotBasis.artifactId ?? input.snapshotBasis.observedAt),
  ].join(":").slice(0, 200);
}

async function getEventActivity(eventId: string): Promise<unknown> {
  const response = await fetch(`${API_BASE}/api/events/${encodeURIComponent(eventId)}/activity`, {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload?.error?.code ?? "activity_request_failed",
      payload?.error?.message ?? `Activity request failed: ${response.status}`,
    );
  }
  return payload;
}

async function getAssetDetailViewModel(
  projectId: string,
  workspaceId: string,
  assetId: string,
  eventId: string,
  datasetVersionId: string,
  historyWindow: OperationsSensorWindowId,
): Promise<AssetDetailViewModel> {
  const params = new URLSearchParams({
    project_id: projectId,
    workspace_id: workspaceId,
    event_id: eventId,
    dataset_version_id: datasetVersionId,
    history_window: historyWindow,
  });
  const response = await fetch(
    `${API_BASE}/api/objects/${encodeURIComponent(assetId)}/detail-view?${params.toString()}`,
    {
      credentials: "include",
      headers: { Accept: "application/json" },
    },
  );
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(
      response.status,
      payload?.error?.code ?? "asset_detail_view_model_failed",
      payload?.error?.message ?? `Asset detail ViewModel request failed: ${response.status}`,
    );
  }
  return payload as AssetDetailViewModel;
}

function staleFrom(observedAt: string | null): boolean {
  if (!observedAt) return false;
  const value = Date.parse(observedAt);
  if (!Number.isFinite(value)) return false;
  const now = Date.now();
  // "stale" means that no recent Observation has arrived. An accelerated
  // Simulation Clock may legitimately be ahead of wall time, so a future
  // timestamp must not be presented as an observation delay.
  return now - value > 24 * 60 * 60 * 1000;
}

function warningMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function sourceStatusLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").toLowerCase();
  if (normalized === "available" || normalized === "ready" || normalized === "active") return "연결됨";
  if (normalized === "stale") return "오래된 관측";
  if (normalized === "unavailable" || normalized === "error") return "일부 미연결";
  return value ? String(value) : "상태 확인 중";
}

export async function loadOperationsBootstrap(
  projectId: string,
  requestedWorkspaceId?: string | null,
  selectedEventId?: string | null,
): Promise<OperationsBootstrapModel> {
  const [project, workspaces] = await Promise.all([
    getProject(projectId),
    getProjectWorkspaces(projectId),
  ]);
  const workspace = workspaces.find((item) => item.id === requestedWorkspaceId)
    ?? workspaces.find((item) => item.id === project.default_workspace_id)
    ?? workspaces[0];
  if (!workspace) throw new Error("이 Project에 연결된 Workspace가 없습니다.");

  const dashboardPromise = getPredictiveMaintenanceDashboard(projectId, workspace.id, {
    selected_event_id: selectedEventId ?? undefined,
    role: "manager",
    intent: "overview",
    locale: "ko-KR",
  });
  // The governed latest-results API caps a page at 500 rows. The current
  // dashboard needs one latest result per asset, so a single maximum-sized page covers
  // the Canonical V3.1 fleet without triggering a 422 and silently falling
  // back to event-only asset metadata.
  const resultPromise = getPredictiveMaintenanceLatestResults(projectId, workspace.id, 500);
  const [dashboardState, resultState] = await Promise.allSettled([dashboardPromise, resultPromise]);

  const warnings: string[] = [];
  let rawEvents = dashboardState.status === "fulfilled" ? dashboardState.value.events : [];
  if (dashboardState.status === "rejected") {
    warnings.push(`운영 현황 일부 지연: ${warningMessage(dashboardState.reason, "사용 불가")}`);
    try {
      rawEvents = await getProjectEvents(projectId);
    } catch (reason) {
      warnings.push(`Event 목록 조회 실패: ${warningMessage(reason, "사용 불가")}`);
    }
  }

  const results = resultState.status === "fulfilled" ? resultState.value.items : [];
  if (resultState.status === "rejected") {
    warnings.push(`설비 판단 결과 일부 지연: ${warningMessage(resultState.reason, "사용 불가")}`);
  }
  const events = promoteRuntimeProductResultsToEvents(results, sortRisk(rawEvents.map(adaptEvent)));
  const assets = mergeAssets(results, events);
  const metrics = computeMetrics(assets, events);
  const lineRisk = computeLineRisk(assets);
  const latestObservedAt = assets
    .map((item) => item.observedAt)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? null;

  const canonical = dashboardState.status === "fulfilled" ? dashboardState.value : null;
  const resultContext = resultState.status === "fulfilled" ? resultState.value.context : null;
  const dataSource = canonical?.data_source;
  const context = canonical?.context ?? resultContext;
  const sourceMode = canonical || resultState.status === "fulfilled"
    ? "canonical-runtime" as const
    : "gold-fixture-fallback" as const;
  const datasetVersionId = dataSource?.dataset_version_id
    ?? context?.dataset_version_id
    ?? events[0]?.datasetVersionId
    ?? "dsv-canonical-v3-1";
  const sourceVersion = dataSource?.source_version ?? context?.source_version ?? "Canonical V3.1";

  return {
    context: {
      projectId: project.id,
      projectName: project.display_name,
      workspaceId: workspace.id,
      workspaceName: workspace.display_name,
      datasetVersionId,
      datasetLabel: dataSource?.dataset_name
        ? `${dataSource.dataset_name} · ${sourceVersion}`
        : "UCI AI4I 2020 Manufacturing Predictive Maintenance — Physics & Maintenance Canonical V3.1",
      sourceVersion,
      modelVersion: dataSource?.model_version ?? context?.model_version ?? null,
      schemaVersion: dataSource?.result_artifact_schema_version ?? context?.result_artifact_schema_version ?? null,
      sourceMode,
      sourceStatus: sourceMode === "canonical-runtime"
        ? `${sourceStatusLabel(dataSource?.dataset_status ?? context?.dataset_status)} · 최신 설비 판단`
        : "운영 데이터 일부 미연결 · 보조 데이터로 표시 중",
      refreshedAt: new Date().toISOString(),
      observedAt: latestObservedAt,
      stale: staleFrom(latestObservedAt),
      warnings,
    },
    assets,
    events,
    metrics,
    lineRisk,
  };
}

async function loadLegacyReport(eventId: string): Promise<{ report: Report | null; warning: string | null }> {
  try {
    return { report: await getReport(eventId, "manager", true, "ko-KR"), warning: null };
  } catch (llmReason) {
    try {
      const report = await getReport(eventId, "manager", false, "ko-KR");
      return {
        report,
        warning: `자동 보고서 생성 일부 지연, 검증된 기본 보고서 사용: ${warningMessage(llmReason, "unknown error")}`,
      };
    } catch (fallbackReason) {
      return {
        report: null,
        warning: `보고서 조회 지연, 기본 양식으로 표시: ${warningMessage(fallbackReason, "unknown error")}`,
      };
    }
  }
}

export async function loadOperationsEventDetail(input: {
  projectId: string;
  workspaceId: string;
  datasetVersionId: string;
  event: OperationsEvent;
  role: OperationsRoleLens;
  historyWindow: OperationsSensorWindowId;
  metrics?: OperationsMetrics;
}): Promise<OperationsEventDetailModel> {
  const usesRuntimeProductResult = input.event.eventId.startsWith("RESULT#");
  const predictivePromise = getPredictiveMaintenanceDashboard(input.projectId, input.workspaceId, {
    dataset_version_id: input.datasetVersionId,
    selected_event_id: input.event.eventId,
    role: input.role === "process_manager" ? "manager" : "engineer",
    intent: input.role === "process_manager" ? "summarize-manager" : "detail-engineer",
    locale: "ko-KR",
  });
  const evidencePromise: Promise<Evidence | null> = usesRuntimeProductResult
    ? Promise.resolve(null)
    : getEvidence(input.event.eventId);
  const reportPromise: Promise<{ report: Report | null; warning: string | null }> = usesRuntimeProductResult
    ? Promise.resolve({ report: null, warning: null })
    : loadLegacyReport(input.event.eventId);
  const activityPromise: Promise<unknown | null> = usesRuntimeProductResult
    ? Promise.resolve(null)
    : getEventActivity(input.event.eventId);
  const assetDetailPromise = getAssetDetailViewModel(
    input.projectId,
    input.workspaceId,
    input.event.assetId,
    input.event.eventId,
    input.datasetVersionId,
    input.historyWindow,
  );
  const [predictiveState, evidenceState, reportState, activityState, assetDetailState] = await Promise.allSettled([
    predictivePromise,
    evidencePromise,
    reportPromise,
    activityPromise,
    assetDetailPromise,
  ]);
  const predictiveDetail = predictiveState.status === "fulfilled"
    ? predictiveState.value.selected_event_detail
    : null;
  const evidence: Evidence | null = evidenceState.status === "fulfilled"
    ? evidenceState.value
    : predictiveDetail?.evidence ?? null;
  const legacyReport = reportState.status === "fulfilled" ? reportState.value : { report: null, warning: null };
  const report = legacyReport.report ?? predictiveDetail?.report ?? null;
  const activity = activityState.status === "fulfilled" ? activityState.value : null;
  const warnings = [
    legacyReport.warning && !predictiveDetail?.report ? legacyReport.warning : null,
    evidenceState.status === "rejected" && !predictiveDetail?.evidence
      ? `상세 근거 조회 지연: ${warningMessage(evidenceState.reason, "사용 불가")}`
      : null,
    activityState.status === "rejected"
      ? `활동 이력 조회 지연: ${warningMessage(activityState.reason, "사용 불가")}`
      : null,
    assetDetailState.status === "rejected"
      ? `설비 상세 조회 지연: ${warningMessage(assetDetailState.reason, "사용 불가")}`
      : null,
  ].filter((value): value is string => Boolean(value));
  const detail = composeEventDetail({
    event: input.event,
    evidence,
    report,
    activity,
    metrics: input.metrics,
    warnings,
  });
  return assetDetailState.status === "fulfilled"
    ? applyAssetDetailViewModel(detail, assetDetailState.value)
    : detail;
}

export async function submitOperationsDecision(input: {
  projectId: string;
  workspaceId: string;
  eventId: string;
  userId: string;
  actor: string;
  decision: OperationsDecision;
  note: string;
  snapshotBasis: OperationsEvidenceSnapshotBasis | null;
}): Promise<void> {
  if (input.decision === "request_inspection" || input.decision === "review_shutdown") {
    if (!input.snapshotBasis) {
      throw new Error("현재 화면 기준 근거가 아직 로드되지 않아 작업요청을 생성할 수 없습니다.");
    }
    await requestInspectionWorkOrder({
      projectId: input.projectId,
      workspaceId: input.workspaceId,
      eventId: input.eventId,
      snapshotBasis: {
        artifact_id: input.snapshotBasis.artifactId,
        evidence_payload_reference: input.snapshotBasis.evidencePayloadReference,
        asset_id: input.snapshotBasis.assetId,
        event_id: input.snapshotBasis.eventId,
        observed_at: input.snapshotBasis.observedAt,
        model_version: input.snapshotBasis.modelVersion,
        dataset_version: input.snapshotBasis.datasetVersion,
        source_sha256: input.snapshotBasis.sourceSha256,
      },
      idempotencyKey: inspectionRequestIdempotencyKey({
        eventId: input.eventId,
        decision: input.decision,
        userId: input.userId,
        snapshotBasis: input.snapshotBasis,
      }),
    });
  }
  await recordDecision(input.eventId, input.actor, input.decision, input.note);
}

export async function submitOperationsNote(input: {
  eventId: string;
  actor: string;
  body: string;
}): Promise<void> {
  await addNote(input.eventId, input.actor, input.body);
}

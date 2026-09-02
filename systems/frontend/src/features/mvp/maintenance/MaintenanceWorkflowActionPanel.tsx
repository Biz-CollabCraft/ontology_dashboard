import { useCallback, useEffect, useMemo, useState } from "react";
import {
  approveInspectionWorkOrder,
  approveMaintenanceWorkOrder,
  completeInspectionWorkOrder,
  completeMaintenanceAction,
  createOperationsManualRecommendation,
  decideOperationsManualRecommendation,
  getMaintenanceEventLineage,
  getPostMaintenanceProductResults,
  requestInspectionWorkOrder,
  requestMaintenanceReplay,
  startInspectionWorkOrder,
  startMaintenanceAction,
  type MaintenanceActionCode,
  type MaintenanceEventLineageReadModel,
} from "../../../api";
import type { MvpEvidenceSnapshotBasis, MvpRoleLens } from "../api/mvpContracts";

function commandKey(eventId: string, action: string, target: string): string {
  return `mvp-${eventId}-${action}-${target}`.replace(/[^a-zA-Z0-9_.:-]/g, "-").slice(0, 190);
}

function latest<T>(items: T[]): T | null {
  return items.length ? items[items.length - 1] : null;
}

export type MaintenanceWorkflowDisplayStatus =
  | "candidate_recommended"
  | "work_requested"
  | "assigned"
  | "inspection_started"
  | "inspection_completed"
  | "maintenance_started"
  | "maintenance_completed"
  | "observation_pending"
  | "ready_for_reprediction";

function displayStatus(
  lineage: MaintenanceEventLineageReadModel,
  postMaintenancePredictionAvailable = false,
): MaintenanceWorkflowDisplayStatus {
  const action = latest(lineage.maintenance_actions ?? []);
  if (action?.status === "completed") {
    if (postMaintenancePredictionAvailable) return "ready_for_reprediction";
    return action.restart_at ? "observation_pending" : "maintenance_completed";
  }
  if (action?.status === "in_progress") return "maintenance_started";
  if (action?.status === "planned") return "assigned";
  const maintenanceWorkOrder = latest(
    lineage.work_orders.filter((item) => item.work_type === "maintenance"),
  );
  if (maintenanceWorkOrder?.status === "requested") return "inspection_completed";
  const inspectionWorkOrder = latest(
    lineage.work_orders.filter((item) => item.work_type === "inspection"),
  );
  if (inspectionWorkOrder?.status === "completed") return "inspection_completed";
  if (inspectionWorkOrder?.status === "in_progress") return "inspection_started";
  if (inspectionWorkOrder?.status === "approved") return "assigned";
  if (inspectionWorkOrder?.status === "requested") return "work_requested";
  return "candidate_recommended";
}

export function MaintenanceWorkflowActionPanel({
  projectId,
  workspaceId,
  datasetVersionId,
  eventId,
  assetId,
  assetType,
  role,
  snapshotBasis,
  canManage,
  canFieldExecute,
  onChanged,
  onStatusChanged,
}: {
  projectId: string;
  workspaceId: string;
  datasetVersionId: string;
  eventId: string;
  assetId: string;
  assetType: string;
  role: MvpRoleLens;
  snapshotBasis: MvpEvidenceSnapshotBasis | null;
  canManage: boolean;
  canFieldExecute: boolean;
  onChanged?: () => void;
  onStatusChanged?: (status: MaintenanceWorkflowDisplayStatus) => void;
}) {
  const [lineage, setLineage] = useState<MaintenanceEventLineageReadModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [postMaintenancePrediction, setPostMaintenancePrediction] = useState<{
    failureProbability: number;
    statusGrade: "normal" | "attention" | "warning" | "critical";
    observedAt: string;
  } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getMaintenanceEventLineage(projectId, workspaceId, eventId);
      setLineage(next);
      onStatusChanged?.(displayStatus(next, Boolean(postMaintenancePrediction)));
    } catch (reason) {
      setMessage({ tone: "error", text: reason instanceof Error ? reason.message : "작업 상태를 불러오지 못했습니다." });
    } finally {
      setLoading(false);
    }
  }, [eventId, onStatusChanged, postMaintenancePrediction, projectId, workspaceId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const state = useMemo(() => {
    const workOrders = lineage?.work_orders ?? [];
    const inspectionWorkOrder = latest(workOrders.filter((item) => item.work_type === "inspection"));
    const maintenanceWorkOrder = latest(workOrders.filter((item) => item.work_type === "maintenance"));
    const inspectionResult = latest(lineage?.inspection_results ?? []);
    const recommendation = latest(lineage?.recommendations ?? []);
    const action = latest(lineage?.maintenance_actions ?? []);
    const maintenanceEvent = latest(lineage?.maintenance_events ?? []);
    const costAnalysis = latest(
      (lineage?.cost_analyses ?? []).filter(
        (item) => item.based_on.inspection_result_id === inspectionResult?.inspection_result_id,
      ),
    );
    const selectedCostOption = costAnalysis
      ? costAnalysis.options.find((item) => item.option_id === costAnalysis.lowest_calculated_cost_option_id)
        ?? costAnalysis.options.find((item) => item.calculation_status === "calculated")
        ?? null
      : null;
    return {
      inspectionWorkOrder,
      maintenanceWorkOrder,
      inspectionResult,
      recommendation,
      action,
      maintenanceEvent,
      costAnalysis,
      selectedCostOption,
    };
  }, [lineage]);

  useEffect(() => {
    const maintenanceEventId = state.maintenanceEvent?.maintenance_event_id;
    if (!maintenanceEventId || !state.action?.restart_at || postMaintenancePrediction) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    const poll = async () => {
      try {
        const result = await getPostMaintenanceProductResults(
          projectId,
          workspaceId,
          assetId,
          maintenanceEventId,
          controller.signal,
        );
        if (result) {
          setPostMaintenancePrediction({
            failureProbability: result.failure_probability,
            statusGrade: result.status_grade,
            observedAt: result.observed_at,
          });
          onStatusChanged?.("ready_for_reprediction");
          setMessage({ tone: "success", text: "정비 후 관측과 예측 처리가 완료됐습니다." });
          return;
        }
      } catch {
        if (controller.signal.aborted) return;
      }
      if (!stopped) timer = setTimeout(() => void poll(), 1_500);
    };

    onStatusChanged?.("observation_pending");
    void poll();
    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [
    assetId,
    onStatusChanged,
    postMaintenancePrediction,
    projectId,
    state.action?.restart_at,
    state.maintenanceEvent?.maintenance_event_id,
    workspaceId,
  ]);

  const run = async (label: string, command: () => Promise<unknown>) => {
    setRunning(true);
    setMessage(null);
    try {
      await command();
      setMessage({ tone: "success", text: `${label} 처리가 완료됐습니다.` });
      await refresh();
      onChanged?.();
    } catch (reason) {
      setMessage({ tone: "error", text: reason instanceof Error ? reason.message : `${label} 처리에 실패했습니다.` });
    } finally {
      setRunning(false);
    }
  };

  let label = "다음 작업 대기";
  let helper = "현재 역할에서 실행할 수 있는 다음 단계가 없습니다.";
  let enabled = false;
  let command: (() => Promise<unknown>) | null = null;

  if (role === "process_manager") {
    if (!state.inspectionWorkOrder) {
      label = "점검 작업요청 생성";
      helper = snapshotBasis ? "현재 Product Result/Evidence 스냅샷을 기준으로 요청합니다." : "정본 근거가 로드될 때까지 기다려 주세요.";
      enabled = canManage && Boolean(snapshotBasis);
      command = snapshotBasis ? () => requestInspectionWorkOrder({
        projectId,
        workspaceId,
        eventId,
        snapshotBasis: {
          artifact_id: snapshotBasis.artifactId,
          evidence_payload_reference: snapshotBasis.evidencePayloadReference,
          asset_id: snapshotBasis.assetId,
          event_id: snapshotBasis.eventId,
          observed_at: snapshotBasis.observedAt,
          model_version: snapshotBasis.modelVersion,
          dataset_version: snapshotBasis.datasetVersion,
          source_sha256: snapshotBasis.sourceSha256,
        },
        idempotencyKey: commandKey(eventId, "inspection-request", snapshotBasis.artifactId ?? eventId),
      }) : null;
    } else if (state.inspectionWorkOrder.status === "requested") {
      label = "점검 작업요청 승인";
      helper = "승인 후 현장 관리자가 점검을 시작할 수 있습니다.";
      enabled = canManage;
      command = () => approveInspectionWorkOrder({
        projectId, workspaceId, workOrderId: state.inspectionWorkOrder!.work_order_id,
        idempotencyKey: commandKey(eventId, "inspection-approve", state.inspectionWorkOrder!.work_order_id),
      });
    } else if (state.inspectionResult && !state.recommendation) {
      label = "정비안 생성";
      helper = state.costAnalysis && state.selectedCostOption
        ? "검토한 비용 분석을 근거로 Operations 수동 정비안을 생성합니다."
        : "먼저 아래 비용 분석을 실행해 참고 결과를 확인하세요.";
      enabled = canManage && Boolean(state.costAnalysis && state.selectedCostOption);
      command = state.costAnalysis && state.selectedCostOption ? () => createOperationsManualRecommendation({
        projectId,
        workspaceId,
        inspectionResultId: state.inspectionResult!.inspection_result_id,
        actionCode: state.selectedCostOption!.action_code,
        costAnalysisId: state.costAnalysis!.analysis_id,
        costOptionId: state.selectedCostOption!.option_id,
        actionCandidateId: state.selectedCostOption!.action_candidate_id,
        idempotencyKey: commandKey(eventId, "recommendation-create", state.costAnalysis!.analysis_id),
      }) : null;
    } else if (state.recommendation && !state.maintenanceWorkOrder) {
      label = "정비안 승인";
      helper = "비용은 참고값이며 이 버튼이 사람의 명시적 정비 승인입니다.";
      enabled = canManage && !["accepted", "rejected"].includes(state.recommendation.status);
      command = () => decideOperationsManualRecommendation({
        projectId,
        workspaceId,
        recommendationId: state.recommendation!.recommendation_id,
        disposition: "accept",
        idempotencyKey: commandKey(eventId, "recommendation-accept", state.recommendation!.recommendation_id),
      });
    } else if (state.maintenanceWorkOrder?.status === "requested") {
      label = "정비 WorkOrder 승인";
      helper = "Runtime Replay session을 만든 뒤 정비 Action을 계획합니다.";
      enabled = canManage;
      command = () => approveMaintenanceWorkOrder({
        projectId,
        workspaceId,
        workOrderId: state.maintenanceWorkOrder!.work_order_id,
        datasetVersionId,
        idempotencyKey: commandKey(eventId, "maintenance-approve", state.maintenanceWorkOrder!.work_order_id),
      });
    }
  } else {
    if (state.inspectionWorkOrder?.status === "approved") {
      label = "점검 시작";
      helper = "SOP를 확인한 뒤 현장 점검을 시작합니다.";
      enabled = canFieldExecute;
      command = () => startInspectionWorkOrder({
        projectId, workspaceId, workOrderId: state.inspectionWorkOrder!.work_order_id,
        idempotencyKey: commandKey(eventId, "inspection-start", state.inspectionWorkOrder!.work_order_id),
      });
    } else if (state.inspectionWorkOrder?.status === "in_progress") {
      const actionCode: MaintenanceActionCode = assetType.toLowerCase() === "compressor"
        ? "COOLING_SYSTEM_RESTORE"
        : "TOOL_REPLACEMENT";
      label = "점검 결과 기록·완료";
      helper = "현재 데모 점검값을 기록하고 정비 필요 결과를 제출합니다.";
      enabled = canFieldExecute;
      command = () => completeInspectionWorkOrder({
        projectId, workspaceId, workOrderId: state.inspectionWorkOrder!.work_order_id, actionCode,
        idempotencyKey: commandKey(eventId, "inspection-complete", state.inspectionWorkOrder!.work_order_id),
      });
    } else if (state.action?.status === "planned") {
      label = "정비 시작";
      helper = "승인된 Maintenance Action을 시작합니다.";
      enabled = canFieldExecute;
      command = () => startMaintenanceAction({
        projectId, workspaceId, maintenanceActionId: state.action!.maintenance_action_id,
        idempotencyKey: commandKey(eventId, "maintenance-start", state.action!.maintenance_action_id),
      });
    } else if (state.action?.status === "in_progress") {
      label = "정비 완료";
      helper = "정비 결과를 기록하고 immutable Maintenance Event를 생성합니다.";
      enabled = canFieldExecute;
      command = () => completeMaintenanceAction({
        projectId,
        workspaceId,
        maintenanceActionId: state.action!.maintenance_action_id,
        actionCode: state.action!.action_code,
        idempotencyKey: commandKey(eventId, "maintenance-complete", state.action!.maintenance_action_id),
      });
    } else if (state.maintenanceEvent && !state.action?.restart_at) {
      label = "정비 후 관측 재개";
      helper = "정비 상태 patch를 반영한 Runtime Overlay 재생을 요청합니다.";
      enabled = canFieldExecute;
      command = () => requestMaintenanceReplay({
        projectId,
        workspaceId,
        maintenanceEventId: state.maintenanceEvent!.maintenance_event_id,
        idempotencyKey: commandKey(eventId, "maintenance-replay", state.maintenanceEvent!.maintenance_event_id),
      });
    }
  }

  if (postMaintenancePrediction) {
    const percent = (postMaintenancePrediction.failureProbability * 100).toFixed(2);
    const isNormal = postMaintenancePrediction.statusGrade === "normal";
    label = isNormal ? "정상 운영 중" : "정비 후 위험 지속";
    helper = isNormal
      ? `정비 후 예측 위험도 ${percent}% · Overlay 공정이 계속 진행 중입니다.`
      : `정비 후 예측 위험도 ${percent}% · 추가 점검 또는 정비 판단이 필요합니다.`;
    enabled = false;
    command = null;
  } else if (state.action?.restart_at) {
    label = "정비 후 관측 수집 중";
    helper = "대상 설비 Overlay Observation을 생성하고 예측 결과를 기다리고 있습니다.";
    enabled = false;
    command = null;
  }

  return (
    <section className="mvp-maintenance-workflow-panel" aria-label="Closed-loop 작업 실행">
      <header><div><span>Closed-loop</span><strong>{role === "process_manager" ? "생산 관리자 작업" : "현장 관리자 작업"}</strong></div><button type="button" className="mvp-icon-button" onClick={() => void refresh()} aria-label="작업 상태 새로고침">↻</button></header>
      <p>{loading ? "작업 상태를 확인하고 있습니다." : helper}</p>
      <button
        type="button"
        className="mvp-button primary"
        disabled={loading || running || !enabled || !command}
        onClick={() => command && void run(label, command)}
      >
        {running ? "처리 중" : label}
      </button>
      {message ? <small className={message.tone === "error" ? "mvp-cost-error" : "mvp-workflow-success"}>{message.text}</small> : null}
    </section>
  );
}

import type { OperationsClosedLoopAvailableAction, OperationsClosedLoopLifecycleStep, OperationsEventDetailModel } from "../api/operationsContracts";

export const PHASES = ["이상 감지", "이상 확인", "현장 점검", "조치 검토·작업", "조치 후 상태 확인"] as const;
const PHASE: Record<OperationsClosedLoopLifecycleStep, number> = {
  prediction: 0, evidence: 1, decision: 1,
  inspection_requested: 2, inspection_approved: 2, inspection_in_progress: 2,
  inspection_completed: 3, inspection_closed_no_action: 4, inspection_data_check_required: 1,
  recommendation_proposed: 3, maintenance_requested: 3,
  maintenance_approved: 3, maintenance_in_progress: 3, maintenance_completed: 4,
  post_maintenance_observation_pending: 4, ready_for_reprediction: 4,
};
export function currentPhase(detail: OperationsEventDetailModel): number | null {
  const step = detail.closedLoop?.lifecycleSummary?.currentStep;
  return step ? PHASE[step] ?? null : null;
}
export const ACTION_META: Record<string, { label: string; role: string; permission: string }> = {
  request_inspection_work_order: { label: "점검 요청", role: "process_manager", permission: "events.decision" },
  create_inspection_work_order: { label: "점검 요청", role: "process_manager", permission: "events.decision" },
  request_inspection: { label: "점검 요청", role: "process_manager", permission: "events.decision" },
  accept_inspection_work_order: { label: "점검 요청 수락", role: "process_engineer", permission: "field.tasks.update" },
  start_inspection_work_order: { label: "현장 점검 시작", role: "process_engineer", permission: "field.tasks.update" },
  start_inspection: { label: "현장 점검 시작", role: "process_engineer", permission: "field.tasks.update" },
  complete_inspection_work_order: { label: "점검 결과 등록", role: "process_engineer", permission: "field.tasks.update" },
  complete_inspection: { label: "점검 결과 등록", role: "process_engineer", permission: "field.tasks.update" },
  calculate_maintenance_cost: { label: "정비 비용 분석", role: "process_manager", permission: "events.decision" },
  create_operations_manual_recommendation: { label: "정비 요청 준비", role: "process_manager", permission: "events.decision" },
  decide_operations_manual_recommendation: { label: "정비안 승인", role: "process_manager", permission: "events.decision" },
  approve_maintenance_work_order: { label: "정비 작업 승인", role: "process_manager", permission: "events.decision" },
  start_maintenance_action: { label: "정비 시작", role: "maintenance_technician", permission: "field.tasks.update" },
  complete_maintenance_action: { label: "작업 완료 기록", role: "maintenance_technician", permission: "field.tasks.update" },
  request_maintenance_replay: { label: "조치 후 관측 재개", role: "maintenance_technician", permission: "field.tasks.update" },
};
export function workflowActions(detail: OperationsEventDetailModel, roles: string[], permissions: string[]) {
  const actions = detail.closedLoop?.availableActions ?? [];
  const primary = detail.closedLoop?.primaryAction;
  const sorted = [...actions].sort((a, b) => Number(b.actionId === primary?.actionId) - Number(a.actionId === primary?.actionId));
  const seen = new Set<string>();
  return sorted.filter(action => {
    if (!ACTION_META[action.actionId] || seen.has(action.actionId)) return false;
    seen.add(action.actionId);
    return true;
  }).slice(0, 2).map(action => ({
    ...action, label: ACTION_META[action.actionId].label,
    reason: action.disabledReason || (!action.targetId ? "조치 대상을 확인할 수 없습니다." : null)
      || (!roles.includes(ACTION_META[action.actionId].role) || !permissions.includes(ACTION_META[action.actionId].permission)
        ? "담당 역할의 확인이 필요합니다." : null)
      || (detail.assetDetailStatus?.isStale || detail.assetDetailStatus?.isDataQualityHold || detail.evidenceContext?.temporalStatus === "stale" ? "최신 근거를 확인한 뒤 진행해 주세요." : null),
  }));
}
export function actionAllowed(actions: OperationsClosedLoopAvailableAction[], ids: string[], targetId: string | null | undefined): boolean {
  return Boolean(targetId && actions.some(action => ids.includes(action.actionId) && action.targetId === targetId && !action.disabledReason));
}

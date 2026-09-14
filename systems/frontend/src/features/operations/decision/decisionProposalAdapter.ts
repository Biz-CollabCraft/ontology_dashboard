import type { OperationsEvidenceSnapshotBasis, OperationsEventDetailModel } from "../api/operationsContracts";
import { workflowActions } from "./decisionWorkspaceModel";

// UI view model. The wire response is validated and adapted below.
import { ApiError, requestManufacturingDecisionSession } from "../../../api";
export const DECISION_ACTION_LABELS = {
  MONITOR: "계속 모니터링",
  REQUEST_ADDITIONAL_DIAGNOSIS: "추가 진단 요청",
  REQUEST_INSPECTION: "점검 요청",
  REQUEST_MAINTENANCE: "정비 요청",
  REVIEW_PLANNED_MAINTENANCE: "계획 정비 검토",
} as const;
export type DecisionAction = keyof typeof DECISION_ACTION_LABELS;
export type DecisionFact = { text: string; evidence_refs: string[]; owner_domain?: string; as_of?: string | null };
export type DecisionConflict = DecisionFact & { comparison?: { planningMinutes: number; maintenanceMinutes: number } };
export type PlanningCondition = "production_impact" | "expected_downtime" | "maintenance_window" | "required_parts" | "technician_readiness" | "concurrent_work";
export interface DecisionProposal {
  proposal_id: string;
  recommended_action: DecisionAction | null;
  abstain_reason?: string | null;
  alternative_actions: DecisionAction[];
  confidence: "low" | "medium" | "high";
  reasoning_summary: string;
  confirmed_facts: DecisionFact[];
  uncertainties: DecisionFact[];
  conflicts: DecisionConflict[];
  additional_information_needed: DecisionFact[];
  evidence_refs: string[];
  human_approval_required: true;
  planning_conditions?: Partial<Record<PlanningCondition, DecisionFact>>;
}
export interface DecisionScope {
  projectId: string; workspaceId: string; eventId: string; assetId: string;
}
export interface DecisionSession {
  session_id: string;
  scope: DecisionScope;
  snapshot_basis: OperationsEvidenceSnapshotBasis;
  expires_at: string;
  status: "investigating" | "completed" | "abstained" | "failed";
  steps: { id: string; label: string; status: "pending" | "running" | "completed" | "failed" }[];
  proposal: DecisionProposal | null;
  // Server Policy Guard owns eligibility and concrete execution binding.
  policy_guard: {
    action: DecisionAction; allowed: boolean; reason: string | null;
    execution?: { actionId: string; targetId: string; targetType: string };
  }[];
}
export type DecisionProposalState =
  | { status: "loading" }
  | { status: "unavailable"; reason: string }
  | { status: "stale"; reason: string }
  | { status: "ready"; session: DecisionSession };
export type DecisionProposalAdapter = (context: DecisionScope & { snapshotBasis: OperationsEvidenceSnapshotBasis | null; role?: string; sessionId?: string }, signal: AbortSignal) => Promise<DecisionProposalState>;

export const loadDecisionProposal: DecisionProposalAdapter = async (context, signal) => {
  if (!context.snapshotBasis || basisKeys.some(k => !context.snapshotBasis?.[k]))
    return { status: "unavailable", reason: "판단 근거 연결을 확인해 주세요." };
  if (Date.parse(context.snapshotBasis.observedAt!) > Date.now())
    return { status: "unavailable", reason: "관측 시각이 현재보다 미래입니다. 관측 시각 이후 다시 판단하거나 공장 현황에서 현재 시각의 관측을 선택해 주세요." };
  const query = new URLSearchParams({ project_id: context.projectId, workspace_id: context.workspaceId,
    evidence_snapshot_id: context.snapshotBasis.artifactId!, decision_as_of: context.snapshotBasis.observedAt!,
    role: context.role ?? "process_manager" });
  try {
    const payload = await requestManufacturingDecisionSession(context.assetId, query, signal, context.sessionId);
    return adaptDecisionSession(payload);
  } catch (error) {
    if (signal.aborted) throw error;
    if (error instanceof ApiError && error.status === 409)
      return { status: "stale", reason: "판단 근거가 변경되었습니다. 최신 상태에서 다시 판단해 주세요." };
    return { status: "unavailable", reason: error instanceof ApiError && error.status === 403
      ? "현재 역할의 판단 조회 권한을 확인해 주세요." : "판단 정보를 불러오지 못했습니다. 서비스와 근거 연결을 확인해 주세요." };
  }
};
const basisKeys: (keyof OperationsEvidenceSnapshotBasis)[] = ["artifactId", "evidencePayloadReference", "assetId", "eventId", "observedAt", "modelVersion", "datasetVersion", "sourceSha256"];
export function validateDecisionState(state: DecisionProposalState, scope: DecisionScope, detail: OperationsEventDetailModel, now = Date.now()): DecisionProposalState {
  if (state.status !== "ready") return state;
  const s = state.session, basis = detail.snapshotBasis;
  if (!basis || basisKeys.some(k => !basis[k] || basis[k] !== s.snapshot_basis[k])
    || Object.keys(scope).some(k => scope[k as keyof DecisionScope] !== s.scope[k as keyof DecisionScope])) {
    return { status: "stale", reason: "선택한 이상 건과 판단 후보의 근거가 일치하지 않습니다." };
  }
  if (!Number.isFinite(Date.parse(s.expires_at)) || Date.parse(s.expires_at) <= now
    || detail.assetDetailStatus?.isStale || detail.assetDetailStatus?.isDataQualityHold
    || detail.evidenceContext?.temporalStatus === "stale") {
    return { status: "stale", reason: "판단 근거가 갱신되었습니다. 최신 판단 후보를 확인해 주세요." };
  }
  return state;
}
export function proposalActions(state: DecisionProposalState, roles: string[], permissions: string[]) {
  if (state.status !== "ready" || state.session.status !== "completed" || !state.session.proposal?.recommended_action) return [];
  const p = state.session.proposal;
  const expiresAt = Date.parse(state.session.expires_at);
  if (p.human_approval_required !== true || !Number.isFinite(expiresAt) || expiresAt <= Date.now()) return [];
  return [...new Set([p.recommended_action, ...p.alternative_actions])]
    .filter((a): a is DecisionAction => a !== null && Object.hasOwn(DECISION_ACTION_LABELS, a)).slice(0, 2).map(action => {
      const guards = state.session.policy_guard.filter(g => g.action === action);
      const guard = guards.length === 1 ? guards[0] : undefined;
      const reason = !guard?.allowed ? guard?.reason || "판단 권한을 확인할 수 없습니다."
        : !roles.includes("process_manager") || !permissions.includes("events.decision") ? "생산 관리자 판단 권한이 필요합니다." : null;
      return { action, label: DECISION_ACTION_LABELS[action], recommended: action === p.recommended_action, reason, guard };
    });
}
export function proposalExecution(state: DecisionProposalState, action: DecisionAction, detail: OperationsEventDetailModel, roles: string[], permissions: string[]) {
  const option = proposalActions(state, roles, permissions).find(a => a.action === action);
  const binding = option?.guard?.execution;
  // Deliberately no binding for monitor, diagnosis or planned maintenance until
  // their backend command/review contracts exist. Cost calculation is not planning.
  const supported: Partial<Record<DecisionAction, string[]>> = {
    REQUEST_INSPECTION: ["request_inspection_work_order", "create_inspection_work_order", "request_inspection"],
    REQUEST_MAINTENANCE: ["create_operations_manual_recommendation"],
  };
  if (option?.reason || !binding || !supported[action]?.includes(binding.actionId)) return null;
  return workflowActions(detail, roles, permissions).find(a =>
    !a.reason && a.actionId === binding.actionId && a.targetId === binding.targetId && a.targetType === binding.targetType) ?? null;
}


function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid decision object");
  return value as Record<string, unknown>;
}
function string(value: unknown): string { if (typeof value !== "string" || !value.trim()) throw new Error("invalid decision string"); return value; }
function list(value: unknown): unknown[] { if (!Array.isArray(value)) throw new Error("invalid decision list"); return value; }
function strings(value: unknown): string[] { return list(value).map(string); }
function action(value: unknown): DecisionAction {
  const valueString = string(value);
  if (!Object.hasOwn(DECISION_ACTION_LABELS, valueString)) throw new Error("unknown decision action");
  return valueString as DecisionAction;
}
function fact(value: unknown): DecisionFact {
  const f = object(value), refs = strings(f.source_refs);
  if (!refs.length) throw new Error("ungrounded decision fact");
  return { text: string(f.summary), evidence_refs: refs,
    ...(f.owner_domain ? { owner_domain: string(f.owner_domain) } : {}),
    ...(f.as_of ? { as_of: string(f.as_of) } : {}) };
}
function conflict(value: unknown): DecisionConflict {
  const f = object(value), result: DecisionConflict = fact(value);
  if (f.conflict_type === "downtime_assumption_mismatch") {
    const values = object(f.values);
    const planning = values.planning_minutes, maintenance = values.maintenance_minutes;
    if (typeof planning !== "number" || !Number.isFinite(planning) || planning < 0
      || typeof maintenance !== "number" || !Number.isFinite(maintenance) || maintenance < 0)
      throw new Error("invalid downtime conflict values");
    result.comparison = { planningMinutes: planning, maintenanceMinutes: maintenance };
  }
  return result;
}
const toolLabels: Record<string,string> = { get_asset_condition: "설비 상태 확인", get_inspection_context: "점검 기록 확인",
  get_maintenance_context: "정비 기록 확인", get_production_context: "생산 영향 확인", get_resource_readiness: "정비 준비 상태 확인" };
export function adaptDecisionSession(payload: unknown): DecisionProposalState {
  const response = object(payload), s = object(response.session), identity = object(s.identity);
  if (s.schema_version !== "manufacturing-decision-session-v1.0" || s.mutation_attempted !== false)
    throw new Error("invalid decision session contract");
  const status = string(s.status);
  if (status === "stale" || status === "closed") return { status: "stale", reason: "판단 유효기간이 끝났거나 근거가 변경되었습니다." };
  const statuses: Record<string,DecisionSession["status"]> = { created: "investigating", assessing: "investigating", waiting_for_tool: "investigating",
    ready_for_review: "completed", abstained: "abstained", failed: "failed" };
  if (!statuses[status]) throw new Error("unknown decision session status");
  const b = object(s.snapshot_basis);
  const snapshot: OperationsEvidenceSnapshotBasis = {
    artifactId: string(b.artifact_id), evidencePayloadReference: string(b.evidence_payload_reference), assetId: string(b.asset_id),
    eventId: string(b.event_id), observedAt: string(b.observed_at), modelVersion: string(b.model_version),
    datasetVersion: string(b.dataset_version), sourceSha256: string(b.source_sha256),
  };
  if (identity.asset_id !== snapshot.assetId || identity.evidence_snapshot_id !== snapshot.artifactId) throw new Error("decision identity mismatch");
  const expires = string(s.expires_at);
  if (!Number.isFinite(Date.parse(expires))) throw new Error("invalid expiry");
  const allowed = list(s.allowed_actions).map(action);
  let proposal: DecisionProposal | null = null;
  if (s.proposal !== null) {
    const p = object(s.proposal);
    if (p.schema_version !== "manufacturing-decision-proposal-v1.0" || p.human_approval_required !== true) throw new Error("invalid proposal boundary");
    const recommended = p.recommended_action === null ? null : action(p.recommended_action);
    const alternatives = list(p.alternative_actions).map(action);
    if (recommended && !allowed.includes(recommended) || alternatives.some(a => !allowed.includes(a))) throw new Error("proposal outside policy");
    if (recommended === null && (status !== "abstained" || !p.abstain_reason)) throw new Error("invalid abstention");
    if (status === "abstained" && recommended !== null) throw new Error("invalid abstention action");
    const confidence = string(p.confidence);
    if (!["low","medium","high"].includes(confidence)) throw new Error("invalid confidence");
    proposal = { proposal_id: string(s.decision_session_id), recommended_action: recommended, alternative_actions: alternatives,
      confidence: confidence as DecisionProposal["confidence"], reasoning_summary: string(p.reasoning_summary),
      confirmed_facts: list(p.confirmed_facts).map(fact), conflicts: list(p.conflicts).map(conflict),
      uncertainties: strings(p.uncertainties).map(text => ({text, evidence_refs: []})),
      additional_information_needed: strings(p.additional_information_needed).map(text => ({text, evidence_refs: []})),
      evidence_refs: strings(p.evidence_refs), human_approval_required: true,
      abstain_reason: p.abstain_reason === null || p.abstain_reason === undefined ? null : string(p.abstain_reason),
    };
  }
  if (status === "ready_for_review" && !proposal?.recommended_action) throw new Error("missing ready proposal");
  const bindings = response.execution_bindings === undefined ? {} : object(response.execution_bindings);
  return { status: "ready", session: {
    session_id: string(s.decision_session_id), scope: { projectId: string(identity.project_id), workspaceId: string(identity.workspace_id),
      eventId: snapshot.eventId!, assetId: string(identity.asset_id) }, snapshot_basis: snapshot, expires_at: expires,
    status: statuses[status], proposal,
    steps: list(s.tool_calls).map(raw => { const t = object(raw); return { id: string(t.tool_call_id),
      label: toolLabels[string(t.tool_name)] ?? string(t.tool_name),
      status: t.status === "available" ? "completed" : t.completed_at ? "failed" : "running" }; }),
    policy_guard: allowed.map(a => { const bind = bindings[a] === undefined ? null : object(bindings[a]);
      return { action: a, allowed: true, reason: null, ...(bind ? { execution: {
        actionId: string(bind.actionId), targetId: string(bind.targetId), targetType: string(bind.targetType),
      }} : {}) }; }),
  } };
}

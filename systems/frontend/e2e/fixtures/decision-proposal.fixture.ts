import type { DecisionProposalAdapter, DecisionProposalState, DecisionScope } from "../../src/features/operations/decision/decisionProposalAdapter";
import type { OperationsEvidenceSnapshotBasis } from "../../src/features/operations/api/operationsContracts";
// UI contract fixture only. Never imported by application code.
export function decisionProposalFixture(context: DecisionScope & { snapshotBasis: OperationsEvidenceSnapshotBasis | null }): DecisionProposalState {
  if (!context.snapshotBasis) return { status: "unavailable", reason: "Fixture requires a snapshot" };
  const { snapshotBasis, ...scope } = context;
  return { status: "ready", session: {
    session_id: "fixture-session", scope, snapshot_basis: snapshotBasis,
    expires_at: new Date(Date.now() + 60000).toISOString(), status: "ready_for_review",
    steps: [{ id: "asset", label: "설비 상태 확인", status: "completed" }],
    policy_guard: [
      { action: "REQUEST_INSPECTION", allowed: true, reason: null, execution: { actionId: "request_inspection_work_order", targetType: "event", targetId: scope.eventId } },
      { action: "REVIEW_PLANNED_MAINTENANCE", allowed: true, reason: null },
    ],
    proposal: {
      proposal_id: "fixture-proposal", recommended_action: "REQUEST_INSPECTION",
      alternative_actions: ["REVIEW_PLANNED_MAINTENANCE"], confidence: "medium",
      reasoning_summary: "점검 결과를 확인한 뒤 정비 범위를 판단할 수 있습니다.",
      confirmed_facts: [{ text: "생산 영향: 높음", evidence_refs: ["fixture://production-impact"] }],
      uncertainties: [{ text: "실제 부품 예약 상태", evidence_refs: [] }],
      conflicts: [{ text: "생산 영향 정지 120분 / 예상 작업 180분", evidence_refs: ["fixture://planning-conflict"] }],
      additional_information_needed: [{ text: "정비 인력 준비 상태", evidence_refs: [] }],
      evidence_refs: ["fixture://production-impact", "fixture://planning-conflict"],
      human_approval_required: true,
    },
  } };
}
export const fixtureAdapter: DecisionProposalAdapter = async context => decisionProposalFixture(context);


// Exact HTTP envelope fixture; the production transport and decoder stay active.
export function decisionSessionWireFixture(context: DecisionScope & { snapshotBasis: OperationsEvidenceSnapshotBasis | null }) {
  const state = decisionProposalFixture(context);
  if (state.status !== "ready") throw new Error("fixture requires basis");
  const s = state.session, p = s.proposal!, b = s.snapshot_basis;
  return { engine: "fixture", execution_bindings: { REQUEST_INSPECTION: s.policy_guard[0].execution }, session: {
    schema_version: "manufacturing-decision-session-v1.0", decision_session_id: s.session_id,
    identity: { organization_id: "fixture-org", project_id: context.projectId, workspace_id: context.workspaceId,
      asset_id: context.assetId, evidence_snapshot_id: b.artifactId, decision_as_of: b.observedAt },
    actor_role: "process_manager", status: "ready_for_review", mutation_attempted: false,
    allowed_actions: s.policy_guard.map(g => g.action), expires_at: s.expires_at,
    snapshot_basis: { artifact_id: b.artifactId, evidence_payload_reference: b.evidencePayloadReference,
      asset_id: b.assetId, event_id: b.eventId, observed_at: b.observedAt, model_version: b.modelVersion,
      dataset_version: b.datasetVersion, source_sha256: b.sourceSha256 },
    tool_calls: [{tool_call_id:"tool-1", tool_name:"get_asset_condition", status:"available", completed_at:b.observedAt}],
    proposal: { ...p, schema_version:"manufacturing-decision-proposal-v1.0", abstain_reason:null,
      confirmed_facts:p.confirmed_facts.map(f => ({summary:f.text,source_refs:f.evidence_refs,owner_domain:"production",as_of:b.observedAt})),
      conflicts:p.conflicts.map(f => ({summary:f.text,source_refs:f.evidence_refs,values:{}})),
      uncertainties:p.uncertainties.map(f => f.text), additional_information_needed:p.additional_information_needed.map(f => f.text) },
  } };
}

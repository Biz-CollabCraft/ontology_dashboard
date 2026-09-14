import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DecisionConditions, DecisionProposalPanel } from "./DecisionProposalPanel";
import { loadDecisionProposal, adaptDecisionSession, proposalActions, proposalExecution, validateDecisionState, type DecisionProposalState } from "./decisionProposalAdapter";
import { applyAssetDetailViewModel, composeEventDetail } from "../api/operationsAdapters";
import type { OperationsEvent } from "../api/operationsContracts";
import { decisionDetailFixture } from "../../../../e2e/fixtures/decision-detail.fixture";
import { decisionProposalFixture, decisionSessionWireFixture } from "../../../../e2e/fixtures/decision-proposal.fixture";
const scope = { projectId: "p", workspaceId: "w", eventId: "event-1", assetId: "asset-1" };
const roles = ["process_manager"], permissions = ["events.decision"];
function setup() {
  const event = { eventId: scope.eventId, assetId: scope.assetId, datasetVersionId: "dataset-1" } as OperationsEvent;
  const detail = applyAssetDetailViewModel(composeEventDetail({ event, evidence: null, report: null, activity: null }), decisionDetailFixture(event.eventId, event.assetId, event.datasetVersionId));
  const state = decisionProposalFixture({ ...scope, snapshotBasis: detail.snapshotBasis });
  if (state.status !== "ready") throw new Error("fixture");
  return { detail, state };
}
let root: Root, host: HTMLDivElement;
beforeEach(() => { Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); host = document.createElement("div"); document.body.append(host); root = createRoot(host); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const click = async (text: string) => { const b = [...host.querySelectorAll("button")].find(b => b.textContent === text); expect(b).toBeDefined(); await act(async () => b!.click()); };
describe("Decision Proposal boundary (fixture-backed)", () => {
  it("explains a future observation without repeatedly calling the API", async () => {
    const {detail} = setup();
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const state = await loadDecisionProposal({...scope, snapshotBasis: {...detail.snapshotBasis!, observedAt: new Date(Date.now()+600000).toISOString()}}, new AbortController().signal);
    expect(state.status).toBe("unavailable");
    if (state.status === "unavailable") expect(state.reason).toContain("관측 시각이 현재보다 미래");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("unavailable API never invents actions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok:false,status:503,json:async () => ({})}));
    const {detail} = setup();
    const state = await loadDecisionProposal({ ...scope, snapshotBasis: detail.snapshotBasis }, new AbortController().signal);
    expect(state.status).toBe("unavailable"); expect(proposalActions(state, roles, permissions)).toEqual([]);
  });
  it("never invents a command absent from backend availableActions", () => {
    const {detail,state} = setup(); detail.closedLoop!.availableActions = [];
    expect(proposalExecution(state,"REQUEST_INSPECTION",detail,roles,permissions)).toBeNull();
  });
  it("requires both role and permission plus Policy Guard approval", () => {
    const {state} = setup();
    expect(proposalActions(state,[],permissions)[0].reason).toBeTruthy();
    expect(proposalActions(state,roles,[])[0].reason).toBeTruthy();
    state.session.policy_guard = [];
    expect(proposalActions(state,roles,permissions)[0].reason).toBeTruthy();
  });
  it("deduplicates and caps decision actions at two", () => {
    const {state} = setup(); state.session.proposal!.alternative_actions = ["REQUEST_INSPECTION","MONITOR","REQUEST_MAINTENANCE"];
    expect(proposalActions(state,roles,permissions).map(a => a.action)).toEqual(["REQUEST_INSPECTION","MONITOR"]);
  });
  it.each(["artifactId","evidencePayloadReference","assetId","eventId","observedAt","modelVersion","datasetVersion","sourceSha256"] as const)("rejects snapshot mismatch: %s", key => {
    const {state,detail} = setup(); state.session.snapshot_basis = { ...state.session.snapshot_basis, [key]: "changed" };
    expect(validateDecisionState(state,scope,detail).status).toBe("stale");
  });
  it("rejects cross-project scope and expiry", () => {
    const {state,detail} = setup();
    expect(validateDecisionState(state,{...scope,projectId:"other"},detail).status).toBe("stale");
    expect(validateDecisionState(state,scope,detail,Date.parse(state.session.expires_at))).toMatchObject({status:"stale"});
  });
  it("blocks stale detail and server-disabled commands", () => {
    const {state,detail} = setup(); detail.assetDetailStatus!.isStale = true;
    const stale = validateDecisionState(state,scope,detail);
    expect(proposalActions(stale,roles,permissions)).toEqual([]);
    expect(proposalExecution(state,"REQUEST_INSPECTION",detail,roles,permissions)).toBeNull();
    detail.assetDetailStatus!.isStale = false; detail.closedLoop!.availableActions[0].disabledReason = "blocked";
    expect(proposalExecution(state,"REQUEST_INSPECTION",detail,roles,permissions)).toBeNull();
  });
  it("never treats cost calculation as planned maintenance", () => {
    const {state,detail} = setup();
    state.session.policy_guard[1].execution = {actionId:"calculate_maintenance_cost",targetId:scope.eventId,targetType:"event"};
    expect(proposalExecution(state,"REVIEW_PLANNED_MAINTENANCE",detail,roles,permissions)).toBeNull();
  });
  it("renders confirmed, uncertainty, conflict and recommendation/alternative separately", async () => {
    const {state,detail} = setup();
    await act(async () => root.render(<><DecisionConditions state={state} detail={detail}/><DecisionProposalPanel state={state} detail={detail} roles={roles} permissions={permissions} refreshing={false} onReview={vi.fn()}/></>));
    for (const t of ["확인됨","미확인","충돌","생산 영향: 높음","실제 부품 예약 상태","120분","추천","대안","점검 요청","계획 정비 검토"]) expect(host.textContent).toContain(t);
  });
  it.each(["loading","unavailable","stale"] as const)("renders %s without proposal buttons", async status => {
    const {detail} = setup();
    const state: DecisionProposalState = status === "loading" ? {status} : {status,reason:"판단 확인 필요"};
    await act(async () => root.render(<DecisionProposalPanel state={state} detail={detail} roles={roles} permissions={permissions} refreshing={false} onReview={vi.fn()}/>));
    expect(host.querySelectorAll("button")).toHaveLength(0); expect(host.querySelector('[role="status"]')).not.toBeNull();
  });
  it("selection only opens human review; a separate step opens existing execution UI", async () => {
    const {state,detail} = setup(); const onReview = vi.fn();
    const render = (s: DecisionProposalState) => <DecisionProposalPanel state={s} detail={detail} roles={roles} permissions={permissions} refreshing={false} onReview={onReview}/>;
    await act(async () => root.render(render(state)));
    await click("점검 요청"); expect(onReview).not.toHaveBeenCalled(); expect(host.textContent).toContain("사용자 검토");
    await click("검토 후 요청 내용 확인"); expect(onReview).toHaveBeenCalledWith("request_inspection_work_order");
    await click("점검 요청");
    await act(async () => root.render(render({status:"stale",reason:"근거 변경"})));
    expect(host.querySelector('[aria-label="사용자 검토"]')).toBeNull();
  });
  it("withdraws expired proposals and refuses approval-free proposals", () => {
    const {state} = setup();
    state.session.expires_at = new Date(Date.now() - 1000).toISOString();
    expect(proposalActions(state, roles, permissions)).toEqual([]);
    state.session.expires_at = new Date(Date.now() + 60000).toISOString();
    Object.assign(state.session.proposal!, {human_approval_required: false});
    expect(proposalActions(state, roles, permissions)).toEqual([]);
  });
  it("renders only supplied session progress and no proposal while investigating", async () => {
    const {state,detail} = setup();
    state.session.status = "investigating";
    state.session.proposal = null;
    state.session.steps.push({id:"production",label:"생산 영향 확인 중",status:"running"});
    await act(async () => root.render(<DecisionProposalPanel state={state} detail={detail} roles={roles} permissions={permissions} refreshing={false} onReview={vi.fn()}/>));
    expect(host.textContent).toContain("생산 영향 확인 중");
    expect(host.querySelectorAll("button")).toHaveLength(0);
  });
  it("planned review exposes all readiness slots without inventing values or commands", async () => {
    const {state,detail} = setup();
    await act(async () => root.render(<DecisionProposalPanel state={state} detail={detail} roles={roles} permissions={permissions} refreshing={false} onReview={vi.fn()}/>));
    await click("계획 정비 검토");
    expect(host.querySelectorAll("dt")).toHaveLength(6);
    expect(host.textContent).toContain("승인 절차가 아직 연결되지 않았습니다.");
  });
});


describe("backend DecisionSession contract", () => {
  it("preserves and renders backend conflict values without numbers in the summary", async () => {
    const {detail} = setup();
    const wire = decisionSessionWireFixture({...scope,snapshotBasis:detail.snapshotBasis});
    Object.assign(wire.session.proposal.conflicts[0], {
      conflict_type: "downtime_assumption_mismatch",
      summary: "생산 영향 계산의 정지시간과 정비 작업 예상시간이 다릅니다.",
      values: {planning_minutes: 120, maintenance_minutes: 180},
    });
    const state = adaptDecisionSession(wire);
    await act(async () => root.render(<DecisionConditions state={state} detail={detail}/>));
    expect(host.textContent).toContain("생산 영향 산정: 120분");
    expect(host.textContent).toContain("예상 정비 작업: 180분");
    expect(host.textContent).toContain("fixture://planning-conflict");
    Object.assign(wire.session.proposal.conflicts[0], {values: {planning_minutes: "120", maintenance_minutes: 180}});
    expect(() => adaptDecisionSession(wire)).toThrow("invalid downtime conflict values");
  });
  it("adapts recommendation, alternative, provenance and execution binding", () => {
    const {detail} = setup();
    const state = adaptDecisionSession(decisionSessionWireFixture({...scope,snapshotBasis:detail.snapshotBasis}));
    expect(proposalActions(state,roles,permissions).map(a => a.action)).toEqual(["REQUEST_INSPECTION","REVIEW_PLANNED_MAINTENANCE"]);
    expect(proposalExecution(state,"REQUEST_INSPECTION",detail,roles,permissions)?.actionId).toBe("request_inspection_work_order");
  });
  it("renders a real abstention without action buttons or confidence", async () => {
    const {detail} = setup(); const wire = decisionSessionWireFixture({...scope,snapshotBasis:detail.snapshotBasis});
    Object.assign(wire.session,{status:"abstained"});
    Object.assign(wire.session.proposal,{recommended_action:null,alternative_actions:[],abstain_reason:"생산 정보 확인 필요"});
    const state=adaptDecisionSession(wire);
    await act(async () => root.render(<DecisionProposalPanel state={state} detail={detail} roles={roles} permissions={permissions} refreshing={false} onReview={vi.fn()}/>));
    expect(host.textContent).toContain("판단 보류"); expect(host.textContent).toContain("생산 정보 확인 필요");
    expect(host.querySelectorAll("button")).toHaveLength(0); expect(host.textContent).not.toContain("추천 신뢰도");
  });
  it.each(["mutation", "outside-policy", "unreferenced-fact", "missing-basis"])("rejects unsafe response: %s", kind => {
    const {detail}=setup(); const wire=decisionSessionWireFixture({...scope,snapshotBasis:detail.snapshotBasis});
    if(kind==="mutation") wire.session.mutation_attempted=true;
    if(kind==="outside-policy") wire.session.allowed_actions=[];
    if(kind==="unreferenced-fact") wire.session.proposal.confirmed_facts[0].source_refs=[];
    if(kind==="missing-basis") wire.session.snapshot_basis.source_sha256=null;
    expect(() => adaptDecisionSession(wire)).toThrow();
  });
  it("creates once and reads the existing session via GET", async () => {
    const {detail}=setup(); const wire=decisionSessionWireFixture({...scope,snapshotBasis:detail.snapshotBasis});
    const fetcher=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>wire});vi.stubGlobal("fetch",fetcher);
    await loadDecisionProposal({...scope,snapshotBasis:detail.snapshotBasis},new AbortController().signal);
    await loadDecisionProposal({...scope,snapshotBasis:detail.snapshotBasis,sessionId:"fixture-session"},new AbortController().signal);
    expect(fetcher.mock.calls.map(c=>c[1].method)).toEqual(["POST","GET"]);
    expect(fetcher.mock.calls[1][0]).toContain("/decision-sessions/fixture-session?");
  });
});

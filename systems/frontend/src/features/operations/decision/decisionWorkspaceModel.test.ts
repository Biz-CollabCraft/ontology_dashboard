import { describe, expect, it } from "vitest";
import { actionAllowed, currentPhase, workflowActions as decisionActions } from "./decisionWorkspaceModel";
import type { OperationsClosedLoopAvailableAction, OperationsEventDetailModel } from "../api/operationsContracts";
const action = (id = "request_inspection_work_order", targetId: string | null = "event-1", disabledReason: string | null = null): OperationsClosedLoopAvailableAction => ({ actionId: id, targetType: "event", targetId, disabledReason });
const detail = (actions: OperationsClosedLoopAvailableAction[]) => ({
  closedLoop: { availableActions: actions, primaryAction: null }, assetDetailStatus: { isStale: false },
}) as OperationsEventDetailModel;
describe("decision workspace policy boundary", () => {
  it("never invents actions when the server provides none", () => {
    expect(decisionActions(detail([]), ["process_manager"], ["events.decision"])).toEqual([]);
  });
  it("keeps disabled reasons and requires a concrete target and role", () => {
    expect(decisionActions(detail([action()]), ["process_engineer"], ["events.decision"])[0].reason).toBeTruthy();
    expect(decisionActions(detail([action()]), ["process_manager"], [])[0].reason).toBeTruthy();
    expect(decisionActions(detail([action(undefined, null)]), ["process_manager"], ["events.decision"])[0].reason).toBeTruthy();
    expect(decisionActions(detail([action(undefined, "event-1", "작업 중")]), ["process_manager"], ["events.decision"])[0].reason).toBe("작업 중");
    expect(decisionActions(detail([action()]), ["process_manager"], ["events.decision"])[0].reason).toBeNull();
  });
  it("limits known actions to two without enabling unsupported commands", () => {
    expect(decisionActions(detail([action("unknown"), action(), action("calculate_maintenance_cost"), action("start_maintenance_action")]), [], [])).toHaveLength(2);
  });
  it("requires the same action target again inside the request form", () => {
    expect(actionAllowed([action()], ["request_inspection_work_order"], "event-2")).toBe(false);
    expect(actionAllowed([action()], ["request_inspection_work_order"], "event-1")).toBe(true);
    expect(actionAllowed([action(undefined, "event-1", "금지")], ["request_inspection_work_order"], "event-1")).toBe(false);
  });
  it("does not call post-maintenance readiness completed or recovered", () => {
    const d = detail([]);
    d.closedLoop!.lifecycleSummary = { currentStep: "ready_for_reprediction", currentStepLabel: "", completedSteps: [], nextStep: null, source: "backend_closed_loop_policy" };
    expect(currentPhase(d)).toBe(4);
    d.closedLoop!.lifecycleSummary = null;
    expect(currentPhase(d)).toBeNull();
  });
});

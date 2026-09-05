import { describe, expect, it } from "vitest";
import type { OpenInspectionWorkOrderReadModel } from "../../../api";
import {
  prioritizeActiveWorkflowCandidates,
  workStatusFromLifecycleStep,
  type WorkOrderCandidate,
} from "./OperationsWorkflowOverviewPage";

function candidate(assetId: string, eventId: string): WorkOrderCandidate {
  return {
    event: { assetId, eventId } as WorkOrderCandidate["event"],
    asset: null,
    suspectedPart: "공구",
  };
}

function workflow(
  assetId: string,
  eventId: string,
  currentStep: OpenInspectionWorkOrderReadModel["current_step"],
): OpenInspectionWorkOrderReadModel {
  return {
    work_order_id: `WO-${eventId}`,
    event_id: eventId,
    asset_id: assetId,
    equipment_id: assetId,
    asset_type: "cnc",
    work_type: "inspection",
    status: currentStep === "inspection_completed" ? "completed" : "in_progress",
    current_step: currentStep,
  };
}

describe("Operations active workflow queue", () => {
  it("keeps one candidate per equipment and anchors it to the active workflow event", () => {
    const active = candidate("CNC-01", "EVENT-OLD");
    const newer = candidate("CNC-01", "EVENT-NEW");
    const other = candidate("CNC-02", "EVENT-OTHER");

    const result = prioritizeActiveWorkflowCandidates(
      [newer, active, other],
      [workflow("CNC-01", "EVENT-OLD", "inspection_completed")],
    );

    expect(result.map((item) => item.event.eventId)).toEqual([
      "EVENT-OLD",
      "EVENT-OTHER",
    ]);
  });

  it("maps inspection and maintenance lifecycle steps to distinct display states", () => {
    expect(workStatusFromLifecycleStep("inspection_requested")).toBe("work_requested");
    expect(workStatusFromLifecycleStep("inspection_in_progress")).toBe("inspection_started");
    expect(workStatusFromLifecycleStep("inspection_completed")).toBe("inspection_completed");
    expect(workStatusFromLifecycleStep("maintenance_in_progress")).toBe("maintenance_started");
    expect(workStatusFromLifecycleStep("post_maintenance_observation_pending")).toBe("observation_pending");
  });
});

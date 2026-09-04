import { describe, expect, it } from "vitest";
import type {
  OperationsAsset,
  OperationsBootstrapModel,
  OperationsEvent,
} from "./api/operationsContracts";
import { resolveMonitoringEvent } from "./OperationsApplication";

function event(assetId: string, eventId: string, observedAt: string): OperationsEvent {
  return { assetId, eventId, observedAt } as OperationsEvent;
}

describe("operations monitoring Event selection", () => {
  it("follows the latest asset Event independently from the workflow Event", () => {
    const workflowEvent = event("CNC-01", "RESULT#T0", "2026-09-04T00:00:00Z");
    const monitoringEvent = event("CNC-01", "RESULT#T1", "2026-09-04T00:10:00Z");
    const model = {
      assets: [{ assetId: "CNC-01", eventId: "RESULT#T1" } as OperationsAsset],
      events: [monitoringEvent, workflowEvent],
    } as OperationsBootstrapModel;

    expect(resolveMonitoringEvent(model, "CNC-01")?.eventId).toBe("RESULT#T1");
    expect(workflowEvent.eventId).toBe("RESULT#T0");
  });

  it("does not borrow another asset Event when the selected asset has no result", () => {
    const model = {
      assets: [{ assetId: "CNC-01", eventId: null } as OperationsAsset],
      events: [event("CNC-02", "RESULT#OTHER", "2026-09-04T00:10:00Z")],
    } as OperationsBootstrapModel;

    expect(resolveMonitoringEvent(model, "CNC-01")).toBeNull();
  });
});

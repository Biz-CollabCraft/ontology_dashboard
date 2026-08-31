import { describe, expect, it } from "vitest";
import type { MaintenanceEventLineageReadModel } from "../../../api";
import type { MvpInspectionGuidance } from "../api/mvpContracts";
import { buildCostRequest, latestEligibleInspection } from "./MaintenanceCostDecisionPanel";

const guidance: MvpInspectionGuidance = {
  sourceType: "demo_sop_fixture",
  sopId: "SOP-CNC-TOOL-001",
  title: "CNC 공구 점검",
  version: "v1",
  referenceLocationLabel: "공구대",
  suggestedCheckMethod: "마모량 확인",
  checklistDraft: ["마모량 확인"],
  maintenanceReviewPrerequisites: {
    label: "정비 검토",
    reviewConditions: ["마모 확인"],
    requiredMeasurements: ["tool_wear_min"],
    humanReviewQuestions: ["교체가 필요한가?"],
    decisionBoundary: "사람이 판단하고 승인한다.",
  },
  safetyLevel: "caution",
  requiresHumanApproval: true,
  sourceRef: "fixture://sop-cnc-tool-001",
  disclaimer: "참고 절차이며 정비 승인이 아닙니다.",
};

function lineage(): MaintenanceEventLineageReadModel {
  return {
    event_id: "EVT-1",
    work_orders: [
      { work_order_id: "WO-OPEN", work_type: "inspection", status: "in_progress" },
      { work_order_id: "WO-DONE", work_type: "inspection", status: "completed" },
    ],
    inspection_results: [
      {
        inspection_result_id: "RESULT-OPEN",
        work_order_id: "WO-OPEN",
        event_id: "EVT-1",
        asset_id: "CNC-1",
        equipment_id: "CNC-1",
        outcome: "maintenance_recommended",
        recorded_at: "2026-08-31T02:00:00Z",
      },
      {
        inspection_result_id: "RESULT-DONE",
        work_order_id: "WO-DONE",
        event_id: "EVT-1",
        asset_id: "CNC-1",
        equipment_id: "CNC-1",
        outcome: "maintenance_recommended",
        recorded_at: "2026-08-31T01:00:00Z",
      },
    ],
    cost_analyses: [],
    recommendations: [],
  };
}

describe("MaintenanceCostDecisionPanel helpers", () => {
  it("uses only a completed inspection with a maintenance recommendation", () => {
    expect(latestEligibleInspection(lineage())?.inspection_result_id).toBe("RESULT-DONE");
  });

  it("does not invent missing cost values and records the consulted SOP", () => {
    const form = {
      immediate: {
        partsCost: "1000",
        laborDuration: "",
        laborRate: "",
        externalCost: "",
        downtime: "",
        productionLossRate: "",
        failureLoss: "",
      },
      planned_window: {
        partsCost: "",
        laborDuration: "",
        laborRate: "",
        externalCost: "",
        downtime: "",
        productionLossRate: "",
        failureLoss: "",
      },
      reinspect_after: {
        partsCost: "",
        laborDuration: "",
        laborRate: "",
        externalCost: "",
        downtime: "",
        productionLossRate: "",
        failureLoss: "",
      },
      no_action_baseline: {
        partsCost: "",
        laborDuration: "",
        laborRate: "",
        externalCost: "",
        downtime: "",
        productionLossRate: "",
        failureLoss: "",
      },
    };

    const request = buildCostRequest(form, guidance, "EVT-1");

    expect(request.sop_id).toBe("SOP-CNC-TOOL-001");
    expect(request.scenarios).toHaveLength(4);
    expect(request.scenarios[0].parts_cost).toEqual({
      low_minor: 1000,
      base_minor: 1000,
      high_minor: 1000,
    });
    expect(request.scenarios[0].labor_duration).toBeNull();
    expect(request.assumptions.join(" ")).toContain("임의 추정");
  });
});

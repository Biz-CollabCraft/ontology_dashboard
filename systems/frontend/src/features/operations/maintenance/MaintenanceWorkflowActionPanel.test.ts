import { describe, expect, it } from "vitest";
import { ApiError } from "../../../api";
import {
  postMaintenancePollingFailure,
  supportsInspectionOutcome,
} from "./MaintenanceWorkflowActionPanel";

describe("post-maintenance result polling", () => {
  it("surfaces authorization and contract failures immediately", () => {
    expect(postMaintenancePollingFailure(
      new ApiError(403, "forbidden", "권한이 없습니다."),
      1,
    )).toEqual({
      message: "정비 후 결과 조회가 거부되었습니다: 권한이 없습니다.",
      stop: true,
    });
  });

  it("retries transient failures but surfaces repeated failures", () => {
    expect(postMaintenancePollingFailure(new Error("connection reset"), 2)).toEqual({
      message: null,
      stop: false,
    });
    expect(postMaintenancePollingFailure(new Error("connection reset"), 3)).toEqual({
      message: "정비 후 결과 조회가 3회 연속 실패했습니다: connection reset",
      stop: false,
    });
  });
});

describe("inspection outcome support", () => {
  it("allows non-CNC equipment to close an inspection without maintenance", () => {
    expect(supportsInspectionOutcome("compressor", "no_action_required")).toBe(true);
    expect(supportsInspectionOutcome("compressor", "data_check_required")).toBe(true);
  });

  it("keeps maintenance execution limited to supported CNC equipment", () => {
    expect(supportsInspectionOutcome("compressor", "maintenance_recommended")).toBe(false);
    expect(supportsInspectionOutcome("cnc", "maintenance_recommended")).toBe(true);
  });
});

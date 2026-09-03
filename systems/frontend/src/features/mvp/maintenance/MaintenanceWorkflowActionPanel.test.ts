import { describe, expect, it } from "vitest";
import { ApiError } from "../../../api";
import {
  displayStatus,
  postMaintenancePollingFailure,
  postMaintenanceRuntimeFailure,
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

  it("separates terminal history failure from transient observation warming", () => {
    const failed = {
      event_id: "EVT-1",
      work_orders: [],
      inspection_results: [],
      cost_analyses: [],
      recommendations: [],
      runtime_status: "history_insufficient" as const,
      runtime_state: {
        status: "history_insufficient" as const,
        failure_reason: "35 prior observations are unavailable",
      },
    };

    expect(postMaintenanceRuntimeFailure(failed)).toContain("35 prior observations");
    expect(displayStatus(failed)).toBe("prediction_blocked");
    expect(postMaintenanceRuntimeFailure({
      ...failed,
      runtime_status: "warming_up",
      runtime_state: { status: "warming_up" },
    })).toBeNull();
  });
});

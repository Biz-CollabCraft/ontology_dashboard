import { describe, expect, it } from "vitest";
import { ApiError } from "../../../api";
import {
  postMaintenancePollingDelay,
  postMaintenancePollingFailure,
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

  it("polls quickly until the first result and keeps refreshing Backend truth afterwards", () => {
    expect(postMaintenancePollingDelay(false, 0)).toBe(1_500);
    expect(postMaintenancePollingDelay(true, 0)).toBe(5_000);
    expect(postMaintenancePollingDelay(true, 3)).toBe(10_000);
  });
});

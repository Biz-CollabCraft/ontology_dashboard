import { describe, expect, it } from "vitest";
import { canMaterializeAgentReviewSummary } from "./permissions";

describe("MVP permissions", () => {
  it("keeps Agent Review Summary materialization behind the dedicated permission", () => {
    expect(canMaterializeAgentReviewSummary(["events.read", "events.decision"])).toBe(false);
    expect(canMaterializeAgentReviewSummary(["agent.review.materialize"])).toBe(true);
  });
});

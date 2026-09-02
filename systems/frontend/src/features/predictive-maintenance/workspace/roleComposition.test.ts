import { describe, expect, it } from "vitest";
import { baseReliabilityComposition, resolveReliabilityComposition } from "./roleComposition";

describe("role composed reliability workspace", () => {
  it("uses materially different first-screen blocks by role", () => {
    expect(baseReliabilityComposition("executive", "reports")).toEqual([
      "risk-metrics", "factory-map", "report-summary", "business-kpis", "production-exposure", "decision-queue", "risk-portfolio", "context-evidence",
    ]);
    expect(baseReliabilityComposition("operations", "operations").slice(0, 4)).toEqual([
      "risk-metrics", "factory-map", "decision-queue", "production-exposure",
    ]);
    expect(baseReliabilityComposition("engineering", "overview").slice(0, 4)).toEqual([
      "risk-metrics", "factory-map", "risk-queue", "feature-trend",
    ]);
    expect(baseReliabilityComposition("maintenance", "operations").slice(0, 3)).toEqual([
      "risk-metrics", "factory-map", "workflow-lifecycle",
    ]);
  });

  it("promotes runtime-critical context without changing the allowed block registry", () => {
    const result = resolveReliabilityComposition("executive", "reports", {
      hasCriticalRisk: true,
      hasDataQualityHold: true,
      hasOpenWorkflow: false,
      hasMaterialConstraint: true,
    });
    expect(result[0]).toBe("data-quality");
    expect(result[1]).toBe("production-exposure");
    expect(result).toContain("material-context");
    expect(new Set(result).size).toBe(result.length);
  });
});

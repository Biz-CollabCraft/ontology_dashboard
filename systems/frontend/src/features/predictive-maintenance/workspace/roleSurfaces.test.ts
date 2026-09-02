import { describe, expect, it } from "vitest";
import { defaultReliabilitySurface, reliabilitySurfaces } from "./roleSurfaces";

describe("semantic reliability surfaces", () => {
  it("promotes the visual factory status surface for operational roles and keeps it lower for executives", () => {
    expect(reliabilitySurfaces("engineering").map((item) => item.id)).toEqual([
      "factory-status", "monitoring", "assets", "sensor-features", "inspection", "maintenance-history", "field-notes",
    ]);
    expect(reliabilitySurfaces("operations").map((item) => item.id)).toEqual([
      "factory-status", "operations-status", "pending-decisions", "decision-case", "production-impact", "maintenance-approval", "backlog", "report-draft",
    ]);
    expect(reliabilitySurfaces("executive").map((item) => item.id)).toEqual([
      "executive-brief", "decision-bottleneck", "operational-risk", "executive-kpi", "executive-reports", "maintenance-effect", "roadmap", "factory-status",
    ]);
    expect(reliabilitySurfaces("maintenance").map((item) => item.id)).toEqual([
      "my-work", "work-targets", "field-status", "work-history",
    ]);
  });

  it("makes factory status the landing surface for manager and engineering", () => {
    expect(defaultReliabilitySurface("engineering").id).toBe("factory-status");
    expect(defaultReliabilitySurface("operations").id).toBe("factory-status");
    expect(defaultReliabilitySurface("executive").id).toBe("executive-brief");
    expect(defaultReliabilitySurface("maintenance").id).toBe("my-work");
  });

  it("keeps the previous role-composed v1 menu available in backup mode", () => {
    expect(defaultReliabilitySurface("engineering", true).id).toBe("monitoring");
    expect(defaultReliabilitySurface("operations", true).id).toBe("pending-decisions");
    expect(reliabilitySurfaces("executive", true).some((item) => item.id === "factory-status")).toBe(false);
  });
});

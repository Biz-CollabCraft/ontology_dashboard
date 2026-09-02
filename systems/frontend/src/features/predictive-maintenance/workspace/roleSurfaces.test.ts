import { describe, expect, it } from "vitest";
import { defaultReliabilitySurface, reliabilitySurfaces } from "./roleSurfaces";

describe("semantic reliability surfaces", () => {
  it("keeps exactly four primary menu items while changing their meaning by role", () => {
    expect(reliabilitySurfaces("engineering").map((item) => item.id)).toEqual([
      "monitoring", "assets", "inspection", "field-notes",
    ]);
    expect(reliabilitySurfaces("operations").map((item) => item.id)).toEqual([
      "pending-decisions", "operations-status", "production-impact", "report-draft",
    ]);
    expect(reliabilitySurfaces("executive").map((item) => item.id)).toEqual([
      "executive-brief", "decision-bottleneck", "operational-risk", "maintenance-effect",
    ]);
    for (const kind of ["engineering", "operations", "executive", "maintenance"] as const) {
      expect(reliabilitySurfaces(kind)).toHaveLength(4);
    }
  });

  it("always makes menu item 01 the landing surface", () => {
    expect(defaultReliabilitySurface("engineering").id).toBe("monitoring");
    expect(defaultReliabilitySurface("operations").id).toBe("pending-decisions");
    expect(defaultReliabilitySurface("executive").id).toBe("executive-brief");
    expect(defaultReliabilitySurface("maintenance").id).toBe("my-work");
  });
});

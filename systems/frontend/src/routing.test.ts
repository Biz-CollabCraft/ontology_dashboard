import { describe, expect, it } from "vitest";
import { isDevDashboardPath, week2MvpRedirectPath } from "./routing";

describe("Week 2 MVP route boundary", () => {
  it("keeps the canonical MVP route unchanged", () => {
    expect(week2MvpRedirectPath("/app/projects/demo/mvp", "fallback")).toBeNull();
  });

  it("redirects imported project workbenches to the canonical MVP route", () => {
    for (const path of [
      "/app/projects/demo",
      "/app/projects/demo/datasets",
      "/app/projects/demo/workspaces/main/agent",
      "/app/projects/demo/blueprint",
      "/app/projects/demo/blueprint-v2",
      "/app/projects/demo/blueprint-v4",
      "/app/projects/demo/blueprint-compare",
    ]) {
      expect(week2MvpRedirectPath(path, "fallback")).toBe("/app/projects/demo/mvp");
    }
  });

  it("uses the active project for non-project app paths", () => {
    expect(week2MvpRedirectPath("/app/analysis/analysis-1", "active-project")).toBe("/app/projects/active-project/mvp");
    expect(week2MvpRedirectPath("/app", "active-project")).toBe("/app/projects/active-project/mvp");
  });

  it("does not redirect public non-app routes", () => {
    expect(week2MvpRedirectPath("/team-share", "active-project")).toBeNull();
  });

  it("recognizes the public read-only development dashboard route", () => {
    expect(isDevDashboardPath("/dev_dashboard")).toBe(true);
    expect(isDevDashboardPath("/app/dev_dashboard")).toBe(false);
  });
});

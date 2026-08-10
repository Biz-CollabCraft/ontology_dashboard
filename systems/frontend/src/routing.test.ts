import { describe, expect, it } from "vitest";
import { week2MvpRedirectPath } from "./routing";

describe("Week 2 MVP route boundary", () => {
  it("keeps the canonical MVP route unchanged", () => {
    expect(week2MvpRedirectPath("/app/projects/demo/mvp", "fallback")).toBeNull();
  });

  it("redirects imported project workbenches to the canonical MVP route", () => {
    expect(week2MvpRedirectPath("/app/projects/demo/datasets", "fallback")).toBe("/app/projects/demo/mvp");
    expect(week2MvpRedirectPath("/app/projects/demo/workspaces/main/agent", "fallback")).toBe("/app/projects/demo/mvp");
    expect(week2MvpRedirectPath("/app/projects/demo/blueprint-v4", "fallback")).toBe("/app/projects/demo/mvp");
  });

  it("uses the active project for non-project app paths", () => {
    expect(week2MvpRedirectPath("/app/analysis/analysis-1", "active-project")).toBe("/app/projects/active-project/mvp");
    expect(week2MvpRedirectPath("/app", "active-project")).toBe("/app/projects/active-project/mvp");
  });

  it("does not redirect public non-app routes", () => {
    expect(week2MvpRedirectPath("/team-share", "active-project")).toBeNull();
  });
});

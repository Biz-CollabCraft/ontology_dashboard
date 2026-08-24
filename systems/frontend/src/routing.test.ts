import { describe, expect, it } from "vitest";
import { week2MvpRedirectPath } from "./routing";

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
    ]) {
      expect(week2MvpRedirectPath(path, "fallback")).toBe("/app/projects/demo/mvp");
    }
  });

  it("keeps published Blueprint showcase routes available", () => {
    expect(week2MvpRedirectPath("/app/projects/demo/blueprint-compare", "fallback")).toBeNull();
    expect(week2MvpRedirectPath("/app/projects/demo/blueprint-v4", "fallback")).toBeNull();
  });

  it("keeps only comparison iframe workbenches available with the embed marker", () => {
    for (const path of [
      "/app/projects/demo",
      "/app/projects/demo/blueprint",
      "/app/projects/demo/blueprint-v2",
      "/app/projects/demo/workspaces/main/ontology",
    ]) {
      expect(week2MvpRedirectPath(path, "fallback", "?comparison_embed=1")).toBeNull();
    }
    expect(
      week2MvpRedirectPath(
        "/app/projects/demo/workspaces/main/governance",
        "fallback",
        "?comparison_embed=1",
      ),
    ).toBe("/app/projects/demo/mvp");
  });

  it("uses the active project for non-project app paths", () => {
    expect(week2MvpRedirectPath("/app/analysis/analysis-1", "active-project")).toBe("/app/projects/active-project/mvp");
    expect(week2MvpRedirectPath("/app", "active-project")).toBe("/app/projects/active-project/mvp");
  });

  it("does not redirect public non-app routes", () => {
    expect(week2MvpRedirectPath("/team-share", "active-project")).toBeNull();
  });
});

import { describe, expect, it } from "vitest";
import { mvpNavigationItems } from "./MvpShell";

describe("MVP shell navigation", () => {
  it("keeps the system admin tab visible in workflow navigation", () => {
    expect(mvpNavigationItems("workflow").map((item) => item.id)).toEqual([
      "field_operator",
      "process_manager",
      "system",
    ]);
  });

  it("keeps the system admin side tab visible in classic navigation", () => {
    expect(mvpNavigationItems("classic").map((item) => item.id)).toContain("system");
  });
});

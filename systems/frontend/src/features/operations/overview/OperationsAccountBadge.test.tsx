// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { OperationsAccountBadge } from "./OperationsAccountBadge";
const setTheme = vi.fn();
vi.mock("../../../ui/foundry/displayPreferences", () => ({ useDisplayPreferences: () => ({ preferences: { theme: "light" }, setTheme }) }));
it("shows account and sends explicit light/dark selections", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  act(() => root.render(<OperationsAccountBadge displayName="김사용" title="보전팀"/>));
  const buttons = host.querySelectorAll("button");
  expect(host.textContent).toContain("김사용");
  expect(buttons[0].getAttribute("aria-pressed")).toBe("true");
  act(() => buttons[1].click());
  expect(setTheme).toHaveBeenLastCalledWith("dark");
  act(() => buttons[0].click());
  expect(setTheme).toHaveBeenLastCalledWith("light");
  act(() => root.unmount());
});

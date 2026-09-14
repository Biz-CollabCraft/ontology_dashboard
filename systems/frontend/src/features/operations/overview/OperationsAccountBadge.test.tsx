// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { OperationsAccountBadge } from "./OperationsAccountBadge";
const state = vi.hoisted(() => ({ theme: "light", setTheme: vi.fn() }));
vi.mock("../../../ui/foundry/displayPreferences", () => ({ useDisplayPreferences: () => ({ preferences: { theme: state.theme }, setTheme: state.setTheme }) }));
it("toggles a single sun/moon button in both directions", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  act(() => root.render(<OperationsAccountBadge displayName="김사용" title="보전팀"/>));
  const buttons = host.querySelectorAll("button");
  expect(host.textContent).toContain("김사용");
  expect(buttons).toHaveLength(1);
  expect(host.querySelector(".lucide-sun")).not.toBeNull();
  act(() => buttons[0].click());
  expect(state.setTheme).toHaveBeenLastCalledWith("dark");
  state.theme = "dark";
  act(() => root.render(<OperationsAccountBadge displayName="김사용" title="보전팀"/>));
  expect(host.querySelector(".lucide-moon")).not.toBeNull();
  expect(buttons[0].getAttribute("aria-label")).toBe("라이트 모드로 전환");
  act(() => buttons[0].click());
  expect(state.setTheme).toHaveBeenLastCalledWith("light");
  act(() => root.unmount());
});

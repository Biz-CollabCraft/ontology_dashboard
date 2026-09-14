// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { AccountInfoPopover } from "./AccountInfoPopover";
(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
let root: ReturnType<typeof createRoot>;
afterEach(() => { act(() => root?.unmount()); document.body.innerHTML = ""; });
it("renders outside the clipped card and clamps to viewport", () => {
  const host = document.createElement("div"); host.style.overflow = "hidden";
  host.innerHTML = '<div class="demo-account-info is-open"><button class="demo-account-info-trigger">정보</button></div>';
  document.body.append(host);
  const anchor = host.querySelector("button")!;
  anchor.getBoundingClientRect = () => ({left: 0, right: 20, top: 10, bottom: 40} as DOMRect);
  const mount = document.createElement("div"); host.append(mount); root = createRoot(mount);
  act(() => root.render(<AccountInfoPopover onClose={() => {}}>엔지니어</AccountInfoPopover>));
  const panel = document.querySelector('[role="note"]') as HTMLElement;
  expect(panel.parentElement).toBe(document.body);
  expect(panel.style.left).toBe("12px");
  expect(panel.getAttribute("popover")).toBe("manual");
  expect(host.contains(panel)).toBe(false);
});
it("closes on Escape or an outside click", () => {
  const host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  const close = vi.fn();
  act(() => root.render(<AccountInfoPopover onClose={close}>보전팀</AccountInfoPopover>));
  act(() => document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"})));
  act(() => document.body.dispatchEvent(new Event("pointerdown", {bubbles: true})));
  expect(close).toHaveBeenCalledTimes(2);
});

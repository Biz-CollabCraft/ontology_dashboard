import { useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function AccountInfoPopover({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const panel = ref.current!;
    const anchor = document.querySelector<HTMLElement>(".demo-account-info.is-open .demo-account-info-trigger");
    const place = () => {
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const width = Math.min(300, window.innerWidth - 24);
      panel.style.width = width + "px";
      panel.style.maxHeight = Math.max(80, window.innerHeight - 24) + "px";
      const height = panel.getBoundingClientRect().height;
      panel.style.left = Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)) + "px";
      panel.style.top = Math.max(12, Math.min(rect.top - height - 8 >= 12 ? rect.top - height - 8 : rect.bottom + 8, window.innerHeight - height - 12)) + "px";
    };
    panel.showPopover?.();
    place();
    const outside = (event: PointerEvent) => { if (!panel.contains(event.target as Node) && !anchor?.contains(event.target as Node)) onClose(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { onClose(); anchor?.focus(); } };
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [onClose]);
  return createPortal(<div ref={ref} popover="manual" role="note" aria-label="계정 상세 정보" style={{
    position: "fixed", inset: "auto", margin: 0, display: "block", zIndex: 2147483647,
    boxSizing: "border-box", padding: "14px", border: "1px solid #bdcbdc", borderRadius: 10,
    background: "#fff", color: "#17263e", boxShadow: "0 8px 28px #17263e33",
    overflow: "auto", overflowWrap: "anywhere", fontSize: 14, lineHeight: 1.5,
  }}>{children}</div>, document.body);
}

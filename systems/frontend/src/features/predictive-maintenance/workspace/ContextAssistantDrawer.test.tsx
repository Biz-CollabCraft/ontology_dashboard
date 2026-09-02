import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ContextAssistantDrawer } from "./ContextAssistantDrawer";
import {
  deterministicReliabilityAssistantAnswer,
  reliabilityAssistantPrompts,
  type ReliabilityAssistantContext,
} from "./assistantContext";

const selectedContext: ReliabilityAssistantContext = {
  assetId: "CNC-03",
  assetName: "CNC-03 spindle",
  eventId: "event-84",
  failureProbability: 0.84,
  currentLifecycleLabel: "점검 완료",
  nextLifecycleLabel: "정비안 검토",
  primaryActionLabel: "정비안 검토",
  evidenceCount: 3,
  evidenceSummary: "진동 상승과 온도 편차 근거가 연결되어 있습니다.",
  workOrderCount: 1,
  maintenanceState: "검토 대기",
  observedAt: "2026-09-02T09:00:00+09:00",
};

let container: HTMLDivElement;
let root: Root;

async function renderDrawer(props: Partial<React.ComponentProps<typeof ContextAssistantDrawer>> = {}) {
  await act(async () => {
    root.render(
      <ContextAssistantDrawer
        open
        onClose={() => undefined}
        context={selectedContext}
        onSubmit={() => undefined}
        {...props}
      />,
    );
  });
}

beforeEach(() => {
  (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
    .IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("ContextAssistantDrawer", () => {
  it("renders nothing in the closed state", async () => {
    await renderDrawer({ open: false });
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("renders selected asset operational context without inventing lifecycle state", async () => {
    await renderDrawer();
    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(container.textContent).toContain("CNC-03 spindle");
    expect(container.textContent).toContain("위험도84%");
    expect(container.textContent).toContain("현재 단계점검 완료");
    expect(container.textContent).toContain("다음 단계정비안 검토");
    expect(container.textContent).toContain("다음 행동정비안 검토");
    expect(container.textContent).toContain("Evidence3");
  });

  it("shows a no-selection context and disables free-form submission", async () => {
    await renderDrawer({ context: null });
    expect(container.textContent).toContain("선택 없음");
    expect(container.textContent).toContain("설비나 이벤트를 선택");
    expect(container.querySelector("textarea")?.hasAttribute("disabled")).toBe(true);
    expect(container.querySelector(".rw-context-assistant__prompts")).toBeNull();
  });

  it("only exposes suggested prompts backed by available context", () => {
    const prompts = reliabilityAssistantPrompts({
      assetId: "CNC-03",
      failureProbability: 0.84,
      currentLifecycleLabel: "점검 완료",
      evidenceCount: 2,
    });
    expect(prompts.map((prompt) => prompt.id)).toEqual(["priority", "evidence", "lifecycle"]);
    expect(prompts.map((prompt) => prompt.id)).not.toContain("next-action");
    expect(prompts.map((prompt) => prompt.id)).not.toContain("work-history");
    expect(prompts.map((prompt) => prompt.id)).not.toContain("post-maintenance");

    const postMaintenancePrompts = reliabilityAssistantPrompts({
      assetId: "CNC-03",
      postMaintenanceSummary: "정비 후 위험도 변화가 연결됨",
    });
    expect(postMaintenancePrompts.map((prompt) => prompt.id)).toEqual(["post-maintenance"]);
  });

  it("closes from the close button and Escape key", async () => {
    const onClose = vi.fn();
    await renderDrawer({ onClose });
    const closeButton = container.querySelector<HTMLButtonElement>('[aria-label="Reliability Assistant 닫기"]');
    expect(closeButton).not.toBeNull();
    await act(async () => closeButton?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(onClose).toHaveBeenCalledTimes(1);

    await act(async () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("renders an explicit empty-message state", async () => {
    await renderDrawer({ messages: [] });
    expect(container.textContent).toContain("아직 질문 없음");
    expect(container.textContent).toContain("선택된 운영 데이터");
  });

  it("states that the surface is context-only and cannot execute or approve work", async () => {
    await renderDrawer();
    expect(container.textContent).toContain("context-only preview");
    expect(container.textContent).toContain("승인·실행·변경하지 않습니다");
    expect(deterministicReliabilityAssistantAnswer(selectedContext)).toContain("규칙 기반");
    expect(deterministicReliabilityAssistantAnswer(selectedContext)).toContain("승인이나 실행 판단이 아닙니다");
  });
});

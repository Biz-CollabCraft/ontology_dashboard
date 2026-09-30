import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Briefing } from "./DecisionWorkspaceApplication";
import { getOperationsAgentReviewSummary } from "../../../api";
import { applyAssetDetailViewModel, composeEventDetail } from "../api/operationsAdapters";
import type { OperationsEvent } from "../api/operationsContracts";
import { decisionDetailFixture } from "../../../../e2e/fixtures/decision-detail.fixture";
vi.mock("../../../api", async importOriginal => ({
  ...await importOriginal<typeof import("../../../api")>(),
  getOperationsAgentReviewSummary: vi.fn(),
}));
const event = { eventId: "event-1", assetId: "asset-1", datasetVersionId: "dataset-1", criticality: null, confidence: "medium" } as OperationsEvent;
const detail = applyAssetDetailViewModel(composeEventDetail({ event, evidence: null, report: null, activity: null }), decisionDetailFixture("event-1", "asset-1", "dataset-1"));
const ready = (hash = "a".repeat(64)) => ({
  summary: { asset_id: "asset-1", mode: "llm", summary: "공구 상태를 현장에서 확인하세요.", evidence_gaps: [] },
  trace: { validation_errors: [], materialization: { status: "ready", source_sha256: hash } },
}) as never;
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  vi.useFakeTimers(); vi.mocked(getOperationsAgentReviewSummary).mockReset();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); });
describe("evidence-bound briefing lifecycle", () => {
  it("retries pending summaries even if the evidence snapshot does not change", async () => {
    vi.mocked(getOperationsAgentReviewSummary).mockResolvedValueOnce({ summary: null, trace: { validation_errors: [], materialization: { status: "pending" } } } as never).mockResolvedValue(ready());
    await act(async () => root.render(<Briefing detail={detail} projectId="p" />));
    expect(host.textContent).toContain("준비되지 않았습니다");
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(host.textContent).toContain("공구 상태를 현장에서 확인하세요.");
  });
  it("withholds a ready summary built from different evidence", async () => {
    vi.mocked(getOperationsAgentReviewSummary).mockResolvedValue(ready("b".repeat(64)));
    await act(async () => root.render(<Briefing detail={detail} projectId="p" />));
    expect(host.textContent).not.toContain("공구 상태를 현장에서 확인하세요.");
  });
  it("allows a slow request to finish before scheduling another read", async () => {
    vi.mocked(getOperationsAgentReviewSummary).mockImplementation(() => new Promise(resolve => setTimeout(() => resolve(ready()), 16000)));
    await act(async () => root.render(<Briefing detail={detail} projectId="p" />));
    await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
    expect(getOperationsAgentReviewSummary).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(host.textContent).toContain("공구 상태를 현장에서 확인하세요.");
    expect(getOperationsAgentReviewSummary).toHaveBeenCalledTimes(1);
  });
});

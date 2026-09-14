import { afterEach, describe, expect, it, vi } from "vitest";
import { loadDecisionWorkspaceDetail } from "../api/operationsApi";
import type { OperationsEvent } from "../api/operationsContracts";
import { decisionDetailFixture } from "../../../../e2e/fixtures/decision-detail.fixture";
const event = { eventId: "event-1", assetId: "asset-1", datasetVersionId: "dataset-1", criticality: null, confidence: "medium" } as OperationsEvent;
afterEach(() => vi.unstubAllGlobals());
describe("decision detail read boundary", () => {
  it("keeps missing canonical evidence blocked without misreporting a case mismatch", async () => {
    const view = decisionDetailFixture("event-1", "asset-1", "dataset-1");
    view.snapshot_basis.evidence_payload_reference = "";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok:true,json:async () => view}));
    await expect(loadDecisionWorkspaceDetail({projectId:"p",workspaceId:"w",event})).rejects.toThrow("원본 판단 근거가 없어");
  });
  it("uses exactly one detail endpoint without any report generation", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => decisionDetailFixture("event-1", "asset-1", "dataset-1") });
    vi.stubGlobal("fetch", fetcher);
    const result = await loadDecisionWorkspaceDetail({ projectId: "project-1", workspaceId: "workspace-1", event });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toContain("/detail-view?");
    expect(result.snapshotBasis?.eventId).toBe("event-1");
    expect(result.event.failureProbability).toBe(.82);
    expect(result.event.status).toBe("warning");
    expect(result.loadedSources.report).toBe(false);
  });
  it.each(["event", "asset", "artifact", "dataset"] as const)("rejects a mismatched %s identity before displaying evidence", async kind => {
    const view = decisionDetailFixture("event-1", "asset-1", "dataset-1");
    if (kind === "event") view.snapshot_basis.event_id = "other";
    if (kind === "asset") view.snapshot_basis.asset_id = "other";
    if (kind === "artifact") view.snapshot_basis.artifact_id = null;
    if (kind === "dataset") view.snapshot_basis.dataset_version = "other";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => view }));
    await expect(loadDecisionWorkspaceDetail({ projectId: "p", workspaceId: "w", event })).rejects.toThrow("일치하지");
  });
});

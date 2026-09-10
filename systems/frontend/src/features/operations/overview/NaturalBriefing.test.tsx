// @vitest-environment jsdom
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { NaturalBriefing } from "./NaturalBriefing";
import { getOperationsAgentReviewSummary, createOperationsAgentReviewSummary } from "../../../api";
import type { OperationsAgentReviewSummaryResponse } from "../api/operationsContracts";
vi.mock("../../../api", () => ({ getOperationsAgentReviewSummary: vi.fn(), createOperationsAgentReviewSummary: vi.fn(), getOperationsAgentReviewPacket: vi.fn() }));
const get = vi.mocked(getOperationsAgentReviewSummary), post = vi.mocked(createOperationsAgentReviewSummary);
function response(assetId = "A", quote = "**관측된 토크**와 점검 기록을 대조합니다. [[ref:1]]\n작업 시작 기록은 확인되지 않습니다."): OperationsAgentReviewSummaryResponse {
  return { summary: { asset_id: assetId, mode: "llm", summary: "공통 설명", source_refs: ["evidence:A"], limitations: [],
    role_summaries: [{ role: "process_engineer", quote }, { role: "maintenance_technician", quote: "보전 담당자의 자연어 설명" }, { role: "process_manager", quote: "생산 관리자의 자연어 설명" }] },
    trace: { fallback: false, materialization: { status: "ready", summary_key: "summary-key-A" } } } as unknown as OperationsAgentReviewSummaryResponse;
}
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks(); get.mockResolvedValue(response());
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function render(assetId = "A", canGenerate = true, role: "process_engineer" | "maintenance_technician" | "process_manager" = "process_engineer", revision = "1") {
  await act(async () => root.render(<StrictMode><NaturalBriefing projectId="project" workspaceId="manufacturing-demo" assetId={assetId} eventId={"event-" + assetId} role={role} canGenerate={canGenerate} revision={revision}/></StrictMode>));
}
it("reads the selected event without generating and shows safe prose with collapsible references", async () => {
  await render();
  expect(get).toHaveBeenLastCalledWith(expect.objectContaining({ assetId: "A", eventId: "event-A", projectId: "project" }));
  expect(post).not.toHaveBeenCalled();
  expect(host.querySelector("strong")?.textContent).toBe("AI 브리핑");
  expect(host.querySelector(".natural-briefing-line strong")?.textContent).toBe("관측된 토크");
  expect(host.querySelector("details summary")?.textContent).toBe("근거");
  expect(host.textContent).not.toContain("[[ref:");
  expect(host.querySelector("ul")).toBeNull();
});
it.each(["maintenance_technician", "process_manager"] as const)("selects %s natural prose", async role => {
  await render("A", true, role);
  expect(host.textContent).toContain(role === "process_manager" ? "생산 관리자의 자연어 설명" : "보전 담당자의 자연어 설명");
  expect(host.textContent).not.toContain("관측된 토크");
});
it("does not expose generation without permission", async () => {
  await render("A", false); expect(host.querySelector("button")).toBeNull(); expect(post).not.toHaveBeenCalled();
});
it.each(["fallback", "stale", "wrong-asset"])("does not show %s prose", async kind => {
  const value = response(kind === "wrong-asset" ? "B" : "A");
  if (kind === "fallback") value.trace.fallback = true;
  if (kind === "stale") value.trace.materialization!.status = "stale";
  get.mockResolvedValue(value); await render(); expect(host.querySelector(".natural-briefing-line")).toBeNull();
});
it("discards late responses after selection changes", async () => {
  let finish!: (value: OperationsAgentReviewSummaryResponse) => void;
  get.mockImplementation(input => input.assetId === "A" ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(response("B", "B 설비 설명")));
  await render("A"); await render("B"); await act(async () => finish(response()));
  expect(host.textContent).toContain("B 설비 설명"); expect(host.textContent).not.toContain("관측된 토크");
});
it("hides old prose immediately when the same event's work status changes", async () => {
  await render(); get.mockImplementation(() => new Promise(() => {})); await render("A", true, "process_engineer", "2");
  expect(host.textContent).not.toContain("관측된 토크"); expect(host.textContent).toContain("조회 중");
});
it("rereads the validated stored result after explicit generation", async () => {
  await render(); post.mockResolvedValue(response()); get.mockResolvedValue(response("A", "새로 저장된 설명"));
  await act(async () => host.querySelector<HTMLButtonElement>("button")!.click());
  expect(post).toHaveBeenCalledTimes(1); expect(host.textContent).toContain("새로 저장된 설명");
});
it("shows a recoverable failure without retaining old prose", async () => {
  await render(); post.mockRejectedValue(new Error("provider unavailable"));
  await act(async () => host.querySelector<HTMLButtonElement>("button")!.click());
  expect(host.textContent).toContain("생성하지 못했습니다"); expect(host.textContent).not.toContain("관측된 토크");
  expect(host.querySelector<HTMLButtonElement>("button")!.disabled).toBe(false);
});

it("uses server replay responses without product API calls and withdraws rejected prose", async () => {
 const props={projectId:"project",workspaceId:"manufacturing-demo",assetId:"A",eventId:"event-A",role:"process_engineer" as const};
 await act(async()=>root.render(<NaturalBriefing {...props} providedResponse={response()}/>));
 expect(get).not.toHaveBeenCalled();expect(post).not.toHaveBeenCalled();
 expect(host.textContent).toContain("관측된 토크");expect(host.textContent).not.toContain("evidence:A");
 const rejected={summary:null,trace:{fallback:true,materialization:{status:"fallback"}}} as unknown as OperationsAgentReviewSummaryResponse;
 await act(async()=>root.render(<NaturalBriefing {...props} providedResponse={rejected}/>));
 expect(host.querySelector('.natural-briefing-line')).toBeNull();
 expect(host.textContent).toContain("검증을 통과하지 못한 응답");
});

it("keeps in-flight generation bound while FILE observations advance", async () => {
 let finish!: (value: OperationsAgentReviewSummaryResponse) => void;
 post.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
 const props = {projectId:"project",workspaceId:"manufacturing-demo",assetId:"A",role:"process_engineer" as const,canGenerate:true};
 await act(async()=>root.render(<NaturalBriefing {...props} eventId="FILE#original#obs1" datasetVersionId="wrong-new-run" observedAt="2026-09-09T01:00:00Z"/>));
 expect(get).toHaveBeenLastCalledWith(expect.objectContaining({datasetVersionId:"original"}));
 await act(async()=>host.querySelector<HTMLButtonElement>('button')!.click());
 const signal=post.mock.calls[0][0].signal;
 await act(async()=>root.render(<NaturalBriefing {...props} eventId="FILE#original#obs2" datasetVersionId="original" observedAt="2026-09-09T01:10:00Z"/>));
 expect(signal?.aborted).toBe(false);
 await act(async()=>finish(response()));
 expect(get).toHaveBeenLastCalledWith(expect.objectContaining({eventId:"FILE#original#obs1",datasetVersionId:"original"}));
 expect(host.querySelector('time')?.dateTime).toBe('2026-09-09T01:00:00Z');
 expect(host.textContent).toContain('생성 기준 관측을 유지');
});

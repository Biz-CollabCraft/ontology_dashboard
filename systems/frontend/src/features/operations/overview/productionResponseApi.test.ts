// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { respondInspectionCoordination } from "../../../api";
afterEach(() => {vi.unstubAllGlobals();document.cookie="ontology_csrf=; Max-Age=0; path=/";});
it.each(["confirmed","changes_requested"] as const)("sends %s to the scoped response API with session, CSRF and retry key", async decision => {
 document.cookie="ontology_csrf=test-csrf; path=/";
 const saved={work_order_id:"work/1",asset_id:"CNC-1",status:decision};
 const fetcher=vi.fn().mockResolvedValue({ok:true,status:200,json:async()=>saved});vi.stubGlobal("fetch",fetcher);
 const payload={request_id:"request-1",decision,scheduled_window:"내일 14시",production_response:"검토 결과"};
 expect(await respondInspectionCoordination({projectId:"project",workspaceId:"workspace",workOrderId:"work/1",payload,idempotencyKey:"retry-key-001"})).toEqual(saved);
 const [url,init]=fetcher.mock.calls[0];
 expect(url).toContain("/api/projects/project/workspaces/workspace/maintenance/inspection-work-orders/work%2F1/production-response");
 expect(init.method).toBe("POST");expect(init.credentials).toBe("include");
 expect(init.headers.get("X-CSRF-Token")).toBe("test-csrf");
 expect(init.headers.get("Idempotency-Key")).toBe("retry-key-001");
 expect(JSON.parse(init.body)).toEqual(payload);
});
it("propagates rejected/stale response instead of reporting success", async () => {
 vi.stubGlobal("fetch",vi.fn().mockResolvedValue({ok:false,status:409,json:async()=>({error:{code:"invalid_transition",message:"stale request"}})}));
 await expect(respondInspectionCoordination({projectId:"p",workspaceId:"w",workOrderId:"o",payload:{request_id:"r",decision:"confirmed",scheduled_window:"내일",production_response:"확인"},idempotencyKey:"retry-001"})).rejects.toMatchObject({status:409});
});

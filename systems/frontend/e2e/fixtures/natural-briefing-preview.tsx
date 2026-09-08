import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { EngineerFactoryStandalone } from "../../src/features/operations/overview/EngineerFactoryStandalone";
import { RoleFactoryStandalone } from "../../src/features/operations/overview/RoleFactoryStandalone";
import "../../src/app.css";
import "../../src/features/operations/operations.css";
import preview from "./natural-briefing-preview.json";
const injected = (window as any).__BRIEFING_FIXTURE__;
const fixture = injected || preview;
// This adapter is confined to this test-only preview entry, never the app entry.
if (!injected) {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, options) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
    if (!url.pathname.startsWith("/api/") && !url.pathname.startsWith("/health")) return originalFetch(input, options);
    const method = options?.method || (input instanceof Request ? input.method : "GET");
    if (method !== "GET") return Response.json({detail:"고정 입력 미리보기에서는 생성·저장을 실행하지 않습니다."}, {status:405});
    let data: unknown = {items:[]};
    if (url.pathname.endsWith("/agent-review-summary")) data = {summary:{...preview.reference,mode:"llm",schema_version:"agent-review-summary-v1.1",asset_id:preview.model.assets[0].assetId,source_refs:[],limitations:[]},trace:{fallback:false,materialization:{status:"ready"}}};
    else if (url.pathname.endsWith("/detail-view")) data = preview.detail;
    else if (url.pathname.endsWith("/inspection-coordinations")) data = {items:[preview.coordination]};
    else if (url.pathname.endsWith("/lineage")) data = {event_id:preview.model.assets[0].eventId,work_orders:[],inspection_results:[],recommendations:[],cost_analyses:[]};
    else if (url.pathname.startsWith("/health")) data = {status:"ok"};
    return Response.json(data);
  };
}
function Preview() {
  const [selected, setSelected] = useState(fixture.model.assets[0].assetId);
  const persona = new URLSearchParams(location.search).get("persona") || "engineering";
  const common = { projectId: "manufacturing-demo-project", workspaceId: "manufacturing-demo", model: fixture.model,
    workOrders: fixture.orders, workOrderError: false, currentUserId: "review-user", canGenerateBrief: Boolean(injected),
    currentUser: { displayName: "화면 검토", title: persona === "engineering" ? "엔지니어" : persona === "maintenance" ? "보전팀" : "생산 관리자" }, onRefresh() {}, onLogout() {} };
  const screen = persona === "engineering" ? <EngineerFactoryStandalone {...common} selectedAssetId={selected} maintenanceDirectives={fixture.orders} onSelectAsset={setSelected}/>
    : <RoleFactoryStandalone {...common} persona={persona as "maintenance" | "production"}/>;
  return <><nav aria-label="미리보기 역할" style={{display:"flex",alignItems:"center",gap:16,padding:"12px 20px",background:"#fff",borderBottom:"1px solid #cbd5e1",fontSize:13}}><strong>AI 브리핑 배치 미리보기</strong><span>고정 입력 · 실제 생성·저장 없음</span>{[["engineering","엔지니어"],["maintenance","보전팀"],["production","생산 관리자"]].map(([id,label])=><a key={id} href={"?persona="+id} aria-current={id===persona?"page":undefined}>{label}</a>)}</nav>{screen}</>;
}
if (injected) createRoot(document.getElementById("root")!).render(<Preview/>);
else location.replace("/demo-briefing.html?view=" + (new URLSearchParams(location.search).get("persona") || "engineering"));

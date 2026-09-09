import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import { NaturalBriefing } from "../../src/features/operations/overview/NaturalBriefing";
function Preview() {
  const [asset, setAsset] = useState("A");
  const [revision, setRevision] = useState(0);
  return <main style={{maxWidth:760,margin:"40px auto",padding:16,fontFamily:"sans-serif"}}>
    <h1>설비 판단 근거</h1>
    <nav><button onClick={()=>setAsset(asset === "A" ? "B" : "A")}>다른 사건 선택</button><button onClick={()=>setRevision(revision+1)}>작업 상태 갱신</button></nav>
    <NaturalBriefing projectId="project" workspaceId="manufacturing-demo" assetId={asset} eventId={`event-${asset}`} observedAt="2026-09-09T00:00:00Z" role="process_engineer" revision={String(revision)}/>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Preview/>);

import { useEffect, useState } from "react";
import { useSystemOperationsNavigate, useSystemOperationsPathname } from "./SystemOperationsNavigation";
import { useAuth } from "../auth/AuthContext";
import { createImpactAnalysis, executeImpactAnalysis, getImpactAnalysis, listImpactAnalyses } from "./impactAnalysisApi";
import { canCreateImpactAnalysis, canExecuteSystemRebuild } from "./permissions";
import type { SystemImpactAnalysis } from "./types";

function Detail({ id }: { id: string }) {
  const navigate = useSystemOperationsNavigate();
  const { user } = useAuth();
  const [analysis, setAnalysis] = useState<SystemImpactAnalysis | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  useEffect(() => { getImpactAnalysis(id).then(setAnalysis).catch(error => setMessage(error instanceof Error ? error.message : "영향 분석 조회 실패")); }, [id]);
  if (!analysis) return <main className="ops-page"><p>{message || "영향 분석을 불러오는 중입니다."}</p></main>;
  const execute = async () => {
    try {
      const job = await executeImpactAnalysis(id, { expected_snapshot_sha256: analysis.snapshot_sha256, selected_action_ids: selected, training_selection: null, reason: "approved downstream rebuild" });
      navigate(`/system/operations/jobs/${job.job_id}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "실행 Job 생성 실패"); }
  };
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/impact")}>← 영향 분석 목록</button><header><p className="ops-eyebrow">DOWNSTREAM IMPACT SNAPSHOT</p><h1>{analysis.mapping_id} · {analysis.mapping_version}</h1><p>{analysis.status} · snapshot {analysis.snapshot_sha256.slice(0, 12)}…</p></header>
    <section className="ops-panel"><h2>실행 가능 작업</h2>{analysis.recommended_actions.length === 0 ? <p>실행 가능한 작업이 없습니다.</p> : analysis.recommended_actions.map(action => <label key={action.action_id}><input type="checkbox" checked={selected.includes(action.action_id)} onChange={event => setSelected(current => event.target.checked ? [...current, action.action_id] : current.filter(value => value !== action.action_id))} /> {action.stage} · {action.action_id}</label>)}</section>
    <section className="ops-panel"><h2>차단 작업</h2>{analysis.blocked_actions.length === 0 ? <p>차단된 작업이 없습니다.</p> : analysis.blocked_actions.map(action => <p key={action.action_id}><strong>{action.stage}</strong> · 누락: {action.missing_parameters.join(", ")}</p>)}</section>
    {canExecuteSystemRebuild(user?.permissions) && <button disabled={selected.length === 0} onClick={() => void execute()}>선택 작업 실행</button>}{message && <p>{message}</p>}
  </main>;
}

export function ImpactAnalysesPage() {
  const navigate = useSystemOperationsNavigate();
  const pathname = useSystemOperationsPathname();
  const { user } = useAuth();
  const match = pathname.match(/^\/system\/operations\/impact\/([^/]+)$/);
  const initialQuery = new URLSearchParams(window.location.search);
  const [sourceType] = useState(initialQuery.get("asset_type") ?? "");
  const [items, setItems] = useState<SystemImpactAnalysis[]>([]);
  const [mappingId, setMappingId] = useState(initialQuery.get("asset_id") ?? ""); const [version, setVersion] = useState(initialQuery.get("version") ?? "");
  const [checksum, setChecksum] = useState(initialQuery.get("sha256") ?? ""); const [jobId, setJobId] = useState(""); const [message, setMessage] = useState("");
  useEffect(() => { if (!match) void listImpactAnalyses().then(value => setItems(value.items)); }, [Boolean(match)]);
  if (match) return <Detail id={decodeURIComponent(match[1])} />;
  const create = async () => { try { const input = sourceType ? { source_asset_type: sourceType, source_asset_id: mappingId, source_version: version, source_sha256: checksum, source_job_id: null, include_stages: ["preprocessing", "feature", "training"] } : { mapping_id: mappingId, mapping_version: version, mapping_sha256: checksum, rebuild_job_id: jobId, include_stages: ["preprocessing", "feature", "training"] }; const analysis = await createImpactAnalysis(input); navigate(`/system/operations/impact/${analysis.analysis_id}`); } catch (error) { setMessage(error instanceof Error ? error.message : "영향 분석 생성 실패"); } };
  return <main className="ops-page"><header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>Downstream 영향 분석</h1><p>Mapping 또는 관리 계약 변경이 후속 학습 파이프라인에 미치는 영향을 snapshot으로 고정합니다.</p></header>
    {canCreateImpactAnalysis(user?.permissions) && <section className="ops-panel"><h2>새 분석 · {sourceType || "static_mapping"}</h2><div className="ops-form-grid"><label>Asset ID<input value={mappingId} onChange={e=>setMappingId(e.target.value)} /></label><label>Version<input value={version} onChange={e=>setVersion(e.target.value)} /></label><label>SHA-256<input value={checksum} onChange={e=>setChecksum(e.target.value.trim())} /></label>{!sourceType && <label>완료된 Rebuild Job ID<input value={jobId} onChange={e=>setJobId(e.target.value)} /></label>}</div><button onClick={() => void create()}>영향 분석 생성</button>{message && <p>{message}</p>}</section>}
    <section className="ops-panel"><h2>분석 목록</h2>{items.map(item => <button className="ops-draft-row" key={item.analysis_id} onClick={() => navigate(`/system/operations/impact/${item.analysis_id}`)}><strong>{item.mapping_id} · {item.mapping_version}</strong><span>{item.status} · {item.snapshot_sha256.slice(0, 12)}…</span></button>)}</section>
  </main>;
}

import { useEffect, useState } from "react";
import { useSystemOperationsNavigate, useSystemOperationsPathname } from "./SystemOperationsNavigation";
import { useAuth } from "../auth/AuthContext";
import { cancelPipelineJob, createRebuildJob, getPipelineJob, listPipelineJobs } from "./pipelineJobApi";
import { canCancelSystemJob, canCreateSystemJob } from "./permissions";
import type { SystemPipelineJob } from "./types";

const shaPattern = /^[a-f0-9]{64}$/;

function JobDetail({ jobId }: { jobId: string }) {
  const navigate = useSystemOperationsNavigate();
  const { user } = useAuth();
  const [job, setJob] = useState<SystemPipelineJob | null>(null);
  const [message, setMessage] = useState("");
  const load = () => getPipelineJob(jobId).then(setJob).catch(reason => setMessage(reason instanceof Error ? reason.message : "Job 조회 실패"));
  useEffect(() => { void load(); const timer = window.setInterval(() => void load(), 3000); return () => window.clearInterval(timer); }, [jobId]);
  if (!job) return <main className="ops-page"><p>{message || "Job을 불러오는 중입니다."}</p></main>;
  const cancellable = ["queued", "running", "checkpointed"].includes(job.status);
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/jobs")}>← Job 목록</button><header><p className="ops-eyebrow">MAPPING REBUILD JOB</p><h1>{job.mapping_id} · {job.mapping_version}</h1><p>{job.status} · {job.source_uri}</p></header>
    <section className="ops-summary-grid"><article><span>상태</span><strong>{job.status}</strong></article><article><span>활성화</span><strong>{job.activate_on_success ? "성공 후" : "안 함"}</strong></article><article><span>시작</span><strong>{job.started_at ? new Date(job.started_at).toLocaleString() : "대기"}</strong></article><article><span>완료</span><strong>{job.completed_at ? new Date(job.completed_at).toLocaleString() : "—"}</strong></article></section>
    {cancellable && canCancelSystemJob(user?.permissions) && <button onClick={() => void cancelPipelineJob(jobId).then(setJob)}>취소 요청</button>}
    {job.error && <section className="ops-panel"><h2>오류</h2><p>{job.error.code} · {job.error.message}</p></section>}
    {job.steps && <section className="ops-panel"><h2>단계별 실행</h2>{job.steps.map(step => <article key={step.step_id}><strong>{step.sequence + 1}. {step.stage}</strong> · {step.status}{step.error && <p>{step.error.code} · {step.error.message}</p>}</article>)}</section>}
    <section className="ops-panel"><h2>진행 및 결과</h2><pre>{JSON.stringify({ progress: job.progress, checkpoint: job.checkpoint, result: job.result }, null, 2)}</pre></section>
  </main>;
}

export function PipelineJobsPage() {
  const navigate = useSystemOperationsNavigate();
  const pathname = useSystemOperationsPathname();
  const { user } = useAuth();
  const match = pathname.match(/^\/system\/operations\/jobs\/([^/]+)$/);
  const [jobs, setJobs] = useState<SystemPipelineJob[]>([]);
  const [mappingId, setMappingId] = useState(""); const [version, setVersion] = useState("");
  const [checksum, setChecksum] = useState(""); const [sourceUri, setSourceUri] = useState("");
  const [reason, setReason] = useState(""); const [activate, setActivate] = useState(true); const [message, setMessage] = useState("");
  const load = () => listPipelineJobs().then(value => setJobs(value.items));
  useEffect(() => { if (!match) void load(); }, [Boolean(match)]);
  if (match) return <JobDetail jobId={decodeURIComponent(match[1])} />;
  const create = async () => {
    if (!shaPattern.test(checksum) || checksum === "0".repeat(64)) { setMessage("유효한 Mapping SHA-256을 입력하세요."); return; }
    try {
      const job = await createRebuildJob({ job_type: "mapping_rebuild", mapping_id: mappingId, mapping_version: version, mapping_sha256: checksum, source_uri: sourceUri, replay_scope: "full_source", activate_on_success: activate, idempotency_key: `mapping-rebuild:${sourceUri}:${checksum}`, reason });
      navigate(`/system/operations/jobs/${encodeURIComponent(job.job_id)}`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Job 생성 실패"); }
  };
  return <main className="ops-page"><header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>Rebuild / Replay Job</h1><p>발행된 Mapping으로 원본 gen_data를 재처리합니다. 기존 Dataset은 변경하지 않습니다.</p></header>
    {canCreateSystemJob(user?.permissions) && <section className="ops-panel"><h2>새 Replay</h2><div className="ops-form-grid"><label>Mapping ID<input placeholder="예: mapping-milling-v1" value={mappingId} onChange={e=>setMappingId(e.target.value)} /></label><label>Mapping version<input placeholder="예: 1.0.0" value={version} onChange={e=>setVersion(e.target.value)} /></label><label>Mapping SHA-256<input placeholder="64자리 SHA-256" value={checksum} onChange={e=>setChecksum(e.target.value.trim())} /></label><label>Source URI<input placeholder="예: gen_data/canonical/..." value={sourceUri} onChange={e=>setSourceUri(e.target.value)} /></label><label>실행 사유<input placeholder="재처리 사유 입력" value={reason} onChange={e=>setReason(e.target.value)} /></label><label className="ops-checkbox-field"><input type="checkbox" checked={activate} onChange={e=>setActivate(e.target.checked)} /><span>성공 후 자동 활성화</span></label></div><button onClick={() => void create()}>Rebuild Job 생성</button>{message && <p>{message}</p>}</section>}
    <section className="ops-panel"><h2>Job 목록</h2>{jobs.length === 0 ? <div className="ops-table-empty">실행된 Job이 없습니다.</div> : jobs.map(job=><button className="ops-draft-row" key={job.job_id} onClick={()=>navigate(`/system/operations/jobs/${job.job_id}`)}><strong>{job.mapping_id} · {job.mapping_version}</strong><span>{job.status} · {job.source_uri}</span></button>)}</section>
  </main>;
}

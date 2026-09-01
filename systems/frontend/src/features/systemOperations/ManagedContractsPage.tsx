import { useEffect, useState } from "react";
import { navigate, usePathname } from "../../routing";
import { useAuth } from "../auth/AuthContext";
import { createManagedContractDraft, diffManagedContractDraft, getManagedContractDraft, listManagedContractDrafts, publishManagedContractDraft, updateManagedContractDraft, validateManagedContractDraft } from "./managedContractApi";
import { canCreateManagedContract, canPublishManagedContract, canValidateManagedContract } from "./permissions";
import type { ManagedContractAssetType, ManagedContractDiff, ManagedContractDraft } from "./types";

const TYPES: ManagedContractAssetType[] = ["preprocessing_plan", "feature_schema", "label_schema", "history_requirement", "training_config"];

function StructuredFields({ draft, payload, setPayload }: { draft: ManagedContractDraft; payload: Record<string, unknown>; setPayload: (value: Record<string, unknown>) => void }) {
  const field = (name: string, label: string, type = "text") => <label>{label}<input type={type} value={String(payload[name] ?? "")} onChange={event => setPayload({ ...payload, [name]: type === "number" ? Number(event.target.value) : event.target.value })} /></label>;
  if (draft.asset_type === "preprocessing_plan") return <div className="ops-form-grid">{field("dataset_id", "Dataset ID")}{field("dataset_version", "Dataset version")}{field("id_column", "ID column")}{field("time_column", "Time column")}{field("duplicate_policy", "Duplicate policy")}{field("missing_value_policy", "Missing-value policy")}</div>;
  if (draft.asset_type === "feature_schema") return <div className="ops-form-grid">{field("feature_executor_version", "Feature executor version")}<label>Feature 수<input readOnly value={Array.isArray(payload.features) ? payload.features.length : 0} /></label></div>;
  if (draft.asset_type === "label_schema") return <div className="ops-form-grid">{field("prediction_task", "Prediction task")}{field("prediction_horizon_hours", "Horizon hours", "number")}{field("positive_interval", "Positive interval")}{field("active_failure_policy", "Active failure policy")}</div>;
  if (draft.asset_type === "history_requirement") return <div className="ops-form-grid">{field("minimum_history_rows", "Minimum rows", "number")}{field("maximum_lookback_hours", "Maximum lookback hours", "number")}{field("sampling_interval_seconds", "Sampling interval seconds", "number")}{field("sufficiency_policy", "Sufficiency policy")}{field("missing_history_policy", "Missing-history policy")}</div>;
  return <div className="ops-form-grid">{field("split_strategy", "Split strategy")}{field("primary_metric", "Primary metric")}{field("random_seed", "Random seed", "number")}</div>;
}

function DraftDetail({ id }: { id: string }) {
  const { user } = useAuth(); const [draft, setDraft] = useState<ManagedContractDraft | null>(null);
  const [payload, setPayload] = useState<Record<string, unknown>>({}); const [jsonText, setJsonText] = useState("");
  const [diff, setDiff] = useState<ManagedContractDiff | null>(null); const [message, setMessage] = useState("");
  const load = () => getManagedContractDraft(id).then(value => { setDraft(value); setPayload(value.payload); setJsonText(JSON.stringify(value.payload, null, 2)); });
  useEffect(() => { void load(); }, [id]);
  useEffect(() => { setJsonText(JSON.stringify(payload, null, 2)); }, [payload]);
  if (!draft) return <main className="ops-page"><p>{message || "Draft를 불러오는 중입니다."}</p></main>;
  const editable = !["published", "publishing"].includes(draft.status);
  const save = async () => { try { const parsed = JSON.parse(jsonText); const value = await updateManagedContractDraft(id, { expected_revision: draft.revision, payload: parsed, reason: "system operator edit" }); setDraft(value); setPayload(value.payload); setMessage("저장했습니다. 변경 후에는 다시 검증해야 합니다."); } catch (error) { setMessage(error instanceof Error ? error.message : "저장 실패"); } };
  const validate = async () => { try { const result = await validateManagedContractDraft(id); setMessage(result.validation_status === "valid" ? "검증을 통과했습니다." : `검증 실패: ${JSON.stringify(result.errors)}`); await load(); } catch (error) { setMessage(error instanceof Error ? error.message : "검증 실패"); } };
  const publish = async () => { try { await publishManagedContractDraft(id, { expected_revision: draft.revision, expected_payload_sha256: draft.payload_sha256, reason: "approved managed contract" }); setMessage("신규 불변 버전을 발행했습니다. 필요한 경우 영향 분석을 실행하세요."); await load(); } catch (error) { setMessage(error instanceof Error ? error.message : "발행 실패"); } };
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/contracts")}>← 계약 Draft 목록</button><header><p className="ops-eyebrow">MANAGED CONTRACT VERSION</p><h1>{draft.asset_id} · {draft.target_version}</h1><p>{draft.asset_type} · revision {draft.revision} · {draft.status}</p></header>
    <section className="ops-panel"><h2>주요 계약 필드</h2><StructuredFields draft={draft} payload={payload} setPayload={setPayload} /></section>
    <section className="ops-panel"><h2>전체 Payload 보조 편집</h2><textarea rows={18} value={jsonText} disabled={!editable} onChange={event => setJsonText(event.target.value)} />{editable && canCreateManagedContract(user?.permissions) && <button onClick={() => void save()}>Draft 저장</button>}</section>
    <section className="ops-panel"><h2>검증·Diff·발행</h2>{canValidateManagedContract(user?.permissions) && <><button onClick={() => void validate()}>현재 revision 검증</button><button onClick={() => void diffManagedContractDraft(id).then(setDiff)}>기준 버전과 Diff</button></>}{canPublishManagedContract(user?.permissions) && <button disabled={draft.validation_status !== "valid" || draft.validated_revision !== draft.revision} onClick={() => void publish()}>불변 버전 발행</button>}{message && <p>{message}</p>}{diff && <pre>{JSON.stringify(diff, null, 2)}</pre>}</section>
    {draft.status === "published" && <button onClick={() => navigate(`/system/operations/impact?asset_type=${draft.asset_type}&asset_id=${draft.asset_id}&version=${draft.target_version}&sha256=${draft.published_sha256 ?? draft.payload_sha256}`)}>Downstream 영향 분석</button>}
  </main>;
}

export function ManagedContractsPage() {
  const { user } = useAuth(); const pathname = usePathname(); const match = pathname.match(/^\/system\/operations\/contracts\/drafts\/([^/]+)$/);
  const [items, setItems] = useState<ManagedContractDraft[]>([]); const [assetType, setAssetType] = useState<ManagedContractAssetType>("preprocessing_plan");
  const [assetId, setAssetId] = useState(""); const [target, setTarget] = useState(""); const [base, setBase] = useState(""); const [message, setMessage] = useState("");
  useEffect(() => { if (!match) void listManagedContractDrafts().then(value => setItems(value.items)); }, [Boolean(match)]);
  if (match) return <DraftDetail id={decodeURIComponent(match[1])} />;
  const create = async () => { try { const value = await createManagedContractDraft({ asset_type: assetType, asset_id: assetId, target_version: target, base_version: base || null }); navigate(`/system/operations/contracts/drafts/${value.draft_id}`); } catch (error) { setMessage(error instanceof Error ? error.message : "Draft 생성 실패"); } };
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/assets")}>← 운영 자산</button><header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>계약·설정 자산</h1><p>기존 발행본을 수정하지 않고 신규 버전 Draft로 관리합니다.</p></header>
    {canCreateManagedContract(user?.permissions) && <section className="ops-panel"><h2>새 버전 Draft</h2><div className="ops-form-grid"><label>자산 유형<select value={assetType} onChange={event => setAssetType(event.target.value as ManagedContractAssetType)}>{TYPES.map(value => <option key={value}>{value}</option>)}</select></label><label>Asset ID<input value={assetId} onChange={event => setAssetId(event.target.value)} /></label><label>Target version<input value={target} onChange={event => setTarget(event.target.value)} /></label><label>Base version (선택)<input value={base} onChange={event => setBase(event.target.value)} /></label></div><button onClick={() => void create()}>Draft 생성</button>{message && <p>{message}</p>}</section>}
    <section className="ops-panel"><h2>Draft 목록</h2>{items.map(item => <button className="ops-draft-row" key={item.draft_id} onClick={() => navigate(`/system/operations/contracts/drafts/${item.draft_id}`)}><strong>{item.asset_type} · {item.asset_id} · {item.target_version}</strong><span>revision {item.revision} · {item.status} · {item.validation_status}</span></button>)}</section>
  </main>;
}

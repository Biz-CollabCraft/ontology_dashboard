import { useEffect, useState } from "react";
import { navigate, usePathname } from "../../routing";
import { createMappingDraft, getMappingDraft, getMappingDraftDiff, listMappingDrafts, publishMappingDraft, updateMappingDraft, validateMappingDraft } from "./mappingDraftApi";
import type { MappingDraft, MappingDraftDiff, MappingFieldDefinition } from "./types";
import { useAuth } from "../auth/AuthContext";
import { canCreateSystemAssetVersion, canPublishSystemAsset, canValidateSystemAsset } from "./permissions";

const EMPTY_FIELD: MappingFieldDefinition = { source_field: "", target_field: "", source_type: "float", target_type: "float", required: true, transform: "to_float" };

function DraftEditor({ id }: { id: string }) {
  const { user } = useAuth();
  const permissions = user?.permissions ?? [];
  const [draft, setDraft] = useState<MappingDraft | null>(null);
  const [payload, setPayload] = useState<Record<string, unknown>>({});
  const [diff, setDiff] = useState<MappingDraftDiff | null>(null);
  const [message, setMessage] = useState("");
  const load = async () => { const value = await getMappingDraft(id); setDraft(value); setPayload(value.payload); };
  useEffect(() => { void load(); }, [id]);
  if (!draft) return <div className="ops-state">Draft를 불러오는 중입니다.</div>;
  const fields = (payload.field_mappings as MappingFieldDefinition[] | undefined) ?? [];
  const setField = (index: number, key: keyof MappingFieldDefinition, value: string | boolean) => {
    const next = fields.map((field, position) => position === index ? ({ ...field, [key]: value } as MappingFieldDefinition) : field);
    setPayload({ ...payload, field_mappings: next });
  };
  const execute = async (action: () => Promise<unknown>, success: string) => { setMessage(""); try { await action(); setMessage(success); await load(); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "요청 실패"); } };
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/mappings/drafts")}>← Draft 목록</button><header><p className="ops-eyebrow">MAPPING VERSION DRAFT</p><h1>{draft.mapping_id} · {draft.target_version}</h1><p>revision {draft.revision} · {draft.status} · validation {draft.validation_status}</p></header>
    <section className="ops-panel"><h2>Mapping 정의</h2><div className="ops-form-grid"><label>Source schema version<input value={String(payload.source_schema_version ?? "")} onChange={(e) => setPayload({ ...payload, source_schema_version: e.target.value })} /></label><label>Source fingerprint<input value={String(payload.source_schema_fingerprint ?? "")} onChange={(e) => setPayload({ ...payload, source_schema_fingerprint: e.target.value })} /></label><label>Description<input value={String(payload.description ?? "")} onChange={(e) => setPayload({ ...payload, description: e.target.value })} /></label></div></section>
    <section className="ops-panel"><h2>Field Mapping</h2><div className="ops-table-wrap"><table><thead><tr><th>Source</th><th>Target</th><th>Source type</th><th>Target type</th><th>Transform</th><th>Required</th><th></th></tr></thead><tbody>{fields.map((field, index) => <tr key={index}><td><input value={field.source_field} onChange={(e) => setField(index,"source_field",e.target.value)} /></td><td><input value={field.target_field} onChange={(e) => setField(index,"target_field",e.target.value)} /></td><td><select value={field.source_type} onChange={(e) => setField(index,"source_type",e.target.value)}>{["float","int","string","bool","number"].map(v=><option key={v}>{v}</option>)}</select></td><td><select value={field.target_type} onChange={(e) => setField(index,"target_type",e.target.value)}>{["float","int","string","bool","datetime"].map(v=><option key={v}>{v}</option>)}</select></td><td><select value={field.transform} onChange={(e) => setField(index,"transform",e.target.value)}>{["identity","to_float","to_int","to_string","scale_10x","kelvin_to_celsius","celsius_to_kelvin"].map(v=><option key={v}>{v}</option>)}</select></td><td><input type="checkbox" checked={field.required} onChange={(e) => setField(index,"required",e.target.checked)} /></td><td><button onClick={() => setPayload({ ...payload, field_mappings: fields.filter((_, p) => p !== index) })}>제거</button></td></tr>)}</tbody></table></div><button onClick={() => setPayload({ ...payload, field_mappings: [...fields, { ...EMPTY_FIELD }] })}>행 추가</button></section>
    <section className="ops-panel ops-actions">{canCreateSystemAssetVersion(permissions) && <button onClick={() => void execute(() => updateMappingDraft(id,draft.revision,payload),"저장했습니다.")}>Draft 저장</button>}{canValidateSystemAsset(permissions) && <button onClick={() => void execute(() => validateMappingDraft(id),"검증했습니다.")}>검증</button>}<button onClick={() => void getMappingDraftDiff(id).then(setDiff)}>Diff</button>{canPublishSystemAsset(permissions) && <button disabled={draft.status !== "validated" || draft.validated_revision !== draft.revision} onClick={() => void execute(() => publishMappingDraft(id,draft.revision),"불변 버전으로 발행했습니다.")}>Publish</button>}{message && <span>{message}</span>}</section>
    {draft.validation_errors.length > 0 && <section className="ops-panel"><h2>검증 오류</h2><pre>{JSON.stringify(draft.validation_errors,null,2)}</pre></section>}
    {diff && <section className="ops-panel"><h2>Diff · +{diff.summary.added} / -{diff.summary.removed} / ~{diff.summary.changed}</h2><pre>{JSON.stringify(diff.changes,null,2)}</pre></section>}
  </main>;
}

export function MappingDraftsPage() {
  const { user } = useAuth();
  const canCreate = canCreateSystemAssetVersion(user?.permissions);
  const pathname = usePathname(); const match = pathname.match(/^\/system\/operations\/mappings\/drafts\/([^/]+)$/);
  const [drafts,setDrafts] = useState<MappingDraft[]>([]); const [mappingId,setMappingId]=useState(""); const [target,setTarget]=useState(""); const [base,setBase]=useState(""); const [message,setMessage]=useState("");
  useEffect(() => { if (!match) void listMappingDrafts().then(value => setDrafts(value.items)); }, [Boolean(match)]);
  if (match) return <DraftEditor id={decodeURIComponent(match[1])} />;
  const create = async () => { try { const value=await createMappingDraft({mapping_id:mappingId,target_version:target,base_version:base||null}); navigate(`/system/operations/mappings/drafts/${value.draft_id}`); } catch(reason) { setMessage(reason instanceof Error?reason.message:"Draft 생성 실패"); } };
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/assets")}>← 운영 자산</button><header><p className="ops-eyebrow">STATIC MAPPING MANAGEMENT</p><h1>Mapping Draft</h1><p>기존 발행본을 변경하지 않고 신규 버전을 작성합니다.</p></header>{canCreate && <section className="ops-panel"><h2>새 버전</h2><div className="ops-form-grid"><label>Mapping ID<input value={mappingId} onChange={e=>setMappingId(e.target.value)} /></label><label>Target version<input value={target} onChange={e=>setTarget(e.target.value)} /></label><label>Base version (선택)<input value={base} onChange={e=>setBase(e.target.value)} /></label></div><button onClick={() => void create()}>Draft 생성</button>{message&&<p>{message}</p>}</section>}<section className="ops-panel"><h2>Draft 목록</h2>{drafts.map(d=><button className="ops-draft-row" key={d.draft_id} onClick={()=>navigate(`/system/operations/mappings/drafts/${d.draft_id}`)}><strong>{d.mapping_id} · {d.target_version}</strong><span>revision {d.revision} · {d.status}</span></button>)}</section></main>;
}

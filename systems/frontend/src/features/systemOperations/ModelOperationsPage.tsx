import { useEffect, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { activateActiveModelSet, clearOperationalModelSelection, listActiveModelSetRevisions, listOperationalModels, rollbackActiveModelSet, selectOperationalModel, validateActiveModelSet, type ModelOperationItem } from "./modelOperationsApi";
import { canActivateSystemModels, canRollbackSystemModels, canSelectSystemModels } from "./permissions";

export function ModelOperationsPage() {
  const { user } = useAuth();
  const [models, setModels] = useState<ModelOperationItem[]>([]);
  const [revisions, setRevisions] = useState<Record<string, unknown>[]>([]);
  const [message, setMessage] = useState("");
  const [reason, setReason] = useState("운영 모델 구성 변경");
  const load = () => Promise.all([listOperationalModels(), listActiveModelSetRevisions()]).then(([m, r]) => { setModels(m.items); setRevisions(r.items); });
  useEffect(() => { void load().catch(error => setMessage(error instanceof Error ? error.message : "모델 운영 상태 조회 실패")); }, []);
  const choose = async (model: ModelOperationItem, version: string) => {
    const checksum = window.prompt("Model Artifact manifest SHA-256을 입력하세요.");
    if (!checksum) return;
    try { await selectOperationalModel(model.model_id, { model_version: version, model_artifact_manifest_sha256: checksum.trim(), reason }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "모델 선택 실패"); }
  };
  const clear = async (model: ModelOperationItem) => {
    if (!model.selection?.selection_id) return;
    try { await clearOperationalModelSelection(model.model_id, { expected_selection_id: model.selection.selection_id, reason }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "선택 해제 실패"); }
  };
  const setPayload = () => ({ model_set_id: "pdm-production", model_set_version: new Date().toISOString(), models: models.map(model => ({ model_id: model.model_id, model_version: null, required: true })), reason });
  const activate = async () => { try { await validateActiveModelSet(setPayload()); await activateActiveModelSet(setPayload()); await load(); } catch (error) { setMessage(error instanceof Error ? error.message : "Active Model Set 활성화 실패"); } };
  const rollback = async (revisionId: string) => { try { await rollbackActiveModelSet(revisionId, reason); await load(); } catch (error) { setMessage(error instanceof Error ? error.message : "Rollback 실패"); } };
  return <main className="ops-page"><header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>Model 운영 선택</h1><p>자동 최신 버전, 운영 선택 버전과 실제 Runtime 활성 버전을 분리해 관리합니다.</p></header>
    <section className="ops-panel"><label className="ops-single-field"><strong>변경 사유</strong><input placeholder="운영 모델 구성 변경" value={reason} onChange={event => setReason(event.target.value)} /></label>{message && <p>{message}</p>}</section>
    <section className="ops-panel"><h2>모델별 버전</h2><div className="ops-table-wrap"><table><thead><tr><th>모델</th><th>latest</th><th>selected</th><th>active</th><th>상태</th><th>작업</th></tr></thead><tbody>{models.length === 0 ? <tr><td colSpan={6} className="ops-table-empty">등록된 운영 모델이 없습니다.</td></tr> : models.map(model => <tr key={model.model_id}><td><strong>{model.model_id}</strong></td><td>{model.latest_version ?? "—"}</td><td>{model.selected_version ?? "—"}</td><td>{model.active_version ?? "—"}</td><td>{model.selection_pending_activation ? "선택 후 미활성" : "일치"}</td><td>{canSelectSystemModels(user?.permissions) && <div className="ops-actions">{model.versions.map(version => <button key={version} onClick={() => void choose(model, version)}>{version} 선택</button>)}{model.selected_version && <button onClick={() => void clear(model)}>선택 해제</button>}</div>}</td></tr>)}</tbody></table></div></section>
    <section className="ops-panel"><h2>Active Model Set</h2>{canActivateSystemModels(user?.permissions) && <button disabled={!models.length} onClick={() => void activate()}>검증 후 활성화</button>}<p>선택만으로 Runtime은 변경되지 않으며 활성화 성공 후 다음 실행부터 적용됩니다.</p></section>
    <section className="ops-panel"><h2>Revision / Rollback</h2>{revisions.length === 0 ? <div className="ops-table-empty">기록된 Revision이 없습니다.</div> : revisions.map(revision => <article key={String(revision.revision_id)}><strong>{String(revision.model_set_version)}</strong> · {String(revision.status)} {canRollbackSystemModels(user?.permissions) && <button onClick={() => void rollback(String(revision.revision_id))}>Rollback</button>}</article>)}</section>
  </main>;
}

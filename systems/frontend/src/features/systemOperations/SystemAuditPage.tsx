import { useEffect, useState } from "react";
import { navigate } from "../../routing";
import { createLogExport, getRecoveryGuide, listAudit, type AuditEvent } from "./auditApi";

export function SystemAuditPage() {
  const [items, setItems] = useState<AuditEvent[]>([]); const [outcome, setOutcome] = useState(""); const [errorCode, setErrorCode] = useState(""); const [message, setMessage] = useState(""); const [guide, setGuide] = useState<string[]>([]);
  const load = () => { const query = new URLSearchParams(); if (outcome) query.set("outcome", outcome); listAudit(query.toString()).then(r => setItems(r.items)).catch(e => setMessage(e.message)); };
  useEffect(load, [outcome]);
  const showGuide = (code: string) => { setErrorCode(code); getRecoveryGuide(code).then(r => setGuide(r.operator_actions)).catch(e => setMessage(e.message)); };
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/assets")}>← 운영 자산</button><header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>감사 기록</h1><p>운영 자산과 모델 변경 행위를 append-only 기록으로 조회합니다.</p><button onClick={() => createLogExport("audit", outcome ? { outcome } : {}).then(r => setMessage(`Export 완료: ${String(r.logical_uri)}`)).catch(e => setMessage(e.message))}>현재 조건 JSONL Export</button></header>
  <section className="ops-panel"><div className="ops-filters"><select aria-label="결과" value={outcome} onChange={e => setOutcome(e.target.value)}><option value="">모든 결과</option><option value="succeeded">succeeded</option><option value="failed">failed</option><option value="denied">denied</option></select></div>{message && <p>{message}</p>}<div className="ops-table-wrap"><table><thead><tr><th>시각</th><th>작업</th><th>자원</th><th>행위자</th><th>결과</th><th>오류</th></tr></thead><tbody>{items.map(item => <tr key={item.audit_id}><td>{new Date(item.occurred_at).toLocaleString()}</td><td>{item.action}</td><td>{item.resource_type}:{item.resource_id}</td><td>{item.actor_id}</td><td>{item.outcome}</td><td>{item.error_code ? <button onClick={() => showGuide(item.error_code!)}>{item.error_code}</button> : "—"}</td></tr>)}</tbody></table></div></section>
  {errorCode && <section className="ops-panel"><h2>{errorCode} 복구 가이드</h2><ol>{guide.map(action => <li key={action}>{action}</li>)}</ol></section>}</main>;
}

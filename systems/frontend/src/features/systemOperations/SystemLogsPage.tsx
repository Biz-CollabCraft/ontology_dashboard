import { useEffect, useState } from "react";
import { navigate } from "../../routing";
import { createLogExport, listOperationalLogs, type OperationalLog } from "./auditApi";

export function SystemLogsPage() {
  const [items, setItems] = useState<OperationalLog[]>([]); const [severity, setSeverity] = useState(""); const [message, setMessage] = useState("");
  useEffect(() => { const query = new URLSearchParams(); if (severity) query.set("severity", severity); listOperationalLogs(query.toString()).then(r => setItems(r.items)).catch(e => setMessage(e.message)); }, [severity]);
  return <main className="ops-page"><button className="ops-back" onClick={() => navigate("/system/operations/assets")}>← 운영 자산</button><header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>운영 로그</h1><p>서비스·도메인·오류 코드와 상관관계 ID를 기준으로 구조화 로그를 조회합니다.</p><button onClick={() => createLogExport("operational_logs", severity ? { severity } : {}).then(r => setMessage(`Export 완료: ${String(r.logical_uri)}`)).catch(e => setMessage(e.message))}>현재 조건 JSONL Export</button></header><section className="ops-panel"><div className="ops-filters"><select aria-label="심각도" value={severity} onChange={e => setSeverity(e.target.value)}><option value="">모든 심각도</option>{["DEBUG","INFO","WARNING","ERROR","CRITICAL"].map(v => <option key={v}>{v}</option>)}</select></div>{message && <p>{message}</p>}<div className="ops-table-wrap"><table><thead><tr><th>시각</th><th>서비스</th><th>도메인</th><th>심각도</th><th>메시지</th><th>오류</th></tr></thead><tbody>{items.map(item => <tr key={item.log_id}><td>{new Date(item.occurred_at).toLocaleString()}</td><td>{item.service}</td><td>{item.domain}</td><td>{item.severity}</td><td>{item.message}</td><td>{item.error_code ?? "—"}</td></tr>)}</tbody></table></div></section></main>;
}

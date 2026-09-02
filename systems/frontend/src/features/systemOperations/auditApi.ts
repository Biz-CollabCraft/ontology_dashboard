import { API_BASE, ApiError } from "../../api";

export type AuditEvent = { audit_id: string; occurred_at: string; actor_id: string; action: string; resource_type: string; resource_id: string; outcome: string; request_id: string; error_code?: string | null };
export type OperationalLog = { log_id: string; occurred_at: string; service: string; domain: string; severity: string; message: string; error_code?: string | null; request_id?: string | null };

function csrfToken() { const prefix = `${encodeURIComponent("ontology_csrf") }=`; return document.cookie.split(";").map(v => v.trim()).find(v => v.startsWith(prefix))?.slice(prefix.length) ?? null; }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers); if (init.body) headers.set("Content-Type", "application/json");
  if ((init.method ?? "GET") !== "GET") { const csrf = csrfToken(); if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf)); }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", payload?.error?.message ?? "운영 기록 요청에 실패했습니다.");
  return payload as T;
}
export function listAudit(params = "") { return request<{items: AuditEvent[]; count: number}>(`/api/system/audit${params ? `?${params}` : ""}`); }
export function listOperationalLogs(params = "") { return request<{items: OperationalLog[]; count: number}>(`/api/system/logs${params ? `?${params}` : ""}`); }
export function createLogExport(source: "audit" | "operational_logs", filters: Record<string, string>) { return request<Record<string, unknown>>("/api/system/log-exports", { method: "POST", body: JSON.stringify({ format: "jsonl", source, filters, limit: 10000 }) }); }
export function getRecoveryGuide(code: string) { return request<{title: string; operator_actions: string[]; automatic_retry_allowed: boolean}>(`/api/system/recovery-guides/${encodeURIComponent(code)}`); }

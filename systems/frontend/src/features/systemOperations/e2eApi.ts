import { API_BASE, ApiError } from "../../api";
export type E2ERun = { run_id: string; status: string; batch_id?: string; asset_ids: string[]; started_at: string; completed_at?: string; error_code?: string };
export type E2EEvent = { timeline_event_id: string; occurred_at: string; stage: string; status: string; service: string; domain: string; asset_id?: string; error_code?: string };
export type AnomalyAlert = { alert_id: string; event_id: string; asset_id: string; observed_at: string; severity: string; status: string; headline: string; product_result_id: string };
async function get<T>(path: string): Promise<T> { const response = await fetch(`${API_BASE}${path}`, { credentials: "include" }); const payload = await response.json().catch(() => ({})); if (!response.ok) throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", "E2E 운영 정보를 불러오지 못했습니다."); return payload as T; }
export const listE2ERuns = () => get<{items: E2ERun[]}>("/api/system/e2e-runs");
export const getE2ETimeline = (runId: string) => get<{run: E2ERun; events: E2EEvent[]}>(`/api/system/e2e-runs/${encodeURIComponent(runId)}/timeline`);
export const listAnomalyAlerts = () => get<{items: AnomalyAlert[]}>("/api/system/alerts");

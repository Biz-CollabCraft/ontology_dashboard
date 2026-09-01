import { API_BASE, ApiError } from "../../api";
import type { SystemPipelineJob } from "./types";

function cookieValue(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  return document.cookie.split(";").map(value => value.trim()).find(value => value.startsWith(prefix))?.slice(prefix.length) ?? null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const method = (init.method ?? "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = cookieValue("ontology_csrf");
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", payload?.error?.message ?? "Pipeline Job 요청에 실패했습니다.");
  return payload as T;
}

export function listPipelineJobs(status = "") { return request<{ items: SystemPipelineJob[] }>(`/api/system/jobs${status ? `?status_filter=${encodeURIComponent(status)}` : ""}`); }
export function getPipelineJob(id: string) { return request<SystemPipelineJob>(`/api/system/jobs/${encodeURIComponent(id)}`); }
export function createRebuildJob(input: Record<string, unknown>) { return request<SystemPipelineJob>("/api/system/jobs/rebuild", { method: "POST", body: JSON.stringify(input) }); }
export function cancelPipelineJob(id: string) { return request<SystemPipelineJob>(`/api/system/jobs/${encodeURIComponent(id)}/cancel`, { method: "POST" }); }

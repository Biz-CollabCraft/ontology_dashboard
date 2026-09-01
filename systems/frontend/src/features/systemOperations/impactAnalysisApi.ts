import { API_BASE, ApiError } from "../../api";
import type { SystemImpactAnalysis, SystemPipelineJob } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body) headers.set("Content-Type", "application/json");
  if (["POST", "PUT", "PATCH", "DELETE"].includes((init?.method ?? "GET").toUpperCase())) {
    const prefix = `${encodeURIComponent("ontology_csrf")}=`;
    const csrf = document.cookie.split(";").map(value => value.trim()).find(value => value.startsWith(prefix))?.slice(prefix.length);
    if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", payload?.error?.message ?? "영향 분석 요청에 실패했습니다.");
  return payload as T;
}

export function listImpactAnalyses() { return request<{ items: SystemImpactAnalysis[] }>("/api/system/impact-analyses"); }
export function getImpactAnalysis(id: string) { return request<SystemImpactAnalysis>(`/api/system/impact-analyses/${encodeURIComponent(id)}`); }
export function createImpactAnalysis(input: Record<string, unknown>) { return request<SystemImpactAnalysis>("/api/system/impact-analyses", { method: "POST", body: JSON.stringify(input) }); }
export function executeImpactAnalysis(id: string, input: Record<string, unknown>) { return request<SystemPipelineJob>(`/api/system/impact-analyses/${encodeURIComponent(id)}/execute`, { method: "POST", body: JSON.stringify(input) }); }

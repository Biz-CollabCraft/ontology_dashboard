import { API_BASE, ApiError } from "../../api";
import type { MappingDraft, MappingDraftDiff } from "./types";

function cookieValue(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  for (const item of document.cookie.split(";")) {
    const value = item.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const method = (init.method ?? "GET").toUpperCase();
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = cookieValue("ontology_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", payload?.error?.message ?? "Mapping 요청에 실패했습니다.");
  return payload as T;
}

export function listMappingDrafts() { return request<{ items: MappingDraft[] }>("/api/system/mapping-drafts"); }
export function getMappingDraft(id: string) { return request<MappingDraft>(`/api/system/mapping-drafts/${encodeURIComponent(id)}`); }
export function createMappingDraft(input: { mapping_id: string; target_version: string; base_version?: string | null }) {
  return request<MappingDraft>("/api/system/mapping-drafts", { method: "POST", body: JSON.stringify(input) });
}
export function updateMappingDraft(id: string, revision: number, payload: Record<string, unknown>) {
  return request<MappingDraft>(`/api/system/mapping-drafts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify({ expected_revision: revision, payload }) });
}
export function validateMappingDraft(id: string) { return request<MappingDraft>(`/api/system/mapping-drafts/${encodeURIComponent(id)}/validate`, { method: "POST" }); }
export function publishMappingDraft(id: string, revision: number) { return request<{ draft: MappingDraft; registry_reconciled: boolean }>(`/api/system/mapping-drafts/${encodeURIComponent(id)}/publish`, { method: "POST", body: JSON.stringify({ expected_revision: revision }) }); }
export function getMappingDraftDiff(id: string) { return request<MappingDraftDiff>(`/api/system/mapping-drafts/${encodeURIComponent(id)}/diff`); }

import { API_BASE, ApiError } from "../../api";

export type ModelOperationItem = {
  model_id: string;
  versions: string[];
  latest_version?: string | null;
  selected_version?: string | null;
  active_version?: string | null;
  selection_pending_activation: boolean;
  selection?: { selection_id: string; model_artifact_manifest_sha256: string } | null;
};

function csrfToken() {
  const prefix = `${encodeURIComponent("ontology_csrf")}=`;
  return document.cookie.split(";").map(value => value.trim()).find(value => value.startsWith(prefix))?.slice(prefix.length) ?? null;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  if (["POST", "PUT", "PATCH", "DELETE"].includes((init.method ?? "GET").toUpperCase())) {
    const csrf = csrfToken(); if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers, credentials: "include" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", payload?.error?.message ?? "모델 운영 요청에 실패했습니다.");
  return payload as T;
}

export function listOperationalModels() { return request<{ items: ModelOperationItem[] }>("/api/system/models"); }
export function selectOperationalModel(modelId: string, input: Record<string, unknown>) { return request<Record<string, unknown>>(`/api/system/models/${encodeURIComponent(modelId)}/select`, { method: "POST", body: JSON.stringify(input) }); }
export function clearOperationalModelSelection(modelId: string, input: Record<string, unknown>) { return request<Record<string, unknown>>(`/api/system/models/${encodeURIComponent(modelId)}/clear-selection`, { method: "POST", body: JSON.stringify(input) }); }
export function getActiveModelSet() { return request<Record<string, unknown>>("/api/system/model-sets/active"); }
export function listActiveModelSetRevisions() { return request<{ items: Record<string, unknown>[] }>("/api/system/model-sets/revisions"); }
export function validateActiveModelSet(input: Record<string, unknown>) { return request<Record<string, unknown>>("/api/system/model-sets/validate", { method: "POST", body: JSON.stringify(input) }); }
export function activateActiveModelSet(input: Record<string, unknown>) { return request<Record<string, unknown>>("/api/system/model-sets/activate", { method: "POST", body: JSON.stringify(input) }); }
export function rollbackActiveModelSet(revisionId: string, reason: string) { return request<Record<string, unknown>>("/api/system/model-sets/rollback", { method: "POST", body: JSON.stringify({ revision_id: revisionId, reason }) }); }

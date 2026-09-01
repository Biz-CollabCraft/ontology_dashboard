import { API_BASE, ApiError } from "../../api";
import type { ManagedContractDiff, ManagedContractDraft, ManagedContractValidation } from "./types";

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
  if (!response.ok) throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", payload?.error?.message ?? "계약 자산 요청에 실패했습니다.");
  return payload as T;
}

export function listManagedContractDrafts() { return request<{ items: ManagedContractDraft[] }>("/api/system/contracts/drafts"); }
export function getManagedContractDraft(id: string) { return request<ManagedContractDraft>(`/api/system/contracts/drafts/${encodeURIComponent(id)}`); }
export function createManagedContractDraft(input: Record<string, unknown>) { return request<ManagedContractDraft>("/api/system/contracts/drafts", { method: "POST", body: JSON.stringify(input) }); }
export function updateManagedContractDraft(id: string, input: Record<string, unknown>) { return request<ManagedContractDraft>(`/api/system/contracts/drafts/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(input) }); }
export function validateManagedContractDraft(id: string) { return request<ManagedContractValidation>(`/api/system/contracts/drafts/${encodeURIComponent(id)}/validate`, { method: "POST" }); }
export function diffManagedContractDraft(id: string) { return request<ManagedContractDiff>(`/api/system/contracts/drafts/${encodeURIComponent(id)}/diff`); }
export function publishManagedContractDraft(id: string, input: Record<string, unknown>) { return request<Record<string, unknown>>(`/api/system/contracts/drafts/${encodeURIComponent(id)}/publish`, { method: "POST", body: JSON.stringify(input) }); }

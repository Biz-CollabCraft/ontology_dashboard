import { API_BASE, ApiError } from "../../api";
import type { LatestReconciliation, OperationalAssetDetail, OperationalAssetListResponse } from "./types";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(response.status, payload?.error?.code ?? "api_request_failed", payload?.error?.message ?? `API request failed: ${response.status}`);
  }
  return payload as T;
}

export interface AssetFilters {
  assetType?: string;
  registryStatus?: string;
  validationStatus?: string;
  active?: boolean;
  search?: string;
  limit?: number;
  offset?: number;
}

export function listOperationalAssets(filters: AssetFilters = {}) {
  const query = new URLSearchParams();
  if (filters.assetType) query.set("asset_type", filters.assetType);
  if (filters.registryStatus) query.set("registry_status", filters.registryStatus);
  if (filters.validationStatus) query.set("validation_status", filters.validationStatus);
  if (filters.active !== undefined) query.set("active", String(filters.active));
  if (filters.search) query.set("search", filters.search);
  query.set("limit", String(filters.limit ?? 50));
  query.set("offset", String(filters.offset ?? 0));
  return getJson<OperationalAssetListResponse>(`/api/system/assets?${query}`);
}

export function getOperationalAsset(assetId: string) {
  return getJson<OperationalAssetDetail>(`/api/system/assets/${encodeURIComponent(assetId)}`);
}

export function getLatestReconciliation() {
  return getJson<LatestReconciliation | null>("/api/system/assets/reconciliation/latest");
}

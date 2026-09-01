import { useEffect, useMemo, useState } from "react";
import { ApiError } from "../../api";
import { navigate, usePathname } from "../../routing";
import { getLatestReconciliation, getOperationalAsset, listOperationalAssets } from "./operationalAssetsApi";
import type { LatestReconciliation, OperationalAssetDetail, OperationalAssetSummary } from "./types";
import "./systemOperations.css";
import { MappingDraftsPage } from "./MappingDraftsPage";
import { useAuth } from "../auth/AuthContext";
import { canCreateSystemAssetVersion } from "./permissions";
import { PipelineJobsPage } from "./PipelineJobsPage";
import { ImpactAnalysesPage } from "./ImpactAnalysesPage";

const ASSET_TYPES = ["static_mapping", "preprocessing_plan", "feature_schema", "label_schema", "history_requirement", "training_config", "feature_dataset_bundle", "model_artifact", "active_model_set", "protocol_contract", "dataset_contract"];
const REGISTRY_STATUSES = ["verified", "discovered", "invalid", "conflicted", "drifted", "unavailable"];

function shortHash(value?: string) { return value ? `${value.slice(0, 12)}…` : "—"; }
function when(value?: string) { return value ? new Date(value).toLocaleString() : "—"; }

function Status({ value }: { value?: string }) {
  return <span className={`ops-status ops-status--${value ?? "unknown"}`}>{value ?? "unknown"}</span>;
}

function Detail({ assetId }: { assetId: string }) {
  const [asset, setAsset] = useState<OperationalAssetDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getOperationalAsset(assetId).then(setAsset).catch((reason) => setError(reason instanceof Error ? reason.message : "자산을 불러오지 못했습니다.")); }, [assetId]);
  if (error) return <main className="ops-page"><button onClick={() => navigate("/system/operations/assets")}>← 목록</button><div className="ops-state ops-state--error">{error}</div></main>;
  if (!asset) return <main className="ops-page"><div className="ops-state">자산 정보를 불러오는 중입니다.</div></main>;
  return <main className="ops-page">
    <button className="ops-back" onClick={() => navigate("/system/operations/assets")}>← 운영 자산 목록</button>
    <header><p className="ops-eyebrow">SYSTEM OPERATIONS · READ ONLY</p><h1>{asset.asset_key}</h1><p>{asset.asset_type} · {asset.source_system}</p></header>
    <section className="ops-summary-grid">
      <article><span>대표 버전</span><strong>{asset.current_version ?? "—"}</strong></article>
      <article><span>Registry</span><Status value={asset.registry_status} /></article>
      <article><span>Schema</span><strong>{asset.schema_id ?? "—"}</strong></article>
      <article><span>마지막 확인</span><strong>{when(asset.last_seen_at)}</strong></article>
    </section>
    <section className="ops-panel"><h2>버전 이력</h2><div className="ops-table-wrap"><table><thead><tr><th>버전</th><th>활성</th><th>Registry</th><th>검증</th><th>Checksum</th><th>논리 URI</th><th>마지막 확인</th></tr></thead><tbody>
      {asset.versions.map((version) => <tr key={version.id}><td>{version.version}</td><td>{version.is_active ? "ACTIVE" : "—"}</td><td><Status value={version.registry_status} /></td><td><Status value={version.validation_status} /></td><td><code title={version.sha256}>{shortHash(version.sha256)}</code></td><td><code>{version.logical_uri}</code></td><td>{when(version.last_seen_at)}</td></tr>)}
    </tbody></table></div></section>
    <section className="ops-panel"><h2>의존성</h2>{asset.versions.flatMap((version) => version.dependencies ?? []).length === 0 ? <p>선언된 의존성이 없습니다.</p> : <ul>{asset.versions.flatMap((version) => version.dependencies ?? []).map((dep, index) => <li key={`${dep.asset_type}-${dep.asset_key}-${dep.version}-${index}`}><strong>{dep.asset_type}</strong> · {dep.asset_key} · {dep.version} <Status value={dep.resolution_status ?? "unresolved"} /></li>)}</ul>}</section>
  </main>;
}

export function SystemOperationsApp() {
  const pathname = usePathname();
  return pathname.startsWith("/system/operations/mappings/drafts")
    ? <MappingDraftsPage />
    : pathname.startsWith("/system/operations/impact")
    ? <ImpactAnalysesPage />
    : pathname.startsWith("/system/operations/jobs")
    ? <PipelineJobsPage />
    : <OperationalAssetsApp />;
}

function OperationalAssetsApp() {
  const pathname = usePathname();
  const { user } = useAuth();
  const detailMatch = pathname.match(/^\/system\/operations\/assets\/([^/]+)$/);
  const [items, setItems] = useState<OperationalAssetSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [reconciliation, setReconciliation] = useState<LatestReconciliation | null>(null);
  const [assetType, setAssetType] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const filters = useMemo(() => ({ assetType, registryStatus: status, search, active: activeOnly ? true : undefined }), [activeOnly, assetType, search, status]);
  useEffect(() => {
    if (detailMatch) return;
    setLoading(true); setError("");
    Promise.all([listOperationalAssets(filters), getLatestReconciliation()])
      .then(([assets, latest]) => { setItems(assets.items); setTotal(assets.total); setReconciliation(latest); })
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : "운영 자산을 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, [assetType, status, search, activeOnly, Boolean(detailMatch)]);
  if (detailMatch) return <Detail assetId={decodeURIComponent(detailMatch[1])} />;
  return <main className="ops-page">
    <header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>운영 자산</h1><p>Generator가 실제 사용하는 Mapping, Schema, Dataset Bundle과 Model Artifact의 검증 상태를 감독합니다.</p>{canCreateSystemAssetVersion(user?.permissions) && <button onClick={() => navigate("/system/operations/mappings/drafts")}>Mapping 새 버전 관리</button>}<button onClick={() => navigate("/system/operations/jobs")}>Rebuild Job</button><button onClick={() => navigate("/system/operations/impact")}>Downstream 영향 분석</button></header>
    <section className="ops-summary-grid"><article><span>등록 자산</span><strong>{total}</strong></article><article><span>최근 동기화</span><strong>{when(reconciliation?.completed_at)}</strong></article><article><span>검증됨</span><strong>{reconciliation?.verified_count ?? "—"}</strong></article><article><span>문제 발견</span><strong>{reconciliation ? reconciliation.invalid_count + reconciliation.conflicted_count : "—"}</strong></article></section>
    <section className="ops-panel"><div className="ops-filters"><input aria-label="자산 검색" placeholder="자산 이름 또는 버전 검색" value={search} onChange={(event) => setSearch(event.target.value)} /><select aria-label="자산 유형" value={assetType} onChange={(event) => setAssetType(event.target.value)}><option value="">모든 유형</option>{ASSET_TYPES.map((value) => <option key={value}>{value}</option>)}</select><select aria-label="Registry 상태" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">모든 상태</option>{REGISTRY_STATUSES.map((value) => <option key={value}>{value}</option>)}</select><label><input type="checkbox" checked={activeOnly} onChange={(event) => setActiveOnly(event.target.checked)} /> 활성 자산만</label></div>
      {loading ? <div className="ops-state">Registry를 불러오는 중입니다.</div> : error ? <div className="ops-state ops-state--error">{error}</div> : items.length === 0 ? <div className="ops-state">조건에 맞는 운영 자산이 없습니다.</div> : <div className="ops-table-wrap"><table><thead><tr><th>유형</th><th>자산</th><th>버전</th><th>Registry</th><th>검증</th><th>활성</th><th>Checksum</th><th>마지막 확인</th></tr></thead><tbody>{items.map((item) => <tr className="ops-row" key={item.id} onClick={() => navigate(`/system/operations/assets/${encodeURIComponent(item.id)}`)}><td>{item.asset_type}</td><td><strong>{item.asset_key}</strong></td><td>{item.current_version ?? "—"}</td><td><Status value={item.registry_status} /></td><td><Status value={item.validation_status} /></td><td>{item.active ? "ACTIVE" : "—"}</td><td><code title={item.sha256}>{shortHash(item.sha256)}</code></td><td>{when(item.last_seen_at)}</td></tr>)}</tbody></table></div>}
    </section>
  </main>;
}

import { useEffect, useMemo, useState } from "react";
import { ApiError } from "../../api";
import { navigate as browserNavigate, usePathname } from "../../routing";
import { getLatestReconciliation, getOperationalAsset, listOperationalAssets } from "./operationalAssetsApi";
import type { LatestReconciliation, OperationalAssetDetail, OperationalAssetSummary } from "./types";
import "./systemOperations.css";
import { MappingDraftsPage } from "./MappingDraftsPage";
import { useAuth } from "../auth/AuthContext";
import { canCreateSystemAssetVersion, canReadManagedContracts, canReadSystemAudit, canReadSystemE2E, canReadSystemImpact, canReadSystemJobs, canReadSystemLogs, canReadSystemModels, canReadSystemOperationalAssets } from "./permissions";
import { PipelineJobsPage } from "./PipelineJobsPage";
import { ImpactAnalysesPage } from "./ImpactAnalysesPage";
import { ManagedContractsPage } from "./ManagedContractsPage";
import { ModelOperationsPage } from "./ModelOperationsPage";
import { SystemAuditPage } from "./SystemAuditPage";
import { SystemLogsPage } from "./SystemLogsPage";
import { SystemE2EPage } from "./SystemE2EPage";
import { SystemOperationsNavigationProvider, useSystemOperationsNavigate } from "./SystemOperationsNavigation";

const ASSET_TYPES = ["static_mapping", "preprocessing_plan", "feature_schema", "label_schema", "history_requirement", "training_config", "feature_dataset_bundle", "model_artifact", "active_model_set", "protocol_contract", "dataset_contract"];
const REGISTRY_STATUSES = ["verified", "discovered", "invalid", "conflicted", "drifted", "unavailable"];

function shortHash(value?: string) { return value ? `${value.slice(0, 12)}…` : "—"; }
function when(value?: string) { return value ? new Date(value).toLocaleString() : "—"; }

function Status({ value }: { value?: string }) {
  return <span className={`ops-status ops-status--${value ?? "unknown"}`}>{value ?? "unknown"}</span>;
}

function Detail({ assetId }: { assetId: string }) {
  const navigate = useSystemOperationsNavigate();
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

export function SystemOperationsApp({ embedded = false }: { embedded?: boolean }) {
  const browserPathname = usePathname();
  const [embeddedPathname, setEmbeddedPathname] = useState("/system/operations/assets");
  const pathname = embedded ? embeddedPathname : browserPathname;
  const navigate = embedded ? setEmbeddedPathname : browserNavigate;
  return (
    <div className={embedded ? "ops-embedded" : undefined}>
      <SystemOperationsNavigationProvider navigate={navigate} pathname={pathname}>
        <SystemOperationsContent pathname={pathname} />
      </SystemOperationsNavigationProvider>
    </div>
  );
}

function SystemOperationsContent({ pathname }: { pathname: string }) {
  const { user } = useAuth();
  const permissions = user?.permissions;
  const navigate = useSystemOperationsNavigate();
  const denied = <main className="ops-page"><div className="ops-state ops-state--error">이 운영 화면을 조회할 권한이 없습니다.</div></main>;
  const navigation = (
    <nav className="ops-panel ops-nav-bar" aria-label="시스템 운영 영역">
      {canReadSystemOperationalAssets(permissions) && (
        <button
          className={pathname === "/system/operations" || pathname === "/system/operations/" || pathname.startsWith("/system/operations/assets") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/assets")}
        >
          운영 자산
        </button>
      )}
      {canCreateSystemAssetVersion(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/mappings") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/mappings/drafts")}
        >
          Mapping
        </button>
      )}
      {canReadManagedContracts(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/contracts") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/contracts")}
        >
          계약·설정
        </button>
      )}
      {canReadSystemModels(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/models") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/models")}
        >
          Model
        </button>
      )}
      {canReadSystemJobs(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/jobs") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/jobs")}
        >
          Rebuild
        </button>
      )}
      {canReadSystemImpact(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/impact") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/impact")}
        >
          영향 분석
        </button>
      )}
      {canReadSystemAudit(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/audit") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/audit")}
        >
          감사
        </button>
      )}
      {canReadSystemLogs(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/logs") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/logs")}
        >
          로그
        </button>
      )}
      {canReadSystemE2E(permissions) && (
        <button
          className={pathname.startsWith("/system/operations/e2e") ? "is-active" : undefined}
          onClick={() => navigate("/system/operations/e2e")}
        >
          E2E·알림
        </button>
      )}
    </nav>
  );
  let content;
  if (pathname === "/system/operations" || pathname === "/system/operations/") {
    if (canReadSystemOperationalAssets(permissions)) content = <OperationalAssetsApp pathname={pathname} />;
    else if (canReadManagedContracts(permissions)) content = <ManagedContractsPage />;
    else if (canReadSystemModels(permissions)) content = <ModelOperationsPage />;
    else if (canReadSystemJobs(permissions)) content = <PipelineJobsPage />;
    else if (canReadSystemImpact(permissions)) content = <ImpactAnalysesPage />;
    else if (canReadSystemAudit(permissions)) content = <SystemAuditPage />;
    else if (canReadSystemLogs(permissions)) content = <SystemLogsPage />;
    else if (canReadSystemE2E(permissions)) content = <SystemE2EPage />;
    else content = denied;
  } else {
    content = pathname.startsWith("/system/operations/mappings/drafts")
      ? (canCreateSystemAssetVersion(permissions) ? <MappingDraftsPage /> : denied)
      : pathname.startsWith("/system/operations/contracts")
      ? (canReadManagedContracts(permissions) ? <ManagedContractsPage /> : denied)
      : pathname.startsWith("/system/operations/models")
      ? (canReadSystemModels(permissions) ? <ModelOperationsPage /> : denied)
      : pathname.startsWith("/system/operations/audit")
      ? (canReadSystemAudit(permissions) ? <SystemAuditPage /> : denied)
      : pathname.startsWith("/system/operations/logs")
      ? (canReadSystemLogs(permissions) ? <SystemLogsPage /> : denied)
      : pathname.startsWith("/system/operations/e2e")
      ? (canReadSystemE2E(permissions) ? <SystemE2EPage /> : denied)
      : pathname.startsWith("/system/operations/impact")
      ? (canReadSystemImpact(permissions) ? <ImpactAnalysesPage /> : denied)
      : pathname.startsWith("/system/operations/jobs")
      ? (canReadSystemJobs(permissions) ? <PipelineJobsPage /> : denied)
      : (canReadSystemOperationalAssets(permissions) ? <OperationalAssetsApp pathname={pathname} /> : denied);
  }
  return <>{navigation}{content}</>;
}

function OperationalAssetsApp({ pathname }: { pathname: string }) {
  const navigate = useSystemOperationsNavigate();
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
    <header><p className="ops-eyebrow">SYSTEM OPERATIONS</p><h1>운영 자산</h1><p>Generator가 실제 사용하는 Mapping, Schema, Dataset Bundle과 Model Artifact의 검증 상태를 감독합니다.</p></header>
    <section className="ops-summary-grid"><article><span>등록 자산</span><strong>{total}</strong></article><article><span>최근 동기화</span><strong>{when(reconciliation?.completed_at)}</strong></article><article><span>검증됨</span><strong>{reconciliation?.verified_count ?? "—"}</strong></article><article><span>문제 발견</span><strong>{reconciliation ? reconciliation.invalid_count + reconciliation.conflicted_count : "—"}</strong></article></section>
    <section className="ops-panel">
      <div className="ops-filters">
        <input className="ops-search-input" aria-label="자산 검색" placeholder="자산 이름 또는 버전 검색" value={search} onChange={(event) => setSearch(event.target.value)} />
        <div className="ops-filters-row">
          <select aria-label="자산 유형" value={assetType} onChange={(event) => setAssetType(event.target.value)}>
            <option value="">모든 유형</option>
            {ASSET_TYPES.map((value) => <option key={value}>{value}</option>)}
          </select>
          <select aria-label="Registry 상태" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">모든 상태</option>
            {REGISTRY_STATUSES.map((value) => <option key={value}>{value}</option>)}
          </select>
          <label className="ops-checkbox-field">
            <input type="checkbox" checked={activeOnly} onChange={(event) => setActiveOnly(event.target.checked)} />
            <span>활성 자산만</span>
          </label>
        </div>
      </div>
      {loading ? <div className="ops-state">Registry를 불러오는 중입니다.</div> : error ? <div className="ops-state ops-state--error">{error}</div> : items.length === 0 ? <div className="ops-state">조건에 맞는 운영 자산이 없습니다.</div> : <div className="ops-table-wrap"><table><thead><tr><th>유형</th><th>자산</th><th>버전</th><th>Registry</th><th>검증</th><th>활성</th><th>Checksum</th><th>마지막 확인</th></tr></thead><tbody>{items.map((item) => <tr className="ops-row" key={item.id} onClick={() => navigate(`/system/operations/assets/${encodeURIComponent(item.id)}`)}><td>{item.asset_type}</td><td><strong>{item.asset_key}</strong></td><td>{item.current_version ?? "—"}</td><td><Status value={item.registry_status} /></td><td><Status value={item.validation_status} /></td><td>{item.active ? "ACTIVE" : "—"}</td><td><code title={item.sha256}>{shortHash(item.sha256)}</code></td><td>{when(item.last_seen_at)}</td></tr>)}</tbody></table></div>}
    </section>
  </main>;
}

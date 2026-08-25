import {
  Boxes,
  ClipboardCheck,
  LayoutDashboard,
  LogOut,
  Menu,
  RefreshCw,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import type { MvpContextModel, MvpRoleLens, MvpView } from "../api/mvpContracts";
import { MvpFreshness } from "../components/MvpUi";

const NAV_ITEMS: Array<{ id: MvpView; label: string; description: string; icon: typeof LayoutDashboard }> = [
  { id: "overview", label: "Overview", description: "운영 상황판", icon: LayoutDashboard },
  { id: "objects", label: "Assets", description: "설비 상태와 근거", icon: Boxes },
  { id: "operations", label: "Work Orders", description: "처리할 작업", icon: ClipboardCheck },
];

export function MvpShell({
  context,
  activeView,
  role,
  onNavigate,
  onRoleChange,
  onRefresh,
  refreshing,
  onLogout,
  children,
}: {
  context: MvpContextModel;
  activeView: MvpView;
  role: MvpRoleLens;
  onNavigate: (view: MvpView) => void;
  onRoleChange: (role: MvpRoleLens) => void;
  onRefresh: () => void;
  refreshing: boolean;
  onLogout: () => void | Promise<void>;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const active = NAV_ITEMS.find((item) => item.id === activeView)
    ?? (activeView === "reports"
      ? { id: "reports" as MvpView, label: "Report", description: "공유용 근거 문서", icon: ClipboardCheck }
      : NAV_ITEMS[0]);
  const headingDetail = activeView === "reports"
    ? "보고서는 top-level 업무가 아니라 선택 설비와 작업의 근거 문서로 확인합니다."
    : role === "process_manager"
      ? "전체 공정, 위험 셀, 처리할 작업을 한 화면에서 판단합니다."
      : "점검 요청과 설비 근거를 작업 단위로 확인합니다.";
  return (
    <main className="mvp-app">
      <header className="mvp-global-header">
        <div className="mvp-brand">
          <span className="mvp-brand-mark"><LayoutDashboard size={19} /></span>
          <div><span>Ontology Dashboard</span><strong>Predictive Maintenance</strong></div>
        </div>
        <div className="mvp-header-context" aria-label="현재 운영 문맥">
          <div><span>Project</span><strong>{context.projectName}</strong></div>
          <div><span>Workspace</span><strong>{context.workspaceName}</strong></div>
          <div className="is-dataset"><span>Dataset</span><strong title={context.datasetLabel}>Canonical V3.1 · {context.datasetVersionId}</strong></div>
        </div>
        <div className="mvp-header-actions">
          <label><span>역할</span><select value={role} onChange={(event) => onRoleChange(event.target.value as MvpRoleLens)}><option value="process_manager">생산 관리자</option><option value="field_operator">현장 담당자</option></select></label>
          <button type="button" className="mvp-icon-button" onClick={onRefresh} aria-label="데이터 새로고침" disabled={refreshing}><RefreshCw size={17} className={refreshing ? "is-spinning" : ""} /></button>
          <button type="button" className="mvp-icon-button" onClick={() => void onLogout()} aria-label="로그아웃" title="로그아웃"><LogOut size={17} /></button>
          <button type="button" className="mvp-icon-button mvp-mobile-menu" onClick={() => setMobileOpen((current) => !current)} aria-label="메뉴 열기">{mobileOpen ? <X size={19} /> : <Menu size={19} />}</button>
        </div>
      </header>

      <div className="mvp-context-line">
        <div><span className={`mvp-source-mode source-${context.sourceMode}`}>{context.sourceMode === "canonical-runtime" ? "운영 데이터 연결" : "보조 데이터 표시"}</span><strong>{context.sourceStatus}</strong></div>
        <MvpFreshness observedAt={context.observedAt} stale={context.stale} />
      </div>

      {context.warnings.length ? (
        <details className="mvp-source-warning">
          <summary>부분 연결 경고 {context.warnings.length}건</summary>
          <ul>{context.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </details>
      ) : null}

      <div className="mvp-workspace">
        <aside className={`mvp-navigation ${mobileOpen ? "is-open" : ""}`} aria-label="예지보전 화면">
          <div className="mvp-nav-intro"><span>WORKFLOW</span><strong>상황 → 설비 → 작업</strong><p>Ontology는 뒤에서 관계를 유지하고, 화면은 처리할 업무만 보여줍니다.</p></div>
          <nav>
            {NAV_ITEMS.map((item) => {
              const Icon = item.icon;
              return <button type="button" key={item.id} className={activeView === item.id ? "is-active" : ""} onClick={() => { onNavigate(item.id); setMobileOpen(false); }}><Icon size={17} /><div><strong>{item.label}</strong><span>{item.description}</span></div></button>;
            })}
          </nav>
          <div className="mvp-nav-footnote"><strong>Domain backbone</strong><span>Asset, Evidence, WorkOrder 관계는 각 Inspector 안에서 연결합니다.</span></div>
        </aside>
        <section className="mvp-main">
          <header className="mvp-page-heading"><span>{active.label}</span><h1>{active.description}</h1><p>{headingDetail}</p></header>
          {children}
        </section>
      </div>
    </main>
  );
}

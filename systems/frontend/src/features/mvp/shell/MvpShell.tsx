import {
  Factory,
  LayoutDashboard,
  LogOut,
  Menu,
  RefreshCw,
  Wrench,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import type { MvpContextModel, MvpRoleLens, MvpView } from "../api/mvpContracts";
import { MvpFreshness } from "../components/MvpUi";

const VIEW_LABELS: Record<MvpView, { label: string; description: string }> = {
  overview: { label: "Overview", description: "운영 상황판" },
  objects: { label: "Assets", description: "설비 상태와 근거" },
  operations: { label: "작업요청", description: "처리할 작업" },
  reports: { label: "Report", description: "공유용 근거 문서" },
};

const ROLE_SCREENS: Array<{ id: MvpRoleLens; label: string; description: string; icon: typeof LayoutDashboard }> = [
  { id: "field_operator", label: "현장 관리자", description: "점검 요청 · 의심 부품 · 처리 작업", icon: Wrench },
  { id: "process_manager", label: "생산 관리자", description: "공정 리스크 · 계획 영향 · 진행 현황", icon: Factory },
];

export function MvpShell({
  context,
  activeView,
  role,
  onRoleChange,
  onRefresh,
  refreshing,
  onLogout,
  children,
}: {
  context: MvpContextModel;
  activeView: MvpView;
  role: MvpRoleLens;
  onRoleChange: (role: MvpRoleLens) => void;
  onRefresh: () => void;
  refreshing: boolean;
  onLogout: () => void | Promise<void>;
  children: ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const active = activeView === "overview"
    ? ROLE_SCREENS.find((item) => item.id === role) ?? ROLE_SCREENS[0]
    : VIEW_LABELS[activeView];
  const headingDetail = activeView === "reports"
    ? "보고서는 top-level 업무가 아니라 선택 설비와 작업의 근거 문서로 확인합니다."
    : activeView !== "overview"
      ? "이 화면은 역할 업무판에서 선택한 항목의 보조 상세 흐름입니다."
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
            {ROLE_SCREENS.map((item) => {
              const Icon = item.icon;
              const activeItem = activeView === "overview" && role === item.id;
              return (
                <button
                  type="button"
                  key={item.id}
                  className={activeItem ? "is-active" : ""}
                  aria-current={activeItem ? "page" : undefined}
                  onClick={() => {
                    onRoleChange(item.id);
                    setMobileOpen(false);
                  }}
                >
                  <Icon size={17} />
                  <div><strong>{item.label}</strong><span>{item.description}</span></div>
                </button>
              );
            })}
          </nav>
          <div className="mvp-nav-footnote"><strong>업무 흐름</strong><span>설비, 근거, 작업요청 관계는 각 상세 화면 안에서 연결합니다.</span></div>
        </aside>
        <section className="mvp-main">
          <header className="mvp-page-heading"><span>{active.label}</span><h1>{active.description}</h1><p>{headingDetail}</p></header>
          {children}
        </section>
      </div>
    </main>
  );
}

import {
  Activity,
  ChevronsLeft,
  ChevronsRight,
  Focus,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Settings2,
  UserRound,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { AuthUser } from "../../types";
import { displayPreset, useDisplayPreferences } from "../../ui/foundry/displayPreferences";
import { useI18n } from "../../ui/i18n/I18nProvider";
import type {
  MvpContextModel,
  MvpEvent,
  MvpEventDetailModel,
  MvpView,
} from "../mvp/api/mvpContracts";
import "./reliability-workspace-preview.css";

type ExperienceKind = "operations" | "engineering" | "maintenance";

interface Experience {
  kind: ExperienceKind;
  label: { ko: string; en: string };
  nav: Array<{
    view: MvpView;
    label: { ko: string; en: string };
    detail: { ko: string; en: string };
  }>;
}

const EXPERIENCES: Record<ExperienceKind, Experience> = {
  operations: {
    kind: "operations",
    label: { ko: "생산 운영", en: "Production operations" },
    nav: [
      { view: "overview", label: { ko: "운영 현황", en: "Operations" }, detail: { ko: "라인 위험 · 생산 영향", en: "Line risk · production impact" } },
      { view: "operations", label: { ko: "판단 및 작업", en: "Decisions & work" }, detail: { ko: "점검 · 판단 · 작업 진행", en: "Inspection · decision · work progress" } },
      { view: "objects", label: { ko: "설비", en: "Assets" }, detail: { ko: "설비별 위험과 근거", en: "Asset risk and evidence" } },
      { view: "reports", label: { ko: "보고", en: "Reports" }, detail: { ko: "운영 보고서 작성", en: "Operational reporting" } },
    ],
  },
  engineering: {
    kind: "engineering",
    label: { ko: "신뢰성 분석", en: "Reliability analysis" },
    nav: [
      { view: "overview", label: { ko: "진단 현황", en: "Diagnostics" }, detail: { ko: "이상 신호 · 원인 후보", en: "Signals · suspected causes" } },
      { view: "objects", label: { ko: "설비 진단", en: "Asset analysis" }, detail: { ko: "센서 · 예측 · 근거", en: "Sensors · predictions · evidence" } },
      { view: "operations", label: { ko: "점검 기록", en: "Inspection record" }, detail: { ko: "현장 결과 · 분석 이력", en: "Field findings · analysis history" } },
      { view: "reports", label: { ko: "분석 보고", en: "Analysis report" }, detail: { ko: "근거 검토 · 보고서 작성", en: "Evidence review · reporting" } },
    ],
  },
  maintenance: {
    kind: "maintenance",
    label: { ko: "정비 실행", en: "Maintenance execution" },
    nav: [
      { view: "operations", label: { ko: "내 작업", en: "My work" }, detail: { ko: "승인 작업 · 진행 상태", en: "Approved work · progress" } },
      { view: "objects", label: { ko: "작업 대상", en: "Work targets" }, detail: { ko: "위치 · 상태 · 근거", en: "Location · condition · evidence" } },
      { view: "overview", label: { ko: "현장 현황", en: "Field status" }, detail: { ko: "점검 · 정비 진행 상황", en: "Inspection · maintenance progress" } },
      { view: "reports", label: { ko: "작업 이력", en: "Work history" }, detail: { ko: "완료 결과 · 기록", en: "Completion results · record" } },
    ],
  },
};

function resolveExperience(user: AuthUser): Experience {
  const roles = user.active_project_roles.length ? user.active_project_roles : user.roles;
  if (roles.includes("process_manager") || user.is_admin) return EXPERIENCES.operations;
  if (roles.includes("maintenance_technician")) return EXPERIENCES.maintenance;
  return EXPERIENCES.engineering;
}

function pageCopy(kind: ExperienceKind, view: MvpView, english: boolean) {
  if (kind === "maintenance") {
    if (view === "objects") return english
      ? ["WORK TARGETS", "Asset location and field evidence", "Review location, status, and evidence needed for approved work."]
      : ["작업 대상", "설비 위치와 현장 근거", "승인된 작업에 필요한 위치, 상태, 근거를 먼저 확인합니다."];
    if (view === "reports") return english
      ? ["WORK HISTORY", "Completed work and field records", "Trace completion results and field records from the same event."]
      : ["작업 이력", "완료 작업과 현장 기록", "완료 결과와 현장 기록을 같은 사건 기준으로 추적합니다."];
    return english
      ? ["MY WORK", "Approved maintenance work", "Start with where to go, what to do, and the required sequence."]
      : ["내 작업", "승인된 정비 작업", "어디에서 무엇을 해야 하는지 작업 순서 중심으로 확인합니다."];
  }
  if (kind === "engineering") {
    if (view === "objects") return english
      ? ["ROOT-CAUSE ANALYSIS", "Equipment signals and causal evidence", "Compare sensor trends, model contribution, and history to narrow causes."]
      : ["원인 분석", "설비 신호와 원인 근거", "센서 추세, 모델 기여도, 이력을 함께 보며 원인 후보를 좁힙니다."];
    if (view === "operations") return english
      ? ["INSPECTION", "Evidence-based inspection record", "Connect field findings and uncertainty back to the source evidence."]
      : ["점검", "근거 기반 점검 기록", "현장 확인 결과와 남은 불확실성을 원천 근거에 연결합니다."];
    return english
      ? ["DIAGNOSTICS", "Equipment signals and evidence", "Start from measurements and sensor changes to narrow suspected causes."]
      : ["진단 현황", "설비 이상 신호와 근거", "수치와 센서 변화부터 탐색해 원인 후보를 좁혀갑니다."];
  }
  if (view === "operations") return english
    ? ["DECISION CASE", "Pending decisions and work progress", "Connect field findings, production impact, and the next operational decision."]
    : ["Decision Case", "검토 대기와 작업 진행", "현장 점검 결과와 생산 영향, 다음 운영 판단을 연결합니다."];
  if (view === "objects") return english
    ? ["PRODUCTION IMPACT", "Operational impact of asset risk", "Connect downtime, planned unit loss, and material constraints."]
    : ["생산 영향", "설비 위험의 운영 영향", "예상 정지, 계획 손실 수량, 자재 제약을 함께 확인합니다."];
  if (view === "reports") return english
    ? ["REPORTS", "Reporting artifacts from decisions", "Review report drafts and snapshots produced from the same case."]
    : ["보고", "Case에서 이어지는 보고 산출물", "같은 Case에서 생성되는 보고 초안과 snapshot을 확인합니다."];
  return english
    ? ["OPERATIONS", "Production risk and response status", "See which lines are exposed and what decisions require attention first."]
    : ["운영 현황", "생산 리스크와 조치 현황", "어느 라인이 영향을 받고 무엇을 먼저 판단해야 하는지 확인합니다."];
}

function probability(value: number | null | undefined) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function riskLabel(status: MvpEvent["status"] | null | undefined, english: boolean) {
  const labels: Record<MvpEvent["status"], [string, string]> = {
    normal: ["정상", "Normal"],
    attention: ["주의", "Attention"],
    warning: ["경고", "Warning"],
    critical: ["고위험", "Critical"],
    data_quality_hold: ["데이터 확인 필요", "Data quality hold"],
  };
  return status ? labels[status][english ? 1 : 0] : "—";
}

function decisionLabel(value: MvpEvent["recommendedDecision"] | null | undefined, english: boolean) {
  const labels: Record<MvpEvent["recommendedDecision"], [string, string]> = {
    continue_monitoring: ["계속 관찰", "Continue monitoring"],
    request_inspection: ["현장 점검 요청", "Request inspection"],
    review_shutdown: ["정지 검토 요청", "Review shutdown"],
    hold_for_data_check: ["데이터 확인 보류", "Hold for data check"],
  };
  return value ? labels[value][english ? 1 : 0] : "—";
}

export function reliabilityWorkspacePreviewEnabled() {
  return new URLSearchParams(window.location.search).get("workspace_shell") === "reliability";
}

export function ReliabilityWorkspacePreview({
  context,
  activeView,
  user,
  selectedEvent,
  detail,
  onNavigate,
  onRefresh,
  refreshing,
  onLogout,
  children,
}: {
  context: MvpContextModel;
  activeView: MvpView;
  user: AuthUser;
  selectedEvent: MvpEvent | null;
  detail: MvpEventDetailModel | null;
  onNavigate: (view: MvpView) => void;
  onRefresh: () => void;
  refreshing: boolean;
  onLogout: () => void | Promise<void>;
  children: ReactNode;
}) {
  const { locale, setLocale } = useI18n();
  const { preferences, setPreset, setShowTechnicalMetadata } = useDisplayPreferences();
  const english = locale === "en-US";
  const experience = useMemo(() => resolveExperience(user), [user]);
  const activeNav = experience.nav.find((item) => item.view === activeView) ?? experience.nav[0];
  const [eyebrow, title, detailCopy] = pageCopy(experience.kind, activeView, english);
  const preset = displayPreset(preferences);
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth > 860);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showGuidance, setShowGuidance] = useState(true);
  const [theme, setTheme] = useState<"dark" | "light">(() => (
    window.localStorage.getItem("ontology-dashboard-theme") === "dark" ? "dark" : "light"
  ));

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("ontology-dashboard-theme", theme);
  }, [theme]);

  useEffect(() => {
    function syncNavigation() {
      if (window.innerWidth <= 860) setLeftOpen(false);
    }
    window.addEventListener("resize", syncNavigation);
    return () => window.removeEventListener("resize", syncNavigation);
  }, []);

  return (
    <main className={`rw-preview-shell role-${experience.kind} ${leftOpen ? "left-open" : "left-collapsed"}`}>
      <header className="rw-preview-topbar">
        <div className="rw-preview-topbar-left">
          <button type="button" className="rw-preview-icon-button" onClick={() => setLeftOpen((value) => !value)} aria-label={leftOpen ? "Collapse navigation" : "Open navigation"}>
            {leftOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
          </button>
          <div className="rw-preview-brand"><span><Activity size={15} /></span><div><strong>Reliability Operations</strong><small>{english ? "Role-aware workspace" : "역할 기반 업무 공간"}</small></div></div>
          <div className="rw-preview-breadcrumb"><span>{context.projectName}</span><i>/</i><strong>{english ? activeNav.label.en : activeNav.label.ko}</strong></div>
        </div>
        <div className="rw-preview-user"><span><UserRound size={13} /></span><div><strong>{user.display_name}</strong><small>{english ? experience.label.en : experience.label.ko}</small></div></div>
      </header>

      <div className="rw-preview-body">
        <aside className="rw-preview-left">
          <div className="rw-preview-left-heading"><span>{english ? experience.label.en : experience.label.ko}</span><strong>{english ? "Workspace" : "업무 공간"}</strong></div>
          <nav aria-label={english ? "Role workflow navigation" : "역할별 업무 탐색"}>
            {experience.nav.map((item, index) => (
              <button type="button" key={item.view} className={activeView === item.view ? "is-active" : ""} aria-current={activeView === item.view ? "page" : undefined} onClick={() => { if (window.innerWidth <= 860) setLeftOpen(false); onNavigate(item.view); }} title={!leftOpen ? (english ? item.label.en : item.label.ko) : undefined}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{english ? item.label.en : item.label.ko}</strong><small>{english ? item.detail.en : item.detail.ko}</small></div>
              </button>
            ))}
          </nav>
          <section className="rw-preview-scope"><span>{english ? "SCOPE" : "현재 범위"}</span><strong>{context.workspaceName}</strong><small>{context.sourceStatus}</small></section>
          <section className={`rw-preview-settings ${settingsOpen ? "is-open" : ""}`}>
            <button type="button" className="rw-preview-settings-trigger" aria-expanded={settingsOpen && leftOpen} onClick={() => { if (!leftOpen) setLeftOpen(true); setSettingsOpen((value) => !value); }}><Settings2 size={14} /><span>{english ? "Settings" : "환경설정"}</span></button>
            {settingsOpen && leftOpen ? <div className="rw-preview-settings-panel">
              <header><strong>{english ? "Workspace settings" : "사용자 환경"}</strong><small>{user.display_name}</small></header>
              <div className="rw-preview-settings-group"><span>{english ? "Language" : "언어"}</span><div className="rw-preview-segmented two"><button type="button" className={!english ? "is-active" : ""} onClick={() => setLocale("ko-KR")}>한국어</button><button type="button" className={english ? "is-active" : ""} onClick={() => setLocale("en-US")}>English</button></div></div>
              <div className="rw-preview-settings-group"><span>{english ? "Theme" : "화면 테마"}</span><div className="rw-preview-segmented two"><button type="button" className={theme === "dark" ? "is-active" : ""} onClick={() => setTheme("dark")}>Dark</button><button type="button" className={theme === "light" ? "is-active" : ""} onClick={() => setTheme("light")}>Light</button></div></div>
              <div className="rw-preview-settings-group"><span>{english ? "Display density" : "화면 밀도"}</span><div className="rw-preview-segmented three">{(["compact", "standard", "accessible"] as const).map((value) => <button type="button" key={value} className={preset === value ? "is-active" : ""} onClick={() => setPreset(value)}>{value === "compact" ? (english ? "Compact" : "조밀") : value === "standard" ? (english ? "Standard" : "기본") : (english ? "Accessible" : "확대")}</button>)}</div></div>
              <button type="button" className="rw-preview-settings-action" onClick={() => setShowGuidance(!showGuidance)}><span>{english ? "Screen guidance" : "화면 도움말"}</span><strong>{showGuidance ? (english ? "Shown" : "표시") : (english ? "Hidden" : "숨김")}</strong></button>
              <button type="button" className="rw-preview-settings-action" onClick={() => setShowTechnicalMetadata(!preferences.showTechnicalMetadata)}><span>{english ? "Technical metadata" : "기술 메타데이터"}</span><strong>{preferences.showTechnicalMetadata ? (english ? "Shown" : "표시") : (english ? "Hidden" : "숨김")}</strong></button>
              <button type="button" className="rw-preview-settings-action" onClick={onRefresh} disabled={refreshing}><span><RefreshCw size={12} />{english ? "Refresh data" : "최신 데이터 다시 확인"}</span></button>
              <button type="button" className="rw-preview-settings-action" onClick={() => { setLeftOpen(false); setSettingsOpen(false); }}><span><Focus size={12} />{english ? "Focus mode" : "집중 모드"}</span></button>
              <button type="button" className="rw-preview-settings-action is-danger" onClick={() => void onLogout()}><span><LogOut size={12} />{english ? "Switch account" : "계정 전환"}</span></button>
            </div> : null}
          </section>
          <button type="button" className="rw-preview-collapse" onClick={() => setLeftOpen((value) => !value)}>{leftOpen ? <><ChevronsLeft size={13} /><span>{english ? "Collapse" : "접기"}</span></> : <ChevronsRight size={13} />}</button>
        </aside>

        <section className="rw-preview-main">
          {context.warnings.length ? <details className="rw-preview-warning"><summary>{english ? `${context.warnings.length} data notice(s)` : `데이터 참고사항 ${context.warnings.length}건`}</summary><ul>{context.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details> : null}
          <header className="rw-preview-page-heading"><span>{eyebrow}</span><h1>{title}</h1><p>{detailCopy}</p></header>
          {showGuidance ? <section className="rw-preview-guidance" aria-label={english ? "Screen guidance" : "화면 도움말"}>
            <strong>{english ? "How to read this screen" : "이 화면을 보는 순서"}</strong>
            <ol>
              <li>{english ? "Confirm which equipment or line is at risk." : "먼저 어떤 설비와 라인이 위험한지 확인합니다."}</li>
              <li>{english ? "Review the evidence, impact, and current workflow step." : "근거, 생산 영향, 현재 workflow 단계를 함께 봅니다."}</li>
              <li>{english ? "Move to the role-specific next action from the left navigation." : "좌측 역할 메뉴에서 내가 맡은 다음 행동으로 이동합니다."}</li>
            </ol>
          </section> : null}
          {selectedEvent ? <section className={`rw-preview-selection-anchor tone-${selectedEvent.status}`}>
            <div><span>{english ? "CURRENT CONTEXT" : "현재 선택"}</span><strong>{selectedEvent.assetName || selectedEvent.assetId}</strong><small>{selectedEvent.line}</small></div>
            <dl><div><dt>{english ? "Risk" : "위험"}</dt><dd>{riskLabel(selectedEvent.status, english)} · {probability(selectedEvent.failureProbability)}</dd></div><div><dt>{english ? "Decision" : "운영 판단"}</dt><dd>{decisionLabel(selectedEvent.recommendedDecision, english)}</dd></div><div><dt>{english ? "Detail" : "상세 근거"}</dt><dd>{detail ? (english ? "Linked" : "연결됨") : (english ? "Loading" : "불러오는 중")}</dd></div></dl>
          </section> : null}
          <div className="rw-preview-content">{children}</div>
        </section>
      </div>

      <footer className="rw-preview-bottom">
        <div className="rw-preview-live"><Activity size={12} /><strong>LIVE</strong><span>{context.observedAt ?? context.refreshedAt}</span></div>
        <div className="rw-preview-selection"><strong>{selectedEvent?.assetName ?? (english ? "No selection" : "선택 없음")}</strong><span>{selectedEvent ? `${riskLabel(selectedEvent.status, english)} · ${probability(selectedEvent.failureProbability)}` : "—"}</span></div>
        <div className="rw-preview-boundary">{english ? "UI shell only · workflow authority remains in backend" : "UI shell 전용 · workflow 판단 권한은 backend 유지"}</div>
      </footer>
    </main>
  );
}

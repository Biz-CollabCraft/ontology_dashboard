import {
  Activity,
  Bot,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Focus,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Search,
  Send,
  Settings2,
  Sparkles,
  Sun,
  UserRound,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useState, type ReactNode } from "react";
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

type ExperienceKind = "executive" | "operations" | "engineering" | "maintenance";

interface Experience {
  kind: ExperienceKind;
  koLabel: string;
  enLabel: string;
  nav: Array<{ view: MvpView; ko: string; en: string; koDetail: string; enDetail: string }>;
}

const EXPERIENCES: Record<ExperienceKind, Experience> = {
  executive: {
    kind: "executive",
    koLabel: "경영 보고",
    enLabel: "Executive briefing",
    nav: [
      { view: "overview", ko: "브리핑", en: "Briefing", koDetail: "생산 연속성 · 경영 판단", enDetail: "Continuity · executive decisions" },
      { view: "reports", ko: "보고서", en: "Reports", koDetail: "상황 보고 · 의사결정 기록", enDetail: "Situation reports · decision record" },
      { view: "objects", ko: "상세 근거", en: "Evidence", koDetail: "필요할 때만 설비 단위 확인", enDetail: "Asset detail only when needed" },
    ],
  },
  operations: {
    kind: "operations",
    koLabel: "생산 운영",
    enLabel: "Production operations",
    nav: [
      { view: "overview", ko: "운영 현황", en: "Operations", koDetail: "라인 위험 · 생산 영향", enDetail: "Line risk · production impact" },
      { view: "operations", ko: "판단 및 작업", en: "Decisions & work", koDetail: "점검 · 판단 · 작업 진행", enDetail: "Inspection · decision · work progress" },
      { view: "objects", ko: "설비", en: "Assets", koDetail: "설비별 위험과 근거", enDetail: "Asset risk and evidence" },
      { view: "reports", ko: "보고", en: "Reports", koDetail: "운영 보고서 작성", enDetail: "Operational reporting" },
    ],
  },
  engineering: {
    kind: "engineering",
    koLabel: "신뢰성 분석",
    enLabel: "Reliability analysis",
    nav: [
      { view: "overview", ko: "진단 현황", en: "Diagnostics", koDetail: "이상 신호 · 원인 후보", enDetail: "Signals · suspected causes" },
      { view: "objects", ko: "설비 진단", en: "Asset analysis", koDetail: "센서 · 예측 · 근거", enDetail: "Sensors · predictions · evidence" },
      { view: "operations", ko: "점검 기록", en: "Inspection record", koDetail: "현장 결과 · 분석 이력", enDetail: "Field findings · analysis history" },
      { view: "reports", ko: "분석 보고", en: "Analysis report", koDetail: "근거 검토 · 보고서 작성", enDetail: "Evidence review · reporting" },
    ],
  },
  maintenance: {
    kind: "maintenance",
    koLabel: "정비 실행",
    enLabel: "Maintenance execution",
    nav: [
      { view: "operations", ko: "내 작업", en: "My work", koDetail: "승인 작업 · 진행 상태", enDetail: "Approved work · progress" },
      { view: "objects", ko: "작업 대상", en: "Work targets", koDetail: "위치 · 상태 · 근거", enDetail: "Location · condition · evidence" },
      { view: "overview", ko: "현장 현황", en: "Field status", koDetail: "점검 · 정비 진행 상황", enDetail: "Inspection · maintenance progress" },
      { view: "reports", ko: "작업 이력", en: "Work history", koDetail: "완료 결과 · 기록", enDetail: "Completion results · record" },
    ],
  },
};

function resolveExperience(user: AuthUser): Experience {
  const roles = user.active_project_roles.length ? user.active_project_roles : user.roles;
  if (roles.includes("executive_viewer")) return EXPERIENCES.executive;
  if (roles.includes("process_manager") || user.is_admin) return EXPERIENCES.operations;
  if (roles.includes("maintenance_technician")) return EXPERIENCES.maintenance;
  return EXPERIENCES.engineering;
}

function pageCopy(kind: ExperienceKind, view: MvpView, english: boolean) {
  if (kind === "executive") {
    if (view === "reports") return english
      ? ["REPORTS", "Executive situation report", "Start with the conclusion and drill into evidence only when needed."]
      : ["보고서", "경영 상황 보고", "핵심 결론을 먼저 보고 필요한 근거만 내려봅니다."];
    if (view === "objects") return english
      ? ["EVIDENCE", "Asset-level evidence", "Use this view only to validate a conclusion from the executive briefing."]
      : ["상세 근거", "설비 단위 근거 확인", "브리핑의 결론을 검증할 때만 사용하는 상세 화면입니다."];
    return english
      ? ["BRIEFING", "Production continuity and decisions", "Prioritize business impact and executive decision requests over raw equipment metrics."]
      : ["브리핑", "생산 안정성과 의사결정", "설비 수치가 아니라 경영진이 확인해야 할 영향과 판단 요청을 우선합니다."];
  }
  if (kind === "maintenance") {
    if (view === "objects") return english
      ? ["WORK TARGETS", "Equipment location and work evidence", "Show only the information needed to perform approved work safely."]
      : ["작업 대상", "설비 위치와 작업 근거", "승인된 작업을 수행하는 데 필요한 설비 정보만 확인합니다."];
    return english
      ? ["MY WORK", "Approved maintenance work", "Start with where to go, what to do, and the required sequence."]
      : ["내 작업", "승인된 정비 작업", "어디에서 무엇을 해야 하는지 작업 순서 중심으로 확인합니다."];
  }
  if (kind === "engineering") {
    if (view === "objects") return english
      ? ["ASSET ANALYSIS", "Equipment signals and causal evidence", "Analyze sensors, predictions, contribution factors, and history in one flow."]
      : ["설비 진단", "설비 신호와 원인 근거", "센서, 예측, 원인 기여와 이력을 한 흐름에서 분석합니다."];
    return english
      ? ["DIAGNOSTICS", "Equipment anomaly signals and evidence", "Start from measurements and sensor changes to narrow suspected causes."]
      : ["진단 현황", "설비 이상 신호와 근거", "수치와 센서 변화부터 탐색해 원인 후보를 좁혀갑니다."];
  }
  if (view === "objects") return english
    ? ["ASSETS", "Asset risk and production impact", "Review how risk signals translate into operational impact by asset."]
    : ["설비", "설비별 위험과 생산 영향", "위험 신호가 실제 운영에 미치는 영향을 설비 단위로 확인합니다."];
  if (view === "operations") return english
    ? ["DECISIONS & WORK", "Pending decisions and work progress", "Connect field findings, production impact, and the next operational decision."]
    : ["판단 및 작업", "검토 대기와 작업 진행", "현장 점검 결과와 생산 영향, 다음 운영 판단을 연결합니다."];
  return english
    ? ["OPERATIONS", "Production risk and response status", "See which lines are exposed and what decisions are required first."]
    : ["운영 현황", "생산 리스크와 조치 현황", "어느 라인이 영향을 받고 무엇을 판단해야 하는지부터 확인합니다."];
}

function probability(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function decisionLabel(value: string | null | undefined, english: boolean) {
  const labels: Record<string, [string, string]> = {
    continue_monitoring: ["계속 관찰", "Continue monitoring"],
    request_inspection: ["현장 점검", "Request inspection"],
    review_shutdown: ["정지 검토", "Review shutdown"],
    hold_for_data_check: ["데이터 확인", "Hold for data check"],
  };
  if (!value) return english ? "No decision" : "판단 없음";
  return labels[value]?.[english ? 1 : 0] ?? value.replaceAll("_", " ");
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
  const preset = displayPreset(preferences);
  const activeNav = experience.nav.find((item) => item.view === activeView) ?? experience.nav[0];
  const [eyebrow, title, detailCopy] = pageCopy(experience.kind, activeView, english);
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const saved = window.localStorage.getItem("ontology-dashboard-theme");
    return saved === "light" ? "light" : "dark";
  });
  const [leftOpen, setLeftOpen] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [flowOpen, setFlowOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<string[]>([
    english ? "I can summarize the selected operational context without executing or approving work." : "선택한 운영 문맥을 실행·승인 없이 요약할 수 있습니다.",
  ]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("ontology-dashboard-theme", theme);
  }, [theme]);

  const evidenceConnected = Boolean(detail?.loadedSources.evidence);
  const inspectionCount = detail?.inspectionTargets.length ?? 0;
  const workOrderCount = detail?.closedLoop?.workOrders.length ?? 0;
  const maintenanceCount = detail?.closedLoop?.maintenanceEvents.length ?? 0;

  function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed) return;
    const asset = selectedEvent?.assetName ?? selectedEvent?.assetId ?? (english ? "No selection" : "선택 없음");
    const risk = probability(selectedEvent?.failureProbability ?? null);
    const decision = decisionLabel(selectedEvent?.recommendedDecision, english);
    const answer = selectedEvent
      ? english
        ? `${asset} is at ${risk} risk. Current operational decision: “${decision}”. ${workOrderCount ? `${workOrderCount} linked work order(s) are visible.` : "No linked work order is visible yet."}`
        : `${asset}의 현재 위험은 ${risk}, 운영 판단은 “${decision}”입니다. ${workOrderCount ? `연결된 WorkOrder ${workOrderCount}건이 확인됩니다.` : "아직 연결된 WorkOrder는 없습니다."}`
      : english
        ? "Select an asset or event in the workspace and I will answer from that context."
        : "메인 화면에서 설비나 이벤트를 선택하면 그 문맥을 기준으로 답변합니다.";
    setMessages((current) => [...current, `YOU · ${trimmed}`, `ASSISTANT · ${answer}`]);
    setDraft("");
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    ask(draft);
  }

  const prompts = english
    ? ["What needs a decision?", "Why is this asset prioritized?", "Show the supporting evidence"]
    : ["지금 판단할 건 뭐야?", "왜 이 설비가 우선이야?", "근거를 보여줘"];

  const flow = [
    ["Prediction", Boolean(selectedEvent)],
    ["Evidence", evidenceConnected],
    ["Inspection", inspectionCount > 0],
    ["Decision", Boolean(selectedEvent?.recommendedDecision)],
    ["WorkOrder", workOrderCount > 0],
    ["Maintenance", maintenanceCount > 0],
  ] as const;

  return (
    <main className={`rw-preview-shell ${leftOpen ? "left-open" : "left-collapsed"} ${assistantOpen ? "assistant-open" : "assistant-closed"}`}>
      <header className="rw-preview-topbar">
        <div className="rw-preview-topbar-left">
          <button type="button" className="rw-preview-icon-button" onClick={() => setLeftOpen((value) => !value)} aria-label={leftOpen ? "Collapse navigation" : "Open navigation"}>{leftOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}</button>
          <div className="rw-preview-brand"><span><Activity size={15} /></span><strong>Reliability Operations</strong></div>
          <div className="rw-preview-breadcrumb"><span>{context.projectName}</span><i>/</i><strong>{english ? activeNav.en : activeNav.ko}</strong></div>
        </div>
        <div className="rw-preview-topbar-right">
          <button type="button" className="rw-preview-search"><Search size={14} /><span>{english ? "Search" : "검색"}</span><kbd>⌘K</kbd></button>
          <button type="button" className={`rw-preview-assistant-toggle ${assistantOpen ? "is-active" : ""}`} onClick={() => setAssistantOpen((value) => !value)}>{assistantOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}<span>Assistant</span></button>
          <div className="rw-preview-user"><span><UserRound size={13} /></span><div><strong>{user.display_name}</strong><small>{english ? experience.enLabel : experience.koLabel}</small></div></div>
        </div>
      </header>

      <div className="rw-preview-body">
        <aside className="rw-preview-left">
          <div className="rw-preview-left-heading"><span>{english ? experience.enLabel : experience.koLabel}</span><strong>{english ? "Workspace" : "업무 공간"}</strong></div>
          <nav>
            {experience.nav.map((item, index) => (
              <button type="button" key={item.view} className={activeView === item.view ? "is-active" : ""} onClick={() => onNavigate(item.view)} title={!leftOpen ? (english ? item.en : item.ko) : undefined}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{english ? item.en : item.ko}</strong><small>{english ? item.enDetail : item.koDetail}</small></div>
              </button>
            ))}
          </nav>
          <section className="rw-preview-scope"><span>{english ? "SCOPE" : "현재 범위"}</span><strong>{context.workspaceName}</strong><small>{context.sourceStatus}</small></section>
          <section className={`rw-preview-settings ${settingsOpen ? "is-open" : ""}`}>
            <button type="button" className="rw-preview-settings-trigger" onClick={() => { if (!leftOpen) setLeftOpen(true); setSettingsOpen((value) => !value); }}><Settings2 size={14} /><span>{english ? "Settings" : "환경설정"}</span></button>
            {settingsOpen && leftOpen ? <div className="rw-preview-settings-panel">
              <header><strong>{english ? "Workspace settings" : "사용자 환경"}</strong><small>{user.display_name}</small></header>
              <div className="rw-preview-settings-group"><span>{english ? "Language" : "언어"}</span><div className="rw-preview-segmented two"><button type="button" className={!english ? "is-active" : ""} onClick={() => setLocale("ko-KR")}>한국어</button><button type="button" className={english ? "is-active" : ""} onClick={() => setLocale("en-US")}>English</button></div></div>
              <div className="rw-preview-settings-group"><span>{english ? "Theme" : "화면 테마"}</span><div className="rw-preview-segmented two"><button type="button" className={theme === "dark" ? "is-active" : ""} onClick={() => setTheme("dark")}><Moon size={12} />Dark</button><button type="button" className={theme === "light" ? "is-active" : ""} onClick={() => setTheme("light")}><Sun size={12} />Light</button></div></div>
              <div className="rw-preview-settings-group"><span>{english ? "Display density" : "화면 밀도"}</span><div className="rw-preview-segmented three">{(["compact", "standard", "accessible"] as const).map((value) => <button type="button" key={value} className={preset === value ? "is-active" : ""} onClick={() => setPreset(value)}>{value === "compact" ? (english ? "Compact" : "조밀") : value === "standard" ? (english ? "Standard" : "기본") : (english ? "Accessible" : "확대")}</button>)}</div></div>
              <button type="button" className="rw-preview-settings-action" onClick={() => setShowTechnicalMetadata(!preferences.showTechnicalMetadata)}><span>{english ? "Technical metadata" : "기술 메타데이터"}</span><strong>{preferences.showTechnicalMetadata ? (english ? "Shown" : "표시") : (english ? "Hidden" : "숨김")}</strong></button>
              <button type="button" className="rw-preview-settings-action" onClick={onRefresh} disabled={refreshing}><span><RefreshCw size={12} />{english ? "Refresh data" : "최신 데이터 다시 확인"}</span></button>
              <button type="button" className="rw-preview-settings-action" onClick={() => { setLeftOpen(false); setAssistantOpen(false); setSettingsOpen(false); }}><span><Focus size={12} />{english ? "Focus mode" : "집중 모드"}</span></button>
              <button type="button" className="rw-preview-settings-action is-danger" onClick={() => void onLogout()}><span><LogOut size={12} />{english ? "Switch account" : "계정 전환"}</span></button>
            </div> : null}
          </section>
          <button type="button" className="rw-preview-collapse" onClick={() => setLeftOpen((value) => !value)}>{leftOpen ? <><ChevronsLeft size={13} /><span>{english ? "Collapse" : "접기"}</span></> : <ChevronsRight size={13} />}</button>
        </aside>

        <section className="rw-preview-main">
          {context.warnings.length ? <details className="rw-preview-warning"><summary>{english ? `${context.warnings.length} data notice(s)` : `데이터 참고사항 ${context.warnings.length}건`}</summary><ul>{context.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details> : null}
          <header className="rw-preview-page-heading"><span>{eyebrow}</span><h1>{title}</h1><p>{detailCopy}</p></header>
          <div className="rw-preview-content">{children}</div>
        </section>

        {assistantOpen ? <aside className="rw-preview-assistant">
          <header><div><span><Sparkles size={14} /></span><div><strong>Reliability Assistant</strong><small>{selectedEvent?.assetName ?? (english ? "No selection" : "선택 없음")}</small></div></div><button type="button" onClick={() => setAssistantOpen(false)}><PanelRightClose size={15} /></button></header>
          <section className="rw-preview-assistant-context"><span>{english ? "CURRENT CONTEXT" : "현재 문맥"}</span><strong>{selectedEvent?.assetName ?? (english ? "No selection" : "선택 없음")}</strong><small>{selectedEvent ? `${probability(selectedEvent.failureProbability)} · ${decisionLabel(selectedEvent.recommendedDecision, english)}` : (english ? "Select an asset in the workspace." : "메인 화면에서 설비를 선택하세요.")}</small><div><b>Evidence <em>{evidenceConnected ? (english ? "linked" : "연결") : "—"}</em></b><b>Inspection <em>{inspectionCount}</em></b><b>WorkOrder <em>{workOrderCount}</em></b></div></section>
          <div className="rw-preview-prompts">{prompts.map((prompt) => <button type="button" key={prompt} onClick={() => ask(prompt)}>{prompt}<ChevronRight size={12} /></button>)}</div>
          <section className="rw-preview-thread">{messages.map((message, index) => <article key={`${message}-${index}`} className={message.startsWith("YOU") ? "is-user" : "is-assistant"}>{message.startsWith("ASSISTANT") || (!message.startsWith("YOU") && index === 0) ? <span><Bot size={13} /></span> : null}<p>{message.replace(/^YOU · |^ASSISTANT · /, "")}</p></article>)}</section>
          <form className="rw-preview-compose" onSubmit={submit}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={english ? "Ask about the current asset or operating state" : "현재 설비나 운영 상태를 질문하세요"} rows={2} /><button type="submit" disabled={!draft.trim()}><Send size={15} /></button></form>
          <footer>{english ? "Context-only preview. Does not execute or approve work." : "현재 연결된 운영 데이터만 요약하는 WIP preview입니다. 작업 실행이나 승인은 하지 않습니다."}</footer>
        </aside> : null}
      </div>

      <footer className="rw-preview-bottom">
        {flowOpen ? <div className="rw-preview-flow"><div><span>{english ? "CLOSED-LOOP FLOW" : "폐쇄루프 흐름"}</span><strong>{selectedEvent?.assetName ?? (english ? "No selection" : "선택 없음")}</strong></div><div className="rw-preview-flow-track">{flow.map(([label, ready]) => <span key={label} className={ready ? "is-ready" : ""}><i />{label}</span>)}</div></div> : null}
        <div className="rw-preview-status"><div className="rw-preview-live"><Activity size={12} /><strong>LIVE</strong><span>{context.observedAt ?? context.refreshedAt}</span></div><div className="rw-preview-selection"><strong>{selectedEvent?.assetName ?? (english ? "No selection" : "선택 없음")}</strong><span>{selectedEvent ? probability(selectedEvent.failureProbability) : "—"}</span></div><div className="rw-preview-workflow"><span>{selectedEvent ? decisionLabel(selectedEvent.recommendedDecision, english) : "—"}</span></div><button type="button" onClick={() => setFlowOpen((value) => !value)}>{flowOpen ? "Flow ↓" : "Flow ↑"}</button></div>
      </footer>
    </main>
  );
}

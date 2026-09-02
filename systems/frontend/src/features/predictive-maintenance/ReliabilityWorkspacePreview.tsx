import {
  Activity,
  ChevronsLeft,
  ChevronsRight,
  Focus,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Search,
  Settings2,
  UserRound,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  createOperationsAgentReviewSummary,
  getOperationsAgentReviewPacket,
  getOperationsAgentReviewSummary,
  runAgentQuery,
} from "../../api";
import type { AuthUser } from "../../types";
import { displayPreset, useDisplayPreferences } from "../../ui/foundry/displayPreferences";
import { useI18n } from "../../ui/i18n/I18nProvider";
import type {
  OperationsClosedLoopLifecycleStep,
  OperationsAgentReviewPacket,
  OperationsAgentReviewSummaryResponse,
  OperationsContextModel,
  OperationsEvent,
  OperationsEventDetailModel,
  OperationsView,
} from "../operations/api/operationsContracts";
import { displayAssetName, displayExplanationMethod, displayLineLabel, displaySensorLabel } from "../operations/displayLabels";
import "./reliability-workspace-preview.css";
import { ContextAssistantDrawer } from "./workspace/ContextAssistantDrawer";
import { LifecycleInstrument } from "./workspace/LifecycleInstrument";
import { OperationalFocus } from "./workspace/OperationalFocus";
import {
  groundedReliabilityAssistantAnswer,
  type ReliabilityAssistantContext,
  type ReliabilityAssistantMessage,
} from "./workspace/assistantContext";
import { resolveReliabilityRoleExperience } from "./workspace/roleExperience";
import { reliabilitySurfaces, resolveReliabilitySurface } from "./workspace/roleSurfaces";

const RELIABILITY_THEME_STORAGE_KEY = "ontology-dashboard:reliability-theme";
const RELIABILITY_LOCALE_STORAGE_KEY = "ontology-dashboard:reliability-locale";

function initialReliabilityTheme(): "dark" | "light" {
  return "light";
}

function initialReliabilityLocale(): "ko-KR" | "en-US" {
  const saved = window.localStorage.getItem(RELIABILITY_LOCALE_STORAGE_KEY);
  return saved === "en-US" ? "en-US" : "ko-KR";
}

function probability(value: number | null) {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

const LIFECYCLE_LABELS: Record<OperationsClosedLoopLifecycleStep, [string, string]> = {
  prediction: ["예측", "Prediction"],
  evidence: ["근거 확인", "Evidence review"],
  decision: ["운영 판단", "Decision"],
  inspection_requested: ["점검 요청", "Inspection requested"],
  inspection_approved: ["점검 승인", "Inspection approved"],
  inspection_in_progress: ["점검 중", "Inspection in progress"],
  inspection_completed: ["점검 완료", "Inspection completed"],
  recommendation_proposed: ["정비안 제안", "Recommendation proposed"],
  maintenance_requested: ["정비 요청", "Maintenance requested"],
  maintenance_approved: ["정비 승인", "Maintenance approved"],
  maintenance_in_progress: ["정비 중", "Maintenance in progress"],
  maintenance_completed: ["정비 완료", "Maintenance completed"],
  post_maintenance_observation_pending: ["정비 후 관측 대기", "Post-maintenance observation pending"],
  ready_for_reprediction: ["재예측 가능", "Ready for re-prediction"],
};

function lifecycleLabel(step: OperationsClosedLoopLifecycleStep | null | undefined, english: boolean) {
  if (!step) return null;
  return LIFECYCLE_LABELS[step][english ? 1 : 0];
}

function riskStatusLabel(status: OperationsEvent["status"] | null | undefined, english: boolean) {
  const labels: Record<NonNullable<OperationsEvent["status"]>, [string, string]> = {
    normal: ["정상", "Normal"],
    attention: ["주의", "Attention"],
    warning: ["경고", "Warning"],
    critical: ["고위험", "Critical"],
    data_quality_hold: ["데이터 확인 필요", "Data quality hold"],
  };
  return status ? labels[status][english ? 1 : 0] : (english ? "No selection" : "선택 없음");
}

function riskTone(status: OperationsEvent["status"] | null | undefined) {
  if (status === "critical") return "critical" as const;
  if (status === "warning") return "warning" as const;
  if (status === "attention" || status === "data_quality_hold") return "attention" as const;
  if (status === "normal") return "normal" as const;
  return "neutral" as const;
}

function recommendedDecisionLabel(value: OperationsEvent["recommendedDecision"] | null | undefined, english: boolean) {
  if (!value) return null;
  const labels: Record<OperationsEvent["recommendedDecision"], [string, string]> = {
    continue_monitoring: ["계속 관찰", "Continue monitoring"],
    request_inspection: ["현장 점검 요청", "Request inspection"],
    review_shutdown: ["정지 검토 요청", "Review shutdown"],
    hold_for_data_check: ["데이터 확인 보류", "Hold for data check"],
  };
  return labels[value][english ? 1 : 0];
}

function operationalImpactLabel(detail: OperationsEventDetailModel | null, english: boolean) {
  const estimatedLostUnits = detail?.operationContext?.eventImpact?.estimatedLostUnits;
  if (typeof estimatedLostUnits === "number") {
    return english
      ? `Estimated ${estimatedLostUnits.toLocaleString()} units at risk`
      : `계획 생산량 약 ${estimatedLostUnits.toLocaleString()}개 영향 추정`;
  }
  const impact = detail?.operationContext?.productionImpact;
  const labels = {
    none: ["현재 생산 영향 없음", "No current production impact"],
    low: ["낮은 생산 영향", "Low production impact"],
    medium: ["중간 생산 영향", "Medium production impact"],
    high: ["높은 생산 영향", "High production impact"],
  } as const;
  return impact ? labels[impact][english ? 1 : 0] : (english ? "Production impact not available" : "생산 영향 미제공");
}

function factorValue(value: number | null, unit: string | null) {
  if (value === null) return null;
  return `${value.toLocaleString()}${unit ? ` ${unit}` : ""}`;
}

function evidenceItemLabel(
  item: OperationsAgentReviewPacket["model_expression_context"]["top_factors"][number],
) {
  const rawValue = item.value === null || item.value === undefined ? null : String(item.value);
  return `${displaySensorLabel(item.feature, item.display_name)}${rawValue ? ` ${rawValue}${item.unit ? ` ${item.unit}` : ""}` : ""}`;
}

function operationalFocusCopy(input: {
  selectedEvent: OperationsEvent | null;
  detail: OperationsEventDetailModel | null;
  lifecycleCurrentLabel: string | null;
  lifecycleNextLabel: string | null;
  primaryActionLabel: string | null;
  roleHeadline: string;
  roleDetail: string;
  english: boolean;
}) {
  if (!input.selectedEvent) {
    return { headline: input.roleHeadline, detail: input.roleDetail };
  }

  const event = input.selectedEvent;
  const eventAssetName = displayAssetName({ assetId: event.assetId, displayName: event.assetName });
  const risk = probability(event.failureProbability);
  const impact = operationalImpactLabel(input.detail, input.english);
  const action = input.primaryActionLabel;
  const current = input.lifecycleCurrentLabel;
  const next = input.lifecycleNextLabel;
  const headline = action
    ? `${eventAssetName} · ${action}`
    : current
      ? `${eventAssetName} · ${current}`
      : `${eventAssetName} · ${riskStatusLabel(event.status, input.english)} ${risk}`;

  const facts = [
    input.english ? `Failure risk ${risk}` : `고장 위험 ${risk}`,
    impact,
    current ? (input.english ? `Current ${current}` : `현재 ${current}`) : null,
    next ? (input.english ? `Next ${next}` : `다음 ${next}`) : null,
    action ? (input.english ? `Action ${action}` : `행동 ${action}`) : null,
  ].filter((value): value is string => Boolean(value));

  return { headline, detail: facts.join(" · ") };
}

export function reliabilityWorkspacePreviewEnabled() {
  const queryEnabled = new URLSearchParams(window.location.search).get("workspace_shell") === "reliability";
  if (queryEnabled) return true;
  const basePath = import.meta.env.BASE_URL.replace(/\/+$/, "");
  const pathname = window.location.pathname;
  if (basePath === "") {
    return /^\/app\/projects\/[^/]+\/operations/.test(pathname);
  }
  const previewBaseEnabled = basePath === "/reliability-preview"
    && (pathname === basePath || pathname.startsWith(`${basePath}/`));
  return previewBaseEnabled;
}

export function ReliabilityWorkspaceLoadingPlaceholder() {
  const locale = initialReliabilityLocale();
  const english = locale === "en-US";

  useEffect(() => {
    document.documentElement.dataset.theme = initialReliabilityTheme();
    document.documentElement.lang = locale;
  }, [locale]);

  return (
    <main
      className="rw-preview-shell rw-preview-loading-placeholder left-open assistant-closed"
      aria-busy="true"
      aria-label={english ? "Reliability workspace loading" : "Reliability workspace 불러오는 중"}
    >
      <header className="rw-preview-topbar">
        <div className="rw-preview-topbar-left">
          <div className="rw-preview-brand"><span><Focus size={14} /></span><strong>Reliability Operations</strong></div>
          <div className="rw-preview-loading-line is-breadcrumb" />
        </div>
        <div className="rw-preview-loading-line is-user" />
      </header>

      <div className="rw-preview-body">
        <aside className="rw-preview-left rw-preview-loading-left" aria-hidden="true">
          <div className="rw-preview-loading-line is-eyebrow" />
          <div className="rw-preview-loading-line is-nav" />
          <div className="rw-preview-loading-line is-nav" />
          <div className="rw-preview-loading-line is-nav" />
          <div className="rw-preview-loading-line is-scope" />
        </aside>

        <section className="rw-preview-main">
          <header className="rw-preview-page-heading">
            <span>{english ? "RELIABILITY OPERATIONS" : "RELIABILITY OPERATIONS"}</span>
            <h1>{english ? "Preparing the operational workspace" : "운영 워크스페이스를 준비하고 있습니다"}</h1>
            <p>{english ? "Connecting risk, evidence, lifecycle, and the next action." : "위험, 근거, lifecycle, 다음 행동을 연결하고 있습니다."}</p>
          </header>

          <div className="rw-preview-loading-content" aria-hidden="true">
            <section className="rw-preview-loading-card is-focus">
              <div className="rw-preview-loading-line is-kicker" />
              <div className="rw-preview-loading-line is-title" />
              <div className="rw-preview-loading-line is-copy" />
              <div className="rw-preview-loading-metrics">
                <span /><span /><span /><span />
              </div>
            </section>
            <section className="rw-preview-loading-card-grid">
              <div className="rw-preview-loading-card"><div className="rw-preview-loading-line is-title" /><div className="rw-preview-loading-line is-copy" /><div className="rw-preview-loading-line is-copy short" /></div>
              <div className="rw-preview-loading-card"><div className="rw-preview-loading-line is-title" /><div className="rw-preview-loading-line is-copy" /><div className="rw-preview-loading-line is-copy short" /></div>
            </section>
          </div>
        </section>
      </div>

      <footer className="rw-preview-bottom" aria-hidden="true">
        <div className="rw-preview-loading-lifecycle">
          <span /><span /><span /><span /><span />
        </div>
      </footer>
    </main>
  );
}

export function ReliabilityWorkspacePreview({
  context,
  activeView,
  activeSurface,
  user,
  selectedEvent,
  detail,
  onNavigate,
  onRefresh,
  refreshing,
  onLogout,
  children,
}: {
  context: OperationsContextModel;
  activeView: OperationsView;
  activeSurface: string | null;
  user: AuthUser;
  selectedEvent: OperationsEvent | null;
  detail: OperationsEventDetailModel | null;
  onNavigate: (surfaceId: string, view: OperationsView) => void;
  onRefresh: () => void;
  refreshing: boolean;
  onLogout: () => void | Promise<void>;
  children: ReactNode;
}) {
  const { setLocale } = useI18n();
  const { preferences, setPreset, setShowTechnicalMetadata } = useDisplayPreferences();
  const [locale, setReliabilityLocaleState] = useState<"ko-KR" | "en-US">(initialReliabilityLocale);
  const english = locale === "en-US";
  const experience = useMemo(() => resolveReliabilityRoleExperience(user), [user]);
  const navigation = useMemo(() => reliabilitySurfaces(experience.kind), [experience.kind]);
  const preset = displayPreset(preferences);
  const activeNav = resolveReliabilitySurface(experience.kind, activeSurface);
  const activePageCopy = activeNav.page;
  const eyebrow = english ? activePageCopy.eyebrow.en : activePageCopy.eyebrow.ko;
  const title = english ? activePageCopy.title.en : activePageCopy.title.ko;
  const detailCopy = english ? activePageCopy.detail.en : activePageCopy.detail.ko;
  const [leftOpen, setLeftOpen] = useState(true);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [messages, setMessages] = useState<ReliabilityAssistantMessage[]>([]);
  const [agentPacket, setAgentPacket] = useState<OperationsAgentReviewPacket | null>(null);
  const [agentSummaryResponse, setAgentSummaryResponse] = useState<OperationsAgentReviewSummaryResponse | null>(null);
  const [assistantLoading, setAssistantLoading] = useState(false);
  const [assistantQueryLoading, setAssistantQueryLoading] = useState(false);
  const [assistantError, setAssistantError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = "light";
    window.localStorage.setItem(RELIABILITY_THEME_STORAGE_KEY, "light");
  }, []);

  useEffect(() => {
    if (experience.kind !== "engineering" && preferences.showTechnicalMetadata) {
      setShowTechnicalMetadata(false);
    }
  }, [experience.kind, preferences.showTechnicalMetadata, setShowTechnicalMetadata]);

  useEffect(() => {
    window.localStorage.setItem(RELIABILITY_LOCALE_STORAGE_KEY, locale);
    setLocale(locale);
  }, [locale, setLocale]);

  useEffect(() => {
    setMessages([]);
    setAgentPacket(null);
    setAgentSummaryResponse(null);
    setAssistantError(null);
  }, [selectedEvent?.eventId]);

  useEffect(() => {
    const assetId = selectedEvent?.assetId;
    if (!assistantOpen || !assetId) return;
    let cancelled = false;
    setAssistantLoading(true);
    setAssistantError(null);

    const request = {
      assetId,
      projectId: context.projectId,
      datasetVersionId: context.datasetVersionId,
      eventId: selectedEvent?.eventId ?? null,
      historyWindow: "24h" as const,
    };

    async function loadGroundedSummary() {
      const cached = await getOperationsAgentReviewSummary(request);
      if (cached.summary) return cached;
      return createOperationsAgentReviewSummary({ ...request, trigger: "ui_manual_regeneration" });
    }

    void Promise.allSettled([
      getOperationsAgentReviewPacket(request),
      loadGroundedSummary(),
    ]).then(([packetResult, summaryResult]) => {
      if (cancelled) return;
      if (packetResult.status === "fulfilled") setAgentPacket(packetResult.value);
      if (summaryResult.status === "fulfilled") setAgentSummaryResponse(summaryResult.value);
      if (packetResult.status === "rejected" && summaryResult.status === "rejected") {
        setAssistantError(english
          ? "Agent Review context is unavailable; using the selected event context only."
          : "Agent Review 문맥을 가져오지 못해 선택 이벤트 문맥만 사용합니다.");
      }
    }).finally(() => {
      if (!cancelled) setAssistantLoading(false);
    });

    return () => { cancelled = true; };
  }, [assistantOpen, context.datasetVersionId, context.projectId, selectedEvent?.assetId, selectedEvent?.eventId]);

  function setReliabilityLocale(nextLocale: "ko-KR" | "en-US") {
    setReliabilityLocaleState(nextLocale);
  }

  const workOrderCount = detail?.closedLoop?.workOrders.length ?? 0;
  const lifecycleSummary = detail?.closedLoop?.lifecycleSummary ?? null;
  const primaryAction = detail?.closedLoop?.primaryAction ?? null;
  const lifecycleCompletedSteps = lifecycleSummary?.completedSteps.map((step) => ({
    id: step,
    label: lifecycleLabel(step, english) ?? step,
  })) ?? [];
  const lifecycleCurrent = lifecycleSummary
    ? {
      id: lifecycleSummary.currentStep,
      label: lifecycleSummary.currentStepLabel || lifecycleLabel(lifecycleSummary.currentStep, english) || lifecycleSummary.currentStep,
    }
    : null;
  const lifecycleNext = lifecycleSummary?.nextStep
    ? { id: lifecycleSummary.nextStep, label: lifecycleLabel(lifecycleSummary.nextStep, english) ?? lifecycleSummary.nextStep }
    : null;
  const lifecycleTimeline = detail?.closedLoop?.timeline.map((item) => ({
    id: item.timelineId,
    label: item.label,
    status: item.status,
    actor: item.actorDisplayName,
    occurredAt: item.occurredAt,
  })) ?? [];
  const evidence = detail?.topFactors.slice(0, 4).map((factor) => ({
    id: factor.id,
    label: displaySensorLabel(factor.feature, factor.label),
    value: factorValue(factor.value, factor.unit),
    detail: displayExplanationMethod(factor.explanationMethod),
  })) ?? [];
  const freshnessObservedAt = detail?.assetDetailStatus?.lastUpdatedAt
    ?? selectedEvent?.observedAt
    ?? context.observedAt
    ?? context.refreshedAt;
  const previewMutationReason = english
    ? "This summary card is read-only. Use the governed action block for approval or field execution."
    : "이 요약 카드는 읽기 전용입니다. 승인·현장 실행은 권한이 적용된 업무 실행 블록에서 수행합니다.";
  const agentSummary = agentSummaryResponse?.summary ?? null;
  const roleSummary = agentSummary?.role_summaries.find((item) => (
    experience.kind === "operations"
      ? item.role === "process_manager"
      : experience.kind === "engineering" || experience.kind === "maintenance"
        ? item.role === "field_operator"
        : false
  ));
  const packetEvidenceItems = agentPacket?.model_expression_context.top_factors.slice(0, 4).map(evidenceItemLabel) ?? [];
  const assistantEvidenceItems = packetEvidenceItems.length
    ? packetEvidenceItems
    : evidence.map((item) => `${item.label}${item.value ? ` ${item.value}` : ""}`);
  const assistantHistoryItems = agentSummary?.history_summary.length
    ? agentSummary.history_summary
    : agentPacket?.review_draft.history_summary ?? [];
  const assistantContext: ReliabilityAssistantContext = {
    roleKind: experience.kind,
    assetId: selectedEvent?.assetId ?? null,
    assetName: selectedEvent?.assetName ?? null,
    eventId: selectedEvent?.eventId ?? null,
    failureProbability: selectedEvent?.failureProbability ?? null,
    statusLabel: riskStatusLabel(selectedEvent?.status, english),
    lineLabel: selectedEvent?.line ?? null,
    operationalImpact: operationalImpactLabel(detail, english),
    recommendedDecisionLabel: recommendedDecisionLabel(selectedEvent?.recommendedDecision, english),
    predictedFailureType: selectedEvent?.predictedFailureType ?? null,
    assignedEngineer: selectedEvent?.assignedEngineer ?? null,
    currentLifecycleLabel: lifecycleCurrent?.label ?? null,
    nextLifecycleLabel: lifecycleNext?.label ?? null,
    primaryActionLabel: primaryAction?.label ?? null,
    evidenceCount: evidence.length,
    evidenceSummary: assistantEvidenceItems.length
      ? assistantEvidenceItems.join(" · ")
      : null,
    workOrderCount,
    maintenanceState: lifecycleCurrent?.label ?? null,
    observedAt: freshnessObservedAt,
    freshnessLabel: freshnessObservedAt ?? null,
    priorityReasons: agentPacket?.review_priority?.reasons ?? [],
    evidenceItems: assistantEvidenceItems,
    historyItems: assistantHistoryItems,
    workHistorySummary: assistantHistoryItems.length ? assistantHistoryItems.join(" · ") : null,
    aiSummary: experience.kind === "executive"
      ? agentSummary?.summary ?? agentPacket?.review_draft.summary ?? null
      : roleSummary?.quote ?? agentSummary?.summary ?? agentPacket?.review_draft.summary ?? null,
    aiSummaryMode: agentSummary?.mode ?? null,
    aiProvider: agentSummaryResponse?.trace.provider ?? null,
    retrievalProvider: agentPacket?.sop_retrieval.provider ?? null,
    retrievalCount: agentPacket?.sop_retrieval.returned_count ?? null,
  };
  const focusCopy = operationalFocusCopy({
    selectedEvent,
    detail,
    lifecycleCurrentLabel: lifecycleCurrent?.label ?? null,
    lifecycleNextLabel: lifecycleNext?.label ?? null,
    primaryActionLabel: primaryAction?.label ?? null,
    roleHeadline: english ? experience.primaryQuestion.en : experience.primaryQuestion.ko,
    roleDetail: english ? experience.operationalFocusHint.en : experience.operationalFocusHint.ko,
    english,
  });
  const showOperationalFocus = new Set([
    "decision-case",
    "production-impact",
    "maintenance-approval",
    "assets",
    "sensor-features",
    "inspection",
    "maintenance-history",
    "work-targets",
  ]).has(activeNav.id);

  async function ask(question: string) {
    const trimmed = question.trim();
    if (!trimmed) return;
    const timestamp = Date.now();
    setMessages((current) => [...current, { id: `user-${timestamp}`, role: "user", text: trimmed }]);
    setAssistantQueryLoading(true);
    setAssistantError(null);

    try {
      const run = await runAgentQuery({
        project_id: context.projectId,
        workspace_id: context.workspaceId,
        question: trimmed,
        route: "auto",
        audience: experience.kind,
        object_type: "equipment",
        object_id: selectedEvent?.assetId ?? undefined,
        event_id: selectedEvent?.eventId ?? undefined,
        top_k: 8,
      });
      const evidenceStores = [...new Set(run.state.evidence.map((item) => item.store))];
      const hasGroundedEvidence = run.state.status === "succeeded" && run.state.evidence.length > 0;
      const answer = hasGroundedEvidence && run.state.answer.trim()
        ? run.state.answer.trim()
        : groundedReliabilityAssistantAnswer(assistantContext, trimmed, locale);
      const hintParts = [
        english ? "Connected evidence" : "연결 근거",
        english ? `${run.state.evidence.length} items` : `${run.state.evidence.length}건`,
        hasGroundedEvidence && evidenceStores.length ? evidenceStores.join(" + ") : null,
        !hasGroundedEvidence ? (english ? "current asset context used" : "현재 설비 문맥 사용") : null,
      ].filter((value): value is string => Boolean(value));
      setMessages((current) => [...current, {
        id: `assistant-${timestamp}`,
        role: "assistant",
        text: answer,
        contextHint: hintParts.join(" · "),
      }]);
      if (!hasGroundedEvidence) {
        setAssistantError(english
          ? "No additional review evidence matched this question. The answer uses the currently selected asset context."
          : "추가 검토 근거가 일치하지 않아 현재 선택 설비의 연결 데이터를 기준으로 답변했습니다.");
      }
    } catch (reason) {
      const fallback = groundedReliabilityAssistantAnswer(assistantContext, trimmed, locale);
      setMessages((current) => [...current, {
        id: `assistant-${timestamp}`,
        role: "assistant",
        text: fallback,
        contextHint: english ? "Current asset context" : "현재 설비 문맥",
      }]);
      setAssistantError(reason instanceof Error
        ? (english ? "Additional evidence lookup was unavailable, so the current asset context was used." : "추가 근거 조회가 지연되어 현재 선택 설비의 연결 데이터를 기준으로 답변했습니다.")
        : (english ? "The current asset context was used for this answer." : "현재 선택 설비의 연결 데이터를 기준으로 답변했습니다."));
    } finally {
      setAssistantQueryLoading(false);
    }
  }

  return (
    <main className={`rw-preview-shell role-${experience.kind} ${leftOpen ? "left-open" : "left-collapsed"} ${assistantOpen ? "assistant-open" : "assistant-closed"}`} data-primary-surface={experience.primarySurface}>
      <header className="rw-preview-topbar">
        <div className="rw-preview-topbar-left">
          <button type="button" className="rw-preview-icon-button" onClick={() => setLeftOpen((value) => !value)} aria-label={leftOpen ? "Collapse navigation" : "Open navigation"}>{leftOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}</button>
          <div className="rw-preview-brand"><span><Activity size={15} /></span><strong>Reliability Operations</strong></div>
          <div className="rw-preview-breadcrumb"><span>{context.projectName}</span><i>/</i><strong>{english ? activeNav.label.en : activeNav.label.ko}</strong></div>
        </div>
        <div className="rw-preview-topbar-right">
          <button type="button" className="rw-preview-search"><Search size={14} /><span>{english ? "Search" : "검색"}</span><kbd>⌘K</kbd></button>
          <button type="button" className={`rw-preview-assistant-toggle ${assistantOpen ? "is-active" : ""}`} onClick={() => setAssistantOpen((value) => !value)}>{assistantOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}<span>Assistant</span></button>
          <div className="rw-preview-user"><span><UserRound size={13} /></span><div><strong>{user.display_name}</strong><small>{english ? experience.label.en : experience.label.ko}</small></div></div>
        </div>
      </header>

      <div className="rw-preview-body">
        <aside className="rw-preview-left">
          <div className="rw-preview-left-heading"><span>{english ? experience.label.en : experience.label.ko}</span><strong>{english ? "Workspace" : "업무 공간"}</strong></div>
          <nav>
            {navigation.map((item, index) => (
              <button type="button" key={item.id} className={activeNav.id === item.id ? "is-active" : ""} onClick={() => onNavigate(item.id, item.view)} title={!leftOpen ? (english ? item.label.en : item.label.ko) : undefined}>
                <span>{String(index + 1).padStart(2, "0")}</span>
                <div><strong>{english ? item.label.en : item.label.ko}</strong><small>{english ? item.detail.en : item.detail.ko}</small></div>
              </button>
            ))}
          </nav>
          <section className="rw-preview-scope"><span>{english ? "SCOPE" : "현재 범위"}</span><strong>{context.workspaceName}</strong><small>{context.sourceStatus}</small></section>
          <section className={`rw-preview-settings ${settingsOpen ? "is-open" : ""}`}>
            <button type="button" className="rw-preview-settings-trigger" onClick={() => { if (!leftOpen) setLeftOpen(true); setSettingsOpen((value) => !value); }}><Settings2 size={14} /><span>{english ? "Settings" : "환경설정"}</span></button>
            {settingsOpen && leftOpen ? <div className="rw-preview-settings-panel">
              <header><strong>{english ? "Workspace settings" : "사용자 환경"}</strong><small>{user.display_name}</small></header>
              <div className="rw-preview-settings-group"><span>{english ? "Language" : "언어"}</span><div className="rw-preview-segmented two"><button type="button" className={!english ? "is-active" : ""} onClick={() => setReliabilityLocale("ko-KR")}>한국어</button><button type="button" className={english ? "is-active" : ""} onClick={() => setReliabilityLocale("en-US")}>English</button></div></div>
              <div className="rw-preview-settings-group"><span>{english ? "Display density" : "화면 밀도"}</span><div className="rw-preview-segmented three">{(["compact", "standard", "accessible"] as const).map((value) => <button type="button" key={value} className={preset === value ? "is-active" : ""} onClick={() => setPreset(value)}>{value === "compact" ? (english ? "Compact" : "조밀") : value === "standard" ? (english ? "Standard" : "기본") : (english ? "Accessible" : "확대")}</button>)}</div></div>
              {experience.kind === "engineering" ? <button type="button" className="rw-preview-settings-action" onClick={() => setShowTechnicalMetadata(!preferences.showTechnicalMetadata)}><span>{english ? "Technical metadata" : "기술 메타데이터"}</span><strong>{preferences.showTechnicalMetadata ? (english ? "Shown" : "표시") : (english ? "Hidden" : "숨김")}</strong></button> : null}
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
          {showOperationalFocus ? <div className="rw-preview-operational-focus">
            <OperationalFocus
              asset={{
                id: selectedEvent?.assetId ?? context.workspaceId,
                name: selectedEvent ? displayAssetName({ assetId: selectedEvent.assetId, displayName: selectedEvent.assetName }) : (english ? "Select an asset" : "설비를 선택하세요"),
                contextLabel: selectedEvent ? displayLineLabel(selectedEvent.line) : context.workspaceName,
              }}
              situation={{
                statusLabel: riskStatusLabel(selectedEvent?.status, english),
                headline: focusCopy.headline,
                detail: focusCopy.detail,
                tone: riskTone(selectedEvent?.status),
                risk: {
                  label: english ? "Failure risk" : "고장 위험",
                  valueLabel: probability(selectedEvent?.failureProbability ?? null),
                },
                operationalImpact: operationalImpactLabel(detail, english),
              }}
              evidence={evidence}
              lifecycle={{
                currentLabel: lifecycleCurrent?.label ?? (english ? "Current step is being confirmed" : "현재 처리 단계 확인 중"),
                nextLabel: lifecycleNext?.label ?? (lifecycleSummary ? (english ? "No next step" : "다음 단계 없음") : null),
                ownerLabel: primaryAction?.ownerLabel ?? null,
              }}
              primaryAction={primaryAction ? {
                label: primaryAction.label,
                ownerLabel: primaryAction.ownerLabel,
                disabled: true,
                disabledReason: primaryAction.disabledReason ?? previewMutationReason,
              } : null}
              freshness={{
                observedAt: freshnessObservedAt,
                label: freshnessObservedAt,
                sourceLabel: null,
              }}
              locale={locale}
            />
          </div> : null}
          <div className="rw-preview-content">{children}</div>
        </section>
      </div>

      <ContextAssistantDrawer
        open={assistantOpen}
        onClose={() => setAssistantOpen(false)}
        context={assistantContext}
        messages={messages}
        onSubmit={ask}
        loading={assistantLoading || assistantQueryLoading}
        submitting={assistantQueryLoading}
        error={assistantError}
        locale={locale}
      />

      <footer className="rw-preview-bottom">
        <LifecycleInstrument
          title={selectedEvent?.assetName ?? (english ? "Lifecycle" : "Lifecycle")}
          completedSteps={lifecycleCompletedSteps}
          current={lifecycleCurrent}
          next={lifecycleNext}
          timeline={lifecycleTimeline}
          locale={locale}
        />
      </footer>
    </main>
  );
}

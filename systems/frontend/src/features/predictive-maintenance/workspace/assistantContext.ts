export type ReliabilityAssistantLocale = "ko-KR" | "en-US";

export interface ReliabilityAssistantContext {
  assetId?: string | null;
  assetName?: string | null;
  eventId?: string | null;
  failureProbability?: number | null;
  currentLifecycleLabel?: string | null;
  nextLifecycleLabel?: string | null;
  primaryActionLabel?: string | null;
  evidenceCount?: number | null;
  evidenceSummary?: string | null;
  workOrderCount?: number | null;
  maintenanceState?: string | null;
  workHistorySummary?: string | null;
  postMaintenanceSummary?: string | null;
  observedAt?: string | null;
  freshnessLabel?: string | null;
}

export interface ReliabilityAssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  contextHint?: string | null;
}

export interface ReliabilityAssistantPrompt {
  id: string;
  label: string;
}

function hasText(value: string | null | undefined): value is string {
  return Boolean(value?.trim());
}

export function hasReliabilityAssistantSelection(context: ReliabilityAssistantContext | null | undefined) {
  return Boolean(context && (hasText(context.assetId) || hasText(context.assetName) || hasText(context.eventId)));
}

export function reliabilityAssistantAssetLabel(
  context: ReliabilityAssistantContext | null | undefined,
  locale: ReliabilityAssistantLocale = "ko-KR",
) {
  if (!context) return locale === "en-US" ? "No selection" : "선택 없음";
  return context.assetName?.trim() || context.assetId?.trim() || context.eventId?.trim()
    || (locale === "en-US" ? "No selection" : "선택 없음");
}

export function reliabilityAssistantRiskLabel(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return `${Math.round(value * 100)}%`;
}

export function reliabilityAssistantPrompts(
  context: ReliabilityAssistantContext | null | undefined,
  locale: ReliabilityAssistantLocale = "ko-KR",
): ReliabilityAssistantPrompt[] {
  if (!hasReliabilityAssistantSelection(context)) return [];

  const english = locale === "en-US";
  const prompts: ReliabilityAssistantPrompt[] = [];

  if (context?.failureProbability !== null && context?.failureProbability !== undefined) {
    prompts.push({
      id: "priority",
      label: english ? "Why is this asset prioritized?" : "왜 이 설비가 우선인가?",
    });
  }
  if ((context?.evidenceCount ?? 0) > 0 || hasText(context?.evidenceSummary)) {
    prompts.push({
      id: "evidence",
      label: english ? "Summarize the supporting evidence" : "현재 핵심 근거 요약",
    });
  }
  if (hasText(context?.currentLifecycleLabel) || hasText(context?.nextLifecycleLabel)) {
    prompts.push({
      id: "lifecycle",
      label: english ? "Explain the current workflow step" : "현재 처리 단계 설명",
    });
  }
  if (hasText(context?.primaryActionLabel)) {
    prompts.push({
      id: "next-action",
      label: english ? "What is my next action?" : "내가 해야 할 다음 행동은?",
    });
  }
  if (hasText(context?.workHistorySummary)) {
    prompts.push({
      id: "work-history",
      label: english ? "Summarize recent work history" : "최근 작업 이력 요약",
    });
  }
  if (hasText(context?.postMaintenanceSummary)) {
    prompts.push({
      id: "post-maintenance",
      label: english ? "Summarize changes after maintenance" : "정비 후 결과 변화 요약",
    });
  }

  return prompts;
}

export function deterministicReliabilityAssistantAnswer(
  context: ReliabilityAssistantContext | null | undefined,
  locale: ReliabilityAssistantLocale = "ko-KR",
) {
  const english = locale === "en-US";
  if (!hasReliabilityAssistantSelection(context)) {
    return english
      ? "Select an asset or event first. This preview only summarizes the operational context currently connected to the workspace."
      : "먼저 설비나 이벤트를 선택하세요. 이 preview는 workspace에 현재 연결된 운영 문맥만 요약합니다.";
  }

  const asset = reliabilityAssistantAssetLabel(context, locale);
  const risk = reliabilityAssistantRiskLabel(context?.failureProbability);
  const facts: string[] = [];

  if (risk) facts.push(english ? `risk ${risk}` : `위험도 ${risk}`);
  if (hasText(context?.currentLifecycleLabel)) {
    facts.push(english ? `current step “${context.currentLifecycleLabel}”` : `현재 단계 “${context.currentLifecycleLabel}”`);
  }
  if (hasText(context?.primaryActionLabel)) {
    facts.push(english ? `primary action “${context.primaryActionLabel}”` : `다음 주요 행동 “${context.primaryActionLabel}”`);
  }
  if ((context?.evidenceCount ?? 0) > 0) {
    facts.push(english ? `${context?.evidenceCount} linked evidence item(s)` : `연결 근거 ${context?.evidenceCount}건`);
  }
  if ((context?.workOrderCount ?? 0) > 0) {
    facts.push(english ? `${context?.workOrderCount} linked work order(s)` : `연결 WorkOrder ${context?.workOrderCount}건`);
  }

  if (!facts.length) {
    return english
      ? `${asset} is selected, but there are no additional connected facts to summarize in this context.`
      : `${asset}이(가) 선택되어 있지만 이 문맥에서 추가로 요약할 연결 정보는 없습니다.`;
  }

  return english
    ? `${asset}: ${facts.join(", ")}. This is a deterministic summary of connected data, not an approval or execution decision.`
    : `${asset}: ${facts.join(", ")}가 확인됩니다. 연결된 데이터를 규칙 기반으로 정리한 내용이며 승인이나 실행 판단이 아닙니다.`;
}

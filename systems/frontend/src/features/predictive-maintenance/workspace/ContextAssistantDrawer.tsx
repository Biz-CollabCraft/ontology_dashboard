import { ChevronRight, PanelRightClose, Send, Sparkles } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  hasReliabilityAssistantSelection,
  reliabilityAssistantAssetLabel,
  reliabilityAssistantPrompts,
  reliabilityAssistantRiskLabel,
  type ReliabilityAssistantContext,
  type ReliabilityAssistantLocale,
  type ReliabilityAssistantMessage,
  type ReliabilityAssistantPrompt,
} from "./assistantContext";
import "./context-assistant.css";

export interface ContextAssistantDrawerProps {
  open?: boolean;
  onClose: () => void;
  context?: ReliabilityAssistantContext | null;
  messages?: ReliabilityAssistantMessage[];
  prompts?: ReliabilityAssistantPrompt[];
  onSubmit?: (question: string) => void;
  locale?: ReliabilityAssistantLocale;
}

export function ContextAssistantDrawer({
  open = false,
  onClose,
  context = null,
  messages = [],
  prompts,
  onSubmit,
  locale = "ko-KR",
}: ContextAssistantDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);
  const [draft, setDraft] = useState("");
  const english = locale === "en-US";
  const selected = hasReliabilityAssistantSelection(context);
  const assetLabel = reliabilityAssistantAssetLabel(context, locale);
  const riskLabel = reliabilityAssistantRiskLabel(context?.failureProbability);
  const suggestedPrompts = useMemo(
    () => prompts ?? reliabilityAssistantPrompts(context, locale),
    [context, locale, prompts],
  );

  useEffect(() => {
    if (!open) return;
    previouslyFocusedRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      onClose();
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocusedRef.current?.focus();
    };
  }, [open, onClose]);

  if (!open) return null;

  function submit(question: string) {
    const trimmed = question.trim();
    if (!trimmed || !onSubmit) return;
    onSubmit(trimmed);
    setDraft("");
  }

  function submitDraft(event: FormEvent) {
    event.preventDefault();
    submit(draft);
  }

  return (
    <aside
      className="rw-context-assistant"
      role="dialog"
      aria-label={english ? "Reliability Assistant" : "Reliability Assistant"}
    >
      <header className="rw-context-assistant__header">
        <div className="rw-context-assistant__identity">
          <span aria-hidden="true"><Sparkles size={15} /></span>
          <div>
            <strong>Reliability Assistant</strong>
            <small>{english ? "Operational context summary" : "운영 문맥 요약"}</small>
          </div>
        </div>
        <button
          ref={closeButtonRef}
          type="button"
          className="rw-context-assistant__close"
          onClick={onClose}
          aria-label={english ? "Close Reliability Assistant" : "Reliability Assistant 닫기"}
        >
          <PanelRightClose size={16} />
        </button>
      </header>

      <section className="rw-context-assistant__context" aria-labelledby="rw-context-assistant-context-title">
        <div className="rw-context-assistant__section-heading">
          <span id="rw-context-assistant-context-title">{english ? "CURRENT CONTEXT" : "현재 문맥"}</span>
          <small>{context?.freshnessLabel ?? context?.observedAt ?? ""}</small>
        </div>
        <strong className="rw-context-assistant__asset">{assetLabel}</strong>
        {!selected ? (
          <p className="rw-context-assistant__empty-context">
            {english ? "Select an asset or event in the workspace to establish context." : "workspace에서 설비나 이벤트를 선택하면 해당 문맥을 기준으로 요약합니다."}
          </p>
        ) : (
          <dl className="rw-context-assistant__facts">
            {context?.assetId ? <div><dt>Asset</dt><dd>{context.assetId}</dd></div> : null}
            {context?.eventId ? <div><dt>Event</dt><dd>{context.eventId}</dd></div> : null}
            {riskLabel ? <div><dt>{english ? "Risk" : "위험도"}</dt><dd>{riskLabel}</dd></div> : null}
            {context?.currentLifecycleLabel ? <div><dt>{english ? "Current step" : "현재 단계"}</dt><dd>{context.currentLifecycleLabel}</dd></div> : null}
            {context?.nextLifecycleLabel ? <div><dt>{english ? "Next step" : "다음 단계"}</dt><dd>{context.nextLifecycleLabel}</dd></div> : null}
            {context?.primaryActionLabel ? <div className="is-action"><dt>{english ? "Primary action" : "다음 행동"}</dt><dd>{context.primaryActionLabel}</dd></div> : null}
            {context?.evidenceCount !== null && context?.evidenceCount !== undefined ? <div><dt>Evidence</dt><dd>{context.evidenceCount}</dd></div> : null}
            {context?.workOrderCount !== null && context?.workOrderCount !== undefined ? <div><dt>WorkOrder</dt><dd>{context.workOrderCount}</dd></div> : null}
            {context?.maintenanceState ? <div><dt>Maintenance</dt><dd>{context.maintenanceState}</dd></div> : null}
          </dl>
        )}
        {context?.evidenceSummary ? <p className="rw-context-assistant__evidence-summary">{context.evidenceSummary}</p> : null}
      </section>

      {suggestedPrompts.length ? (
        <section className="rw-context-assistant__prompts" aria-labelledby="rw-context-assistant-prompts-title">
          <div className="rw-context-assistant__section-heading">
            <span id="rw-context-assistant-prompts-title">{english ? "CONTEXT QUESTIONS" : "문맥 질문"}</span>
          </div>
          <div>
            {suggestedPrompts.map((prompt) => (
              <button type="button" key={prompt.id} onClick={() => submit(prompt.label)} disabled={!onSubmit}>
                <span>{prompt.label}</span><ChevronRight size={13} aria-hidden="true" />
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="rw-context-assistant__thread" aria-label={english ? "Context summary thread" : "문맥 요약 대화"}>
        {messages.length ? messages.map((message) => (
          <article key={message.id} className={`rw-context-assistant__message is-${message.role}`}>
            <span>{message.role === "user" ? (english ? "QUESTION" : "질문") : (english ? "CONNECTED DATA" : "연결 데이터 요약")}</span>
            <p>{message.text}</p>
            {message.contextHint ? <small>{message.contextHint}</small> : null}
          </article>
        )) : (
          <div className="rw-context-assistant__empty-thread">
            <span>{english ? "NO QUESTIONS YET" : "아직 질문 없음"}</span>
            <p>{english ? "Use a context question or enter a question about the selected operational data." : "위 문맥 질문을 선택하거나 현재 선택된 운영 데이터에 대해 질문할 수 있습니다."}</p>
          </div>
        )}
      </section>

      <form className="rw-context-assistant__composer" onSubmit={submitDraft}>
        <label htmlFor="rw-context-assistant-question" className="rw-context-assistant__sr-only">
          {english ? "Ask about the current operational context" : "현재 운영 문맥 질문"}
        </label>
        <textarea
          id="rw-context-assistant-question"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={selected
            ? (english ? "Ask about the selected operational context" : "선택된 운영 문맥에 대해 질문")
            : (english ? "Select an asset or event first" : "먼저 설비나 이벤트를 선택하세요")}
          rows={2}
          disabled={!selected || !onSubmit}
        />
        <button
          type="submit"
          disabled={!selected || !onSubmit || !draft.trim()}
          aria-label={english ? "Submit context question" : "문맥 질문 보내기"}
        >
          <Send size={15} />
        </button>
      </form>

      <footer className="rw-context-assistant__disclaimer">
        {english
          ? "Context-only preview. It summarizes connected operational data and does not approve, execute, or mutate work."
          : "현재 연결된 운영 데이터만 요약하는 context-only preview입니다. 작업을 승인·실행·변경하지 않습니다."}
      </footer>
    </aside>
  );
}

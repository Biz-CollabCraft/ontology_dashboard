import { Calculator, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  calculateMaintenanceCost,
  getMaintenanceActionCandidates,
  getMaintenanceEventLineage,
  type MaintenanceActionCandidateReadModel,
  type MaintenanceActionCode,
  type MaintenanceCostAnalysisRequest,
  type MaintenanceCostAnalysisReadModel,
  type MaintenanceEventLineageReadModel,
  type MaintenanceExecutionTiming,
  type MaintenanceInspectionResultReadModel,
} from "../../../api";
import type { MvpInspectionGuidance } from "../api/mvpContracts";

const TIMING_LABEL: Record<MaintenanceExecutionTiming, string> = {
  immediate: "즉시 정비",
  planned_window: "계획 정비 창",
  reinspect_after: "재점검 후",
  no_action_baseline: "미조치 기준",
};

const ACTION_LABEL: Record<MaintenanceActionCode, string> = {
  TOOL_REPLACEMENT: "공구 교체",
  COOLING_SYSTEM_RESTORE: "냉각 시스템 복구",
};

const DEMO_SOP_BY_ACTION: Partial<
  Record<MaintenanceActionCode, Pick<MvpInspectionGuidance, "sopId" | "version">>
> = {
  TOOL_REPLACEMENT: {
    sopId: "SOP-DEMO-CNC-ROTATING-ASSEMBLY-001",
    version: "demo-2026-08-28",
  },
  COOLING_SYSTEM_RESTORE: {
    sopId: "SOP-DEMO-CNC-ROTATING-ASSEMBLY-001",
    version: "demo-2026-08-28",
  },
};

const CONFIDENCE_LABEL = {
  high: "높음",
  medium: "보통",
  low: "낮음",
  insufficient: "근거 부족",
} as const;

export function latestEligibleInspection(
  lineage: MaintenanceEventLineageReadModel | null,
): MaintenanceInspectionResultReadModel | null {
  if (!lineage) return null;
  const latestInspectionWorkOrder = lineage.work_orders
    .filter((item) => item.work_type === "inspection")
    .at(-1);
  if (!latestInspectionWorkOrder || latestInspectionWorkOrder.status !== "completed") {
    return null;
  }
  const latestResult = [...lineage.inspection_results]
    .filter((item) => item.work_order_id === latestInspectionWorkOrder.work_order_id)
    .sort((left, right) => right.recorded_at.localeCompare(left.recorded_at))[0] ?? null;
  return latestResult?.outcome === "maintenance_recommended" ? latestResult : null;
}

export function isCostAnalysisStageOpen(
  lineage: MaintenanceEventLineageReadModel | null,
  inspection: MaintenanceInspectionResultReadModel | null,
): boolean {
  if (!lineage || !inspection) return false;
  const recommendationCreated = lineage.recommendations.some((item) => (
    item.source_inspection_reference === inspection.inspection_result_id
    || item.source_inspection_work_order_id === inspection.work_order_id
  ));
  const maintenanceStarted = lineage.work_orders.some((item) => item.work_type === "maintenance")
    || Boolean(lineage.maintenance_actions?.length)
    || Boolean(lineage.maintenance_events?.length);
  return !recommendationCreated && !maintenanceStarted;
}

export function latestCostAnalysisForInspection(
  analyses: MaintenanceCostAnalysisReadModel[],
  inspection: MaintenanceInspectionResultReadModel | null,
  actionCode?: MaintenanceActionCode | null,
): MaintenanceCostAnalysisReadModel | null {
  if (!inspection) return null;
  return analyses
    .filter((analysis) => (
      analysis.based_on.inspection_work_order_id === inspection.work_order_id
      && analysis.based_on.inspection_result_id === inspection.inspection_result_id
      && (
        !actionCode
        || analysis.options.some((option) => option.action_code === actionCode)
      )
    ))
    .sort((left, right) => right.calculated_at.localeCompare(left.calculated_at))[0] ?? null;
}

export function costOptionsForDisplay(
  analysis: MaintenanceCostAnalysisReadModel,
  actionCode: MaintenanceActionCode | null,
): MaintenanceCostAnalysisReadModel["options"] {
  if (actionCode === "COOLING_SYSTEM_RESTORE") {
    return analysis.options.filter((option) => option.execution_timing === "immediate");
  }
  if (actionCode === "TOOL_REPLACEMENT") {
    return analysis.options.filter((option) => option.execution_timing !== "reinspect_after");
  }
  return [];
}

export function buildCostRequest(
  guidance: Pick<MvpInspectionGuidance, "sopId" | "version">,
  actionCode: MaintenanceActionCode = "TOOL_REPLACEMENT",
): MaintenanceCostAnalysisRequest {
  return {
    action_code: actionCode,
    sop_id: guidance.sopId,
    sop_version: guidance.version,
  };
}

export function resolveCostAnalysisSopReference(
  guidance: Pick<MvpInspectionGuidance, "sopId" | "version"> | null,
  actionCode: MaintenanceActionCode | null,
): Pick<MvpInspectionGuidance, "sopId" | "version"> | null {
  if (guidance?.sopId.trim() && guidance.version.trim()) {
    return {
      sopId: guidance.sopId.trim(),
      version: guidance.version.trim(),
    };
  }
  return actionCode ? DEMO_SOP_BY_ACTION[actionCode] ?? null : null;
}

function requestKey(prefix: string): string {
  const suffix = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${suffix}`;
}

function formatWon(value: number | null | undefined): string {
  return value === null || value === undefined ? "산정 불가" : `${value.toLocaleString()}원`;
}

export function MaintenanceCostDecisionPanel({
  projectId,
  workspaceId,
  eventId,
  guidance,
  onChanged,
  onEligibilityChanged,
}: {
  projectId: string;
  workspaceId: string;
  eventId: string;
  guidance: MvpInspectionGuidance | null;
  onChanged?: () => void;
  onEligibilityChanged?: (eligible: boolean) => void;
}) {
  const [lineage, setLineage] = useState<MaintenanceEventLineageReadModel | null>(null);
  const [actionCandidates, setActionCandidates] = useState<MaintenanceActionCandidateReadModel[]>([]);
  const [selectedActionCode, setSelectedActionCode] = useState<MaintenanceActionCode | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const nextLineage = await getMaintenanceEventLineage(
        projectId,
        workspaceId,
        eventId,
        signal,
      );
      setLineage(nextLineage);
      const nextInspection = latestEligibleInspection(nextLineage);
      const nextStageOpen = isCostAnalysisStageOpen(nextLineage, nextInspection);
      onEligibilityChanged?.(nextStageOpen);
      if (nextInspection && nextStageOpen) {
        const candidates = await getMaintenanceActionCandidates(
          projectId,
          workspaceId,
          nextInspection.inspection_result_id,
          signal,
        );
        setActionCandidates(candidates.items);
        setSelectedActionCode((currentAction) => (
          currentAction && candidates.items.some(
            (candidate) => candidate.action_code === currentAction
          )
            ? currentAction
            : candidates.items[0]?.action_code ?? null
        ));
      } else {
        setActionCandidates([]);
        setSelectedActionCode(null);
      }
    } catch (caught) {
      if (signal?.aborted) return;
      onEligibilityChanged?.(false);
      setError(caught instanceof Error ? caught.message : "비용 분석 이력을 불러오지 못했습니다.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [projectId, workspaceId, eventId]);

  const inspection = useMemo(() => latestEligibleInspection(lineage), [lineage]);
  const stageOpen = useMemo(
    () => isCostAnalysisStageOpen(lineage, inspection),
    [inspection, lineage],
  );
  const analyses = useMemo(() => [...(lineage?.cost_analyses ?? [])]
    .sort((left, right) => right.calculated_at.localeCompare(left.calculated_at)), [lineage]);
  const current = useMemo(
    () => latestCostAnalysisForInspection(analyses, inspection, selectedActionCode),
    [analyses, inspection, selectedActionCode],
  );
  const visibleOptions = useMemo(
    () => current ? costOptionsForDisplay(current, selectedActionCode) : [],
    [current, selectedActionCode],
  );
  const isImmediateCooling = selectedActionCode === "COOLING_SYSTEM_RESTORE";
  const visibleCalculationComplete = visibleOptions.length > 0
    && visibleOptions.every((option) => option.calculation_status === "calculated");
  const sopReference = useMemo(
    () => resolveCostAnalysisSopReference(guidance, selectedActionCode),
    [guidance, selectedActionCode],
  );
  const calculate = async () => {
    if (!inspection || !selectedActionCode) return;
    if (!sopReference) {
      setError("선택한 정비 Action에 연결된 SOP 기준정보가 없습니다.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await calculateMaintenanceCost(
        projectId,
        workspaceId,
        inspection.inspection_result_id,
        buildCostRequest(sopReference, selectedActionCode),
        requestKey("cost-analysis"),
      );
      await load();
      onChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "비용 분석을 실행하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const blocker = actionCandidates.length === 0
    ? "점검 결과에서 실행 가능한 정비 Action 후보가 확인되지 않았습니다."
    : null;
  if (loading || !inspection || !stageOpen) return null;

  return (
    <section className="mvp-maintenance-cost-panel" aria-label="정비 비용 분석">
      <header>
        <Calculator size={14} />
        <div>
          <span>1단계</span>
          <strong>{isImmediateCooling ? "즉시 복구 비용 확인" : "정비 비용 확인"}</strong>
        </div>
        <button type="button" className="mvp-icon-button" onClick={() => void load()} disabled={loading} aria-label="비용 분석 새로고침">
          <RefreshCw size={13} />
        </button>
      </header>
      <p>
        {isImmediateCooling
          ? "점검 결과로 확인된 냉각 복구 후보의 현재 예상 비용을 계산합니다."
          : "점검 결과로 확인된 정비 후보의 예상 비용을 비교합니다."}
      </p>
      {blocker ? <small className="mvp-cost-warning">{blocker}</small> : null}
      {error ? <small className="mvp-cost-error">{error}</small> : null}

      {actionCandidates.length ? (
        <div className="mvp-cost-action-candidates" aria-label="정비 Action 후보">
          <strong>점검 결과</strong>
          {actionCandidates.map((candidate) => (
            <button
              key={candidate.action_candidate_id}
              type="button"
              className={selectedActionCode === candidate.action_code ? "mvp-button" : "mvp-button ghost"}
              onClick={() => {
                setSelectedActionCode(candidate.action_code);
              }}
              disabled={submitting}
            >
              {ACTION_LABEL[candidate.action_code]}
            </button>
          ))}
        </div>
      ) : null}

      {selectedActionCode ? (
        <div className="mvp-cost-inputs">
          {sopReference ? (
            <div className="mvp-cost-sop-summary">
              <span>자동 선택된 참고 SOP</span>
              <strong>{sopReference.sopId}</strong>
              <small>{sopReference.version} · 데모 SOP 기준</small>
            </div>
          ) : (
            <div className="mvp-cost-sop-summary is-missing">
              <span>참고 SOP</span>
              <strong>연결된 기준정보 없음</strong>
              <small>이 Action에 적용할 승인된 SOP를 먼저 연결해야 합니다.</small>
            </div>
          )}
          <div className="mvp-cost-request-row">
            <small>
              {selectedActionCode === "TOOL_REPLACEMENT"
                ? "인서트·노무 기준은 Backend 버전 기준정보를 사용합니다."
                : "냉각 복구 기준은 Backend 버전 기준정보를 사용합니다."}
            </small>
            <button type="button" className="mvp-button" disabled={Boolean(blocker) || !sopReference || loading || submitting} onClick={() => void calculate()}>
            {isImmediateCooling ? "즉시 복구 비용 확인" : "비용 분석 요청"}
            </button>
          </div>
        </div>
      ) : null}

      {current ? (
        <div className="mvp-cost-result">
          <header>
            <strong>
              {isImmediateCooling
                ? "즉시 냉각 복구 예상 비용"
                : `최근 분석 · ${selectedActionCode ? ACTION_LABEL[selectedActionCode] : "정비 Action"}`}
            </strong>
            <span>{visibleCalculationComplete ? "참고 계산 완료" : "입력 부족"}</span>
          </header>
          <small>{new Date(current.calculated_at).toLocaleString()} · {current.price_version}</small>
          <small>데모 참고값 · 실제 사업장 견적·ERP·MES·급여 실적이 아닙니다.</small>
          <div className="mvp-cost-options">
            {visibleOptions.map((option) => {
              const isLowest = !isImmediateCooling
                && option.option_id === current.lowest_calculated_cost_option_id;
              return (
                <article key={option.option_id}>
                  <div>
                    <strong>{ACTION_LABEL[option.action_code]} · {TIMING_LABEL[option.execution_timing]}</strong>
                    {isLowest ? <b>계산상 최저비용</b> : null}
                  </div>
                  <span>{formatWon(option.total_expected_cost?.base_minor)}</span>
                  {option.assumed_execution_at ? (
                    <small>
                      비용 산정 가정 {new Date(option.assumed_execution_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}
                      {option.labor_rate_base_minor_per_minute !== null && option.labor_rate_base_minor_per_minute !== undefined
                        ? ` · ${option.labor_rate_type === "night" ? "야간" : "주간"} ${option.labor_rate_base_minor_per_minute.toLocaleString()}원/분`
                        : ""}
                    </small>
                  ) : null}
                  <small>{option.expected_downtime ? `예상 정지 ${option.expected_downtime.base_minutes}분` : `부족: ${option.missing_inputs.join(", ")}`}</small>
                  <small>신뢰도: {CONFIDENCE_LABEL[option.confidence]}</small>
                </article>
              );
            })}
          </div>
          <p>
            {isImmediateCooling
              ? "냉각 전용 미래 위험 데이터가 없어 계획·미조치 비용은 표시하지 않습니다. 이 예상 비용은 정비 추천·승인·WorkOrder·실행을 생성하지 않는 참고 정보입니다."
              : "최저비용 표시는 현재 가정의 계산 참고값일 뿐입니다. 비용 분석은 정비 추천·승인·WorkOrder·실행을 생성하지 않습니다."}
          </p>
        </div>
      ) : null}
    </section>
  );
}

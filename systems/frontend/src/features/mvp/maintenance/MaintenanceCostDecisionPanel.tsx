import { Calculator, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  calculateMaintenanceCost,
  createRecommendationFromCostOption,
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

const TIMINGS: MaintenanceExecutionTiming[] = [
  "immediate",
  "planned_window",
  "reinspect_after",
  "no_action_baseline",
];

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

const COST_FIELDS = [
  ["partsCost", "부품비"],
  ["laborDuration", "작업시간(분)"],
  ["laborRate", "분당 인건비"],
  ["externalCost", "외주비"],
  ["downtime", "정지시간(분)"],
  ["productionLossRate", "분당 생산손실"],
  ["failureLoss", "예상 고장손실"],
] as const;

type CostField = (typeof COST_FIELDS)[number][0];
type ScenarioValues = Record<CostField, string>;
type ScenarioForm = Record<MaintenanceExecutionTiming, ScenarioValues>;

function emptyScenario(): ScenarioValues {
  return {
    partsCost: "",
    laborDuration: "",
    laborRate: "",
    externalCost: "",
    downtime: "",
    productionLossRate: "",
    failureLoss: "",
  };
}

function emptyForm(): ScenarioForm {
  return Object.fromEntries(
    TIMINGS.map((timing) => [timing, emptyScenario()]),
  ) as ScenarioForm;
}

function numericValue(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? Math.round(parsed) : null;
}

function money(value: string) {
  const parsed = numericValue(value);
  return parsed === null
    ? null
    : { low_minor: parsed, base_minor: parsed, high_minor: parsed };
}

function duration(value: string) {
  const parsed = numericValue(value);
  return parsed === null
    ? null
    : { low_minutes: parsed, base_minutes: parsed, high_minutes: parsed };
}

function rate(value: string) {
  const parsed = numericValue(value);
  return parsed === null
    ? null
    : {
      low_minor_per_minute: parsed,
      base_minor_per_minute: parsed,
      high_minor_per_minute: parsed,
    };
}

export function latestEligibleInspection(
  lineage: MaintenanceEventLineageReadModel | null,
): MaintenanceInspectionResultReadModel | null {
  if (!lineage) return null;
  const completedWorkOrders = new Set(
    lineage.work_orders
      .filter((item) => item.work_type === "inspection" && item.status === "completed")
      .map((item) => item.work_order_id),
  );
  return [...lineage.inspection_results]
    .filter((item) => (
      item.outcome === "maintenance_recommended"
      && completedWorkOrders.has(item.work_order_id)
    ))
    .sort((left, right) => right.recorded_at.localeCompare(left.recorded_at))[0] ?? null;
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

export function buildCostRequest(
  form: ScenarioForm,
  guidance: Pick<MvpInspectionGuidance, "sopId" | "version">,
  eventId: string,
  actionCode: MaintenanceActionCode = "TOOL_REPLACEMENT",
): MaintenanceCostAnalysisRequest {
  if (actionCode === "TOOL_REPLACEMENT") {
    return {
      action_code: actionCode,
      sop_id: guidance.sopId,
      sop_version: guidance.version,
    };
  }
  return {
    action_code: actionCode,
    sop_id: guidance.sopId,
    sop_version: guidance.version,
    currency: "KRW",
    currency_minor_unit: 0,
    scenarios: TIMINGS.map((execution_timing) => {
      const values = form[execution_timing];
      return {
        execution_timing,
        parts_cost: money(values.partsCost),
        labor_duration: duration(values.laborDuration),
        labor_rate_per_minute: rate(values.laborRate),
        external_service_cost: money(values.externalCost),
        expected_downtime: duration(values.downtime),
        production_loss_rate_per_minute: rate(values.productionLossRate),
        expected_failure_loss: money(values.failureLoss),
        confidence: "medium" as const,
      };
    }),
    assumptions: [
      "사용자가 입력한 기준값을 민감도 low/base/high의 동일값으로 사용",
      "빈 입력은 임의 추정하지 않고 insufficient로 처리",
      "비용 분석은 의사결정 참고값이며 추천·승인·실행 명령이 아님",
    ],
    input_sources: [{
      input_name: "product_ui_cost_inputs",
      source_kind: "assumption",
      source_reference: `maintenance-product-ui:event:${eventId}`,
      confidence: "medium",
    }],
    price_version: `user-input-${new Date().toISOString().slice(0, 10)}`,
    calculation_policy_version: "maintenance-cost-policy-v1",
  };
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
}: {
  projectId: string;
  workspaceId: string;
  eventId: string;
  guidance: MvpInspectionGuidance | null;
  onChanged?: () => void;
}) {
  const [lineage, setLineage] = useState<MaintenanceEventLineageReadModel | null>(null);
  const [actionCandidates, setActionCandidates] = useState<MaintenanceActionCandidateReadModel[]>([]);
  const [selectedActionCode, setSelectedActionCode] = useState<MaintenanceActionCode | null>(null);
  const [form, setForm] = useState<ScenarioForm>(() => emptyForm());
  const [formOpen, setFormOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [basis, setBasis] = useState("");
  const [sopId, setSopId] = useState(guidance?.sopId ?? "");
  const [sopVersion, setSopVersion] = useState(guidance?.version ?? "");
  const [selectedMessage, setSelectedMessage] = useState<string | null>(null);

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
      if (nextInspection) {
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

  useEffect(() => {
    if (guidance?.sopId) setSopId(guidance.sopId);
    if (guidance?.version) setSopVersion(guidance.version);
  }, [guidance?.sopId, guidance?.version]);

  const inspection = useMemo(() => latestEligibleInspection(lineage), [lineage]);
  const analyses = useMemo(() => [...(lineage?.cost_analyses ?? [])]
    .sort((left, right) => right.calculated_at.localeCompare(left.calculated_at)), [lineage]);
  const current = useMemo(
    () => latestCostAnalysisForInspection(analyses, inspection, selectedActionCode),
    [analyses, inspection, selectedActionCode],
  );
  const selectedRecommendationsByAction = useMemo(() => new Map(
    (lineage?.recommendations ?? [])
      .filter((item) => (
        inspection
        && item.source_inspection_work_order_id === inspection.work_order_id
        && item.source_inspection_reference === inspection.inspection_result_id
        && Boolean(item.action_code)
      ))
      .map((item) => [item.action_code as string, item]),
  ), [inspection, lineage]);

  const update = (timing: MaintenanceExecutionTiming, field: CostField, value: string) => {
    setForm((currentForm) => ({
      ...currentForm,
      [timing]: { ...currentForm[timing], [field]: value },
    }));
  };

  const calculate = async () => {
    if (!inspection || !selectedActionCode) return;
    if (!sopId.trim() || !sopVersion.trim()) {
      setError("점검에 참고한 SOP ID와 버전을 입력해 주세요.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setSelectedMessage(null);
    try {
      await calculateMaintenanceCost(
        projectId,
        workspaceId,
        inspection.inspection_result_id,
        buildCostRequest(
          form,
          { sopId: sopId.trim(), version: sopVersion.trim() },
          eventId,
          selectedActionCode,
        ),
        requestKey("cost-analysis"),
      );
      setFormOpen(false);
      await load();
      onChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "비용 분석을 실행하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const selectOption = async (analysisId: string, optionId: string) => {
    if (!basis.trim()) {
      setError("선택 근거를 입력해 주세요.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createRecommendationFromCostOption(
        projectId,
        workspaceId,
        analysisId,
        optionId,
        [basis.trim()],
        requestKey("cost-option-selection"),
      );
      setSelectedMessage(
        `${created.recommendation_id}가 제안 상태로 생성되었습니다. 별도 승인 전에는 WorkOrder가 생성되지 않습니다.`,
      );
      await load();
      onChanged?.();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "비용 옵션을 선택하지 못했습니다.");
    } finally {
      setSubmitting(false);
    }
  };

  const blocker = !inspection
    ? "완료된 점검 결과에서 정비 필요가 확인된 뒤 사용할 수 있습니다."
    : actionCandidates.length === 0
      ? "점검 결과에서 실행 가능한 정비 Action 후보가 확인되지 않았습니다."
    : !sopId.trim() || !sopVersion.trim()
      ? "점검에 참고한 SOP 기준정보가 필요합니다."
    : null;
  const usesServerCostBasis = selectedActionCode === "TOOL_REPLACEMENT";

  return (
    <section className="mvp-maintenance-cost-panel" aria-label="정비 비용 분석">
      <header>
        <Calculator size={14} />
        <strong>정비 비용 분석</strong>
        <button type="button" className="mvp-icon-button" onClick={() => void load()} disabled={loading} aria-label="비용 분석 새로고침">
          <RefreshCw size={13} />
        </button>
      </header>
      <p>점검 결과에서 확인된 정비 Action 후보의 비용만 비교합니다. 버튼을 누르기 전에는 분석하지 않습니다.</p>
      {loading ? <small>점검·비용 lineage를 불러오는 중입니다.</small> : null}
      {blocker ? <small className="mvp-cost-warning">{blocker}</small> : null}
      {error ? <small className="mvp-cost-error">{error}</small> : null}

      {actionCandidates.length ? (
        <div className="mvp-cost-action-candidates" aria-label="정비 Action 후보">
          <strong>정비 Action 후보</strong>
          {actionCandidates.map((candidate) => (
            <button
              key={candidate.action_candidate_id}
              type="button"
              className={selectedActionCode === candidate.action_code ? "mvp-button" : "mvp-button ghost"}
              onClick={() => {
                setSelectedActionCode(candidate.action_code);
                setFormOpen(false);
                setSelectedMessage(null);
              }}
              disabled={submitting}
            >
              {ACTION_LABEL[candidate.action_code]}
            </button>
          ))}
        </div>
      ) : null}

      {usesServerCostBasis ? (
        <div className="mvp-cost-inputs">
          <p>인서트 1개 비용과 노무 기준은 Backend의 버전 관리 기준정보를 사용합니다. 즉시·12시간 후 실행 시각에 따라 주간 또는 야간 요율이 자동 선택됩니다.</p>
          <small>참고 SOP: {sopId || "-"} · {sopVersion || "-"}</small>
          <button type="button" className="mvp-button" disabled={Boolean(blocker) || loading || submitting} onClick={() => void calculate()}>
            비용 분석 요청
          </button>
        </div>
      ) : !formOpen ? (
        <button type="button" className="mvp-button" disabled={Boolean(blocker) || loading || submitting} onClick={() => setFormOpen(true)}>
          냉각계통 비용 분석 입력
        </button>
      ) : (
        <div className="mvp-cost-inputs">
          <p>금액은 원, 시간은 분 단위입니다. 빈 값은 임의 추정하지 않고 insufficient로 처리됩니다.</p>
          <div className="mvp-cost-sop-reference">
            <label>
              <span>참고한 SOP ID</span>
              <input value={sopId} onChange={(event) => setSopId(event.target.value)} />
            </label>
            <label>
              <span>SOP 버전</span>
              <input value={sopVersion} onChange={(event) => setSopVersion(event.target.value)} />
            </label>
          </div>
          {TIMINGS.map((timing) => (
            <fieldset key={timing}>
              <legend>{TIMING_LABEL[timing]}</legend>
              <div>
                {COST_FIELDS.map(([field, label]) => (
                  <label key={`${timing}-${field}`}>
                    <span>{label}</span>
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={form[timing][field]}
                      onChange={(event) => update(timing, field, event.target.value)}
                    />
                  </label>
                ))}
              </div>
            </fieldset>
          ))}
          <div className="mvp-cost-controls">
            <button type="button" className="mvp-button ghost" onClick={() => setFormOpen(false)} disabled={submitting}>취소</button>
            <button type="button" className="mvp-button" onClick={() => void calculate()} disabled={submitting}>비용 계산</button>
          </div>
        </div>
      )}

      {current ? (
        <div className="mvp-cost-result">
          <header>
            <strong>최근 분석 · {selectedActionCode ? ACTION_LABEL[selectedActionCode] : "정비 Action"}</strong>
            <span>{current.missing_inputs.length ? "입력 부족" : "계산 완료"}</span>
          </header>
          <small>{new Date(current.calculated_at).toLocaleString()} · {current.price_version}</small>
          <label>
            <span>선택 근거</span>
            <textarea value={basis} onChange={(event) => setBasis(event.target.value)} placeholder="사용자가 이 시점을 선택한 이유" />
          </label>
          <div className="mvp-cost-options">
            {current.options.map((option) => {
              const executable = option.calculation_status === "calculated"
                && (option.execution_timing === "immediate" || option.execution_timing === "planned_window");
              const isLowest = option.option_id === current.lowest_calculated_cost_option_id;
              const selectedRecommendation = selectedRecommendationsByAction.get(option.action_code);
              const alreadySelected = selectedRecommendation?.source_cost_option_id === option.option_id;
              const actionAlreadySelected = Boolean(selectedRecommendation);
              return (
                <article key={option.option_id}>
                  <div>
                    <strong>{ACTION_LABEL[option.action_code]} · {TIMING_LABEL[option.execution_timing]}</strong>
                    {isLowest ? <b>계산상 최저비용</b> : null}
                  </div>
                  <span>{formatWon(option.total_expected_cost?.base_minor)}</span>
                  {option.execution_at ? (
                    <small>
                      실행 {new Date(option.execution_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}
                      {option.labor_rate_base_minor_per_minute !== null && option.labor_rate_base_minor_per_minute !== undefined
                        ? ` · ${option.labor_rate_type === "night" ? "야간" : "주간"} ${option.labor_rate_base_minor_per_minute.toLocaleString()}원/분`
                        : ""}
                    </small>
                  ) : null}
                  <small>{option.expected_downtime ? `예상 정지 ${option.expected_downtime.base_minutes}분` : `부족: ${option.missing_inputs.join(", ")}`}</small>
                  <button
                    type="button"
                    className="mvp-button ghost"
                    disabled={!executable || actionAlreadySelected || submitting}
                    onClick={() => void selectOption(current.analysis_id, option.option_id)}
                  >
                    {alreadySelected
                      ? "제안 생성됨"
                      : executable && actionAlreadySelected
                        ? "이미 정비안 선택됨"
                        : "이 시점 선택"}
                  </button>
                </article>
              );
            })}
          </div>
          <p>최저비용 표시는 계산 결과일 뿐 자동 추천이 아닙니다. 선택 시에도 제안만 생성되며 승인·WorkOrder·정비 실행은 별도입니다.</p>
        </div>
      ) : null}
      {selectedMessage ? <small className="mvp-cost-success">{selectedMessage}</small> : null}
    </section>
  );
}

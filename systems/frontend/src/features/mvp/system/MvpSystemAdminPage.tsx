import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  RefreshCw,
  TerminalSquare,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getMvpAgentReviewWorkflowRuns } from "../../../api";
import type {
  MvpAgentReviewWorkflowRun,
  MvpBootstrapModel,
} from "../api/mvpContracts";
import { MvpState, formatTimestamp } from "../components/MvpUi";

type RuntimeStatusFilter = "all" | MvpAgentReviewWorkflowRun["status"];

const STATUS_FILTERS: Array<{ id: RuntimeStatusFilter; label: string }> = [
  { id: "all", label: "전체" },
  { id: "completed", label: "완료" },
  { id: "partial", label: "부분 처리" },
  { id: "failed", label: "실패" },
  { id: "running", label: "진행 중" },
];

const STATUS_LABEL: Record<MvpAgentReviewWorkflowRun["status"], string> = {
  completed: "완료",
  partial: "부분 처리",
  failed: "실패",
  running: "진행 중",
};

function triggerLabel(value: string): string {
  if (value === "watcher" || value === "polling_watcher") return "자동 watcher";
  if (value === "manual_materialization") return "수동 생성";
  if (value === "ui_manual_regeneration") return "UI 재생성";
  return value || "trigger 미기록";
}

function runLine(run: MvpAgentReviewWorkflowRun): string {
  const asset = run.asset_id ?? run.trace.materialization?.asset_id;
  const event = run.event_id ?? run.trace.materialization?.event_id;
  const stage = run.trace.stage ?? "stage 미기록";
  return [
    formatTimestamp(run.updated_at),
    STATUS_LABEL[run.status],
    triggerLabel(run.trigger),
    run.engine,
    typeof asset === "string" ? asset : "asset 미기록",
    typeof event === "string" ? event : "event 미기록",
    run.history_window ?? "window 미기록",
    stage,
  ].join("  |  ");
}

function statusIcon(status: MvpAgentReviewWorkflowRun["status"]) {
  if (status === "completed") return <CheckCircle2 size={15} />;
  if (status === "failed") return <AlertTriangle size={15} />;
  if (status === "running") return <Clock3 size={15} />;
  return <DatabaseZap size={15} />;
}

export function MvpSystemAdminPage({
  model,
  refreshing,
  onRefresh,
}: {
  model: MvpBootstrapModel;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const [runs, setRuns] = useState<MvpAgentReviewWorkflowRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState<RuntimeStatusFilter>("all");
  const [selectedRun, setSelectedRun] = useState<MvpAgentReviewWorkflowRun | null>(null);

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await getMvpAgentReviewWorkflowRuns({
        projectId: model.context.projectId,
        datasetVersionId: model.context.datasetVersionId,
        limit: 100,
      });
      setRuns(response.items);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "AI 런타임 로그를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [model.context.datasetVersionId, model.context.projectId]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const filteredRuns = useMemo(
    () => runs.filter((run) => statusFilter === "all" || run.status === statusFilter),
    [runs, statusFilter],
  );
  const counts = useMemo(() => ({
    completed: runs.filter((run) => run.status === "completed").length,
    partial: runs.filter((run) => run.status === "partial").length,
    failed: runs.filter((run) => run.status === "failed").length,
    running: runs.filter((run) => run.status === "running").length,
  }), [runs]);

  return (
    <div className="mvp-system-admin-page">
      <section className="mvp-system-admin-hero" aria-label="시스템 관리자 로그 개요">
        <div>
          <span><TerminalSquare size={15} /> SYSTEM ADMIN</span>
          <h2>AI 런타임 로그</h2>
          <p>요약 생성, 재사용, fallback, 검증 실패를 project 단위로 조회합니다.</p>
        </div>
        <button
          type="button"
          className="mvp-system-refresh"
          onClick={() => {
            onRefresh();
            void loadRuns();
          }}
          disabled={loading || refreshing}
        >
          <RefreshCw size={15} className={loading || refreshing ? "is-spinning" : ""} />
          새로고침
        </button>
      </section>

      <section className="mvp-system-admin-summary" aria-label="AI 런타임 상태 요약">
        <div><span>전체 실행</span><strong>{runs.length}</strong></div>
        <div><span>완료</span><strong>{counts.completed}</strong></div>
        <div><span>부분 처리</span><strong>{counts.partial}</strong></div>
        <div><span>실패</span><strong>{counts.failed}</strong></div>
        <div><span>진행 중</span><strong>{counts.running}</strong></div>
      </section>

      <section className="mvp-system-terminal" aria-label="AI 런타임 터미널 로그">
        <header>
          <div>
            <TerminalSquare size={15} />
            <strong>agent-review-workflow-runs</strong>
            <span>{model.context.projectId} · {model.context.workspaceId}</span>
          </div>
          <div className="mvp-system-filter" role="tablist" aria-label="로그 상태 필터">
            {STATUS_FILTERS.map((filter) => (
              <button
                type="button"
                key={filter.id}
                role="tab"
                aria-selected={statusFilter === filter.id}
                className={statusFilter === filter.id ? "is-active" : ""}
                onClick={() => setStatusFilter(filter.id)}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </header>

        {loading ? <MvpState kind="loading" title="런타임 로그 조회 중" detail="저장된 workflow run 상태를 읽고 있습니다." /> : null}
        {error ? <MvpState kind="error" title="런타임 로그 조회 실패" detail={error} onRetry={loadRuns} /> : null}
        {!loading && !error && filteredRuns.length ? (
          <div className="mvp-system-log-list">
            {filteredRuns.map((run) => (
              <button
                type="button"
                key={run.workflow_run_id}
                className={`mvp-system-log-line is-${run.status}`}
                onClick={() => setSelectedRun(run)}
              >
                <span>{statusIcon(run.status)}</span>
                <code>{runLine(run)}</code>
              </button>
            ))}
          </div>
        ) : null}
        {!loading && !error && !filteredRuns.length ? (
          <MvpState kind="empty" title="표시할 로그가 없습니다" detail="선택한 상태 필터에 해당하는 AI 런타임 로그가 없습니다." />
        ) : null}
      </section>

      {selectedRun ? (
        <div className="mvp-runtime-detail-layer">
          <button type="button" className="mvp-runtime-detail-scrim" onClick={() => setSelectedRun(null)} aria-label="상세 닫기" />
          <section className="mvp-runtime-detail-dialog" role="dialog" aria-modal="true" aria-label="AI 런타임 로그 상세">
            <header>
              <TerminalSquare size={14} />
              <strong>런타임 로그 상세</strong>
              <button type="button" onClick={() => setSelectedRun(null)}>닫기</button>
            </header>
            <dl>
              <div><dt>실행 ID</dt><dd>{selectedRun.workflow_run_id}</dd></div>
              <div><dt>상태</dt><dd>{STATUS_LABEL[selectedRun.status]}</dd></div>
              <div><dt>trigger</dt><dd>{triggerLabel(selectedRun.trigger)}</dd></div>
              <div><dt>engine</dt><dd>{selectedRun.engine}</dd></div>
              <div><dt>asset</dt><dd>{selectedRun.asset_id ?? "미기록"}</dd></div>
              <div><dt>event</dt><dd>{selectedRun.event_id ?? "미기록"}</dd></div>
              <div><dt>dataset</dt><dd>{selectedRun.dataset_version_id ?? "미기록"}</dd></div>
              <div><dt>window</dt><dd>{selectedRun.history_window ?? "미기록"}</dd></div>
              <div><dt>시작</dt><dd>{formatTimestamp(selectedRun.started_at)}</dd></div>
              <div><dt>완료</dt><dd>{selectedRun.completed_at ? formatTimestamp(selectedRun.completed_at) : "진행 중"}</dd></div>
              <div><dt>source hash</dt><dd>{selectedRun.source_sha256.slice(0, 12)}</dd></div>
              <div><dt>context hash</dt><dd>{selectedRun.context_sha256.slice(0, 12)}</dd></div>
              <div className="is-wide"><dt>summary key</dt><dd>{selectedRun.summary_key}</dd></div>
              <div className="is-wide"><dt>오류</dt><dd>{selectedRun.error_message ? `${selectedRun.error_type ?? "error"}: ${selectedRun.error_message}` : "없음"}</dd></div>
            </dl>
            {selectedRun.trace.validation_errors?.length ? (
              <ul>
                {selectedRun.trace.validation_errors.map((item) => (
                  <li key={`${selectedRun.workflow_run_id}-${item}`}>{item}</li>
                ))}
              </ul>
            ) : null}
            <small>이 화면은 조회 전용입니다. 작업요청 생성, 승인, 재시도 실행은 제공하지 않습니다.</small>
          </section>
        </div>
      ) : null}
    </div>
  );
}

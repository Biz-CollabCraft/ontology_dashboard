import { LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import type { OperationsAsset, OperationsBootstrapModel, OperationsEventDetailModel } from "../api/operationsContracts";
import { loadOperationsEventDetail } from "../api/operationsApi";
import { acceptInspectionWorkOrder, startInspectionWorkOrder, type OpenInspectionWorkOrderReadModel } from "../../../api";

type Persona = "maintenance" | "production";

function pct(value: number | null) {
  return value === null ? "정보 없음" : `${Math.round(value * 100)}%`;
}

function minutes(value: number | null) {
  if (value === null) return "정보 없음";
  const hours = Math.floor(value / 60);
  const rest = Math.round(value % 60);
  return hours ? `${hours}시간 ${rest}분` : `${rest}분`;
}

function statusLabel(asset: OperationsAsset) {
  if (asset.status === "critical" || asset.status === "warning") return "긴급";
  if (asset.status === "attention") return "주의";
  if (asset.status === "data_quality_hold") return "확인 필요";
  return "정상";
}

function tone(asset: OperationsAsset) {
  if (asset.status === "critical" || asset.status === "warning") return "critical";
  if (asset.status === "attention") return "attention";
  if (asset.status === "data_quality_hold") return "hold";
  return "normal";
}

function severity(asset: OperationsAsset) {
  return tone(asset) === "critical" ? 4 : tone(asset) === "attention" ? 3 : tone(asset) === "hold" ? 2 : 1;
}

function seriesPoints(asset: OperationsAsset) {
  const values = asset.riskHistory?.map((point) => point.value) ?? [];
  return values.map((value, index) => `${index / Math.max(1, values.length - 1) * 100},${100 - value * 100}`).join(" ");
}

export function RoleFactoryStandalone({ projectId, workspaceId, persona, model, workOrders, workOrderError, onRefresh, onLogout }: {
  projectId: string;
  workspaceId: string;
  persona: Persona;
  model: OperationsBootstrapModel;
  workOrders: OpenInspectionWorkOrderReadModel[];
  workOrderError: boolean;
  onRefresh: () => void;
  onLogout: () => void | Promise<void>;
}) {
  const [selectedAsset, setSelectedAsset] = useState<OperationsAsset | null>(null);
  const [detail, setDetail] = useState<OperationsEventDetailModel | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [commandBusy, setCommandBusy] = useState<string | null>(null);
  const [commandMessage, setCommandMessage] = useState<string | null>(null);
  const risky = [...model.assets].filter((asset) => asset.status !== "normal").sort((a, b) => severity(b) - severity(a) || (b.failureProbability ?? -1) - (a.failureProbability ?? -1));
  const urgent = risky.filter((asset) => tone(asset) === "critical");
  const impactedLines = new Set(risky.map((asset) => asset.line)).size;
  const title = persona === "maintenance" ? "보전 작업 현황" : "생산 대응 현황";
  const subtitle = persona === "maintenance" ? "점검 요청부터 현장 조치와 결과 회신까지" : "설비 위험을 부족분·납기·정지 일정 판단으로 연결";

  useEffect(() => {
    if (persona !== "production" || !selectedAsset?.eventId) {
      setDetail(null);
      return;
    }
    const selectedEvent = model.events.find((event) => event.eventId === selectedAsset.eventId);
    if (!selectedEvent) return;
    let cancelled = false;
    setDetailLoading(true);
    loadOperationsEventDetail({ projectId, workspaceId, datasetVersionId: model.context.datasetVersionId, event: selectedEvent, role: "process_manager", reportRole: "manager", reportType: "operations-decision", historyWindow: "24h", metrics: model.metrics })
      .then((payload) => { if (!cancelled) setDetail(payload); })
      .catch(() => { if (!cancelled) setDetail(null); })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [model, persona, projectId, selectedAsset, workspaceId]);

  async function advanceWorkOrder(item: OpenInspectionWorkOrderReadModel) {
    if (item.status === "in_progress") return;
    setCommandBusy(item.work_order_id);
    setCommandMessage(null);
    try {
      const input = { projectId, workspaceId, workOrderId: item.work_order_id, idempotencyKey: `${item.work_order_id}:${item.status}:${Date.now()}` };
      if (item.status === "requested") await acceptInspectionWorkOrder(input);
      else await startInspectionWorkOrder(input);
      setCommandMessage(item.status === "requested" ? "요청을 접수했습니다." : "현장 점검을 시작했습니다.");
      onRefresh();
    } catch (reason) {
      setCommandMessage(reason instanceof Error ? reason.message : "처리 명령을 완료하지 못했습니다.");
    } finally {
      setCommandBusy(null);
    }
  }

  return <main className="engineer-lite-board role-factory-board">
    <header className="engineer-factory-header">
      <div><strong>{title}</strong><span>{model.context.workspaceName} · {subtitle}</span></div>
      <div className="engineer-factory-live"><i /><b>실시간 연결</b><span>{model.assets.length}대 기준</span><button type="button" onClick={onRefresh}>↻ 새로고침</button><button type="button" onClick={() => void onLogout()}><LogOut size={14} /> 로그아웃</button></div>
    </header>

    <section className="engineer-factory-kpis">
      {persona === "maintenance" ? <>
        <article><span>접수된 정비 요청</span><strong>{workOrders.length}<small>건</small></strong><p>먼저 접수된 순서로 처리합니다.</p></article>
        <article><span>긴급 설비</span><strong>{urgent.length}<small>대</small></strong><p>현장 안전과 작업 허가를 우선 확인합니다.</p></article>
        <article><span>예상 정지 영향</span><strong>{minutes(model.metrics.estimatedDowntimeMinutes)}</strong><p>현재 위험 설비 기준 합계입니다.</p></article>
      </> : <>
        <article><span>생산 영향 검토 설비</span><strong>{risky.length}<small>대</small></strong><p>주의 이상 설비를 생산계획과 대조합니다.</p></article>
        <article><span>영향 가능 라인</span><strong>{impactedLines}<small>개</small></strong><p>현재 위험 설비가 포함된 라인입니다.</p></article>
        <article><span>예상 정지 영향</span><strong>{minutes(model.metrics.estimatedDowntimeMinutes)}</strong><p>부족분·납기 산정의 입력값입니다.</p></article>
      </>}
    </section>

    <section className="role-factory-grid">
      <section className="engineer-factory-card role-work-queue">
        <header><strong>{persona === "maintenance" ? "보전 요청 큐" : "생산 영향 우선순위"}</strong><span>{persona === "maintenance" ? "먼저 접수된 순" : "위험도 높은 순"}</span></header>
        <div>{persona === "maintenance" ? (
          workOrderError ? <p className="role-empty-state">정비 요청 연결을 확인해 주세요.</p> : workOrders.length ? workOrders.map((item) => <article key={item.work_order_id}><b>{item.equipment_id || item.asset_id}</b><span>{item.assigned_to ? `담당 ${item.assigned_to}` : "담당자 배정 대기"}</span><small>{item.status === "in_progress" ? "점검 중" : item.status === "approved" ? "착수 준비" : "접수 대기"}</small><button type="button" disabled={commandBusy === item.work_order_id || item.status === "in_progress"} onClick={() => void advanceWorkOrder(item)}>{item.status === "requested" ? "요청 접수" : item.status === "approved" ? "현장 점검 시작" : "점검 결과 입력 필요"}</button></article>) : <p className="role-empty-state">현재 정비 요청이 없습니다.</p>
        ) : risky.map((asset) => <button type="button" key={asset.assetId} className={`role-impact-item tone-${tone(asset)}`} onClick={() => setSelectedAsset(asset)}><b>{asset.displayName}</b><span>{asset.line} · {asset.cell}</span><strong>{pct(asset.failureProbability)}</strong><small>{statusLabel(asset)} · {asset.predictedFailureType || "이상 유형 확인 필요"}</small></button>)}</div>
      </section>

      <section className="engineer-factory-card role-primary-work">
        <header><strong>{persona === "maintenance" ? "현장 작업 준비" : "생산 대응 검토"}</strong><span>업무 단계별 확인</span></header>
        {persona === "maintenance" ? <div className="role-step-list">{commandMessage ? <p className="role-command-message">{commandMessage}</p> : null}
          <article><b>1. 요청 접수</b><p>설비, 이상 근거, 요청 시각과 중복 요청 여부를 확인합니다.</p></article>
          <article><b>2. 현장 점검</b><p>안전 절차와 센서·부품 점검 결과를 기록합니다.</p></article>
          <article><b>3. 조치안 협의</b><p>방법, 필요 부품, 예상 정지 시간과 영향 품목을 생산관리자에게 전달합니다.</p></article>
          <article><b>4. 작업 및 회신</b><p>착수 조건 확인 후 작업 결과와 후속 관측 기준을 회신합니다.</p></article>
        </div> : <div className="role-production-review">
          <div><span>일일 생산 계획</span><strong>{detail?.operationContext?.productionPlan ? `${detail.operationContext.productionPlan.plannedUnits.toLocaleString("ko-KR")}개` : "설비를 선택하세요"}</strong><small>{detail?.operationContext?.productionPlan?.planDate ?? "운영 API 기준"}</small></div>
          <div><span>예상 생산 손실</span><strong>{detail?.operationContext?.eventImpact?.estimatedLostUnits != null ? `${detail.operationContext.eventImpact.estimatedLostUnits.toLocaleString("ko-KR")}개` : detailLoading ? "불러오는 중" : "산정 정보 없음"}</strong><small>{detail?.operationContext?.eventImpact?.productVariant ?? "선택 설비 영향 기준"}</small></div>
          <div><span>정지 일정 후보</span><strong>{minutes(model.metrics.estimatedDowntimeMinutes)}</strong><small>보전팀 예상 정지 시간과 협의합니다.</small></div>
          <div><span>대응안</span><strong>대체 생산 · 일정 조정</strong><small>계획 연결 후 수량 기반 비교가 활성화됩니다.</small></div>
        </div>}
      </section>

      <aside className="engineer-factory-card role-next-action">
        <header><strong>다음 행동</strong><span>역할 책임</span></header>
        {persona === "maintenance" ? <><b>착수 조건 확인</b><ul><li>부품과 인력</li><li>작업 허가</li><li>정지 시간 합의</li><li>결과 기록 항목</li></ul><button type="button" disabled>정비 작업 API 연결 필요</button></> : <><b>생산 대응·정지 일정 회신</b><ul><li>부족 수량 확인</li><li>납기 영향 확인</li><li>대체 라인 비교</li><li>정지 가능 시간 회신</li></ul><button type="button" disabled>생산계획 API 연결 필요</button></>}
      </aside>
    </section>
    {persona === "production" && selectedAsset ? <div className="role-impact-overlay" onClick={() => setSelectedAsset(null)}><aside className="role-impact-drawer" onClick={(event) => event.stopPropagation()} aria-label={`${selectedAsset.displayName} 생산 영향 상세`}>
      <header><div><strong>{selectedAsset.displayName}</strong><span>{selectedAsset.assetId} · 생산 영향 검토</span></div><button type="button" onClick={() => setSelectedAsset(null)} aria-label="생산 영향 상세 닫기">×</button></header>
      <div className="role-impact-body">
        <section className="role-impact-chart"><header><div><strong>위험 점수 추세</strong><span>{selectedAsset.line} · {selectedAsset.cell}</span></div><b className={`tone-${tone(selectedAsset)}`}>{pct(selectedAsset.failureProbability)}</b></header><svg viewBox="0 0 100 100" preserveAspectRatio="none"><rect y="0" width="100" height="38" className="risk-zone"/><rect y="38" width="100" height="20" className="attention-zone"/><rect y="58" width="100" height="42" className="normal-zone"/><line x1="0" x2="100" y1="38" y2="38"/><line x1="0" x2="100" y1="58" y2="58"/><polyline points={seriesPoints(selectedAsset)}/></svg><footer><span>이전 관측</span><b>현재 상태 {statusLabel(selectedAsset)}</b><span>현재</span></footer></section>
        <section className="role-impact-summary"><header><strong>생산 영향 요약</strong><span>{detailLoading ? "운영 API 조회 중" : "현재 관측 기준"}</span></header><dl><div><dt>영향 라인</dt><dd>{selectedAsset.line}</dd></div><div><dt>예상 정지</dt><dd>{minutes(selectedAsset.estimatedDowntimeMinutes)}</dd></div><div><dt>설비 중요도</dt><dd>{selectedAsset.criticality ?? "정보 없음"}</dd></div><div><dt>예비 부품</dt><dd>{selectedAsset.sparePartAvailable === true ? "확보" : selectedAsset.sparePartAvailable === false ? "미확보" : "확인 필요"}</dd></div><div><dt>예상 손실 수량</dt><dd>{detail?.operationContext?.eventImpact?.estimatedLostUnits != null ? `${detail.operationContext.eventImpact.estimatedLostUnits.toLocaleString("ko-KR")}개` : "산정 정보 없음"}</dd></div><div><dt>대상 품목</dt><dd>{detail?.operationContext?.eventImpact?.productVariant ?? "연결 정보 없음"}</dd></div></dl></section>
        <section className="role-impact-evidence"><header><strong>판단 근거와 센서 추이</strong><span>위험 기여도 순</span></header><div>{selectedAsset.topFactors.slice(0,4).map((factor) => <article key={factor.id}><div><b>{factor.label || factor.feature}</b><strong>{Math.round(Math.abs(factor.contribution) * 100)}%</strong></div><small>{typeof factor.value === "number" ? `${factor.value.toLocaleString("ko-KR",{maximumFractionDigits:2})}${factor.unit ? ` ${factor.unit}` : ""}` : "관측값 확인 필요"}</small></article>)}</div></section>
      </div>
    </aside></div> : null}
  </main>;
}

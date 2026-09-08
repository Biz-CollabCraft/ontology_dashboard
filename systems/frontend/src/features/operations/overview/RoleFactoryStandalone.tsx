import { LogOut } from "lucide-react";
import { MaintenanceApprovalList } from "./MaintenanceApprovalList";
import "./MaintenanceRequestList.css";
import type { ComponentProps } from "react";
import { ProductionRequestBoard } from "./ProductionRequestBoard";
import { useEffect, useState } from "react";
import type { AssetDetailViewModel, OperationsAsset, OperationsBootstrapModel } from "../api/operationsContracts";
import { loadOperationsAssetDetail } from "../api/operationsApi";
import { type OpenInspectionWorkOrderReadModel } from "../../../api";
import { InspectionWorkOrderEditor } from "./InspectionWorkOrderEditor";
import { OperationsAccountBadge } from "./OperationsAccountBadge";
import { ProductionCoordinationPanel } from "./ProductionCoordinationPanel";
import { displayEquipmentSensorLabel, FAILURE_TYPE_LABELS } from "../displayLabels";

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

function seriesPoints(asset: OperationsAsset, detail?: AssetDetailViewModel | null) {
  const detailValues = detail?.asset.asset_id === asset.assetId
    ? detail.risk_series.map((point) => point.failure_probability)
    : [];
  const assetValues = asset.riskHistory?.map((point) => point.value) ?? [];
  const values = detailValues.length > assetValues.length ? detailValues : assetValues;
  if (values.length === 1) {
    const y = 100 - values[0] * 100;
    return `0,${y} 100,${y}`;
  }
  return values.map((value, index) => `${index / Math.max(1, values.length - 1) * 100},${100 - value * 100}`).join(" ");
}

function sensorPoints(points: Array<{ value: number }>) {
  if (!points.length) return "";
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, Math.abs(max) * 0.08, 1);
  if (values.length === 1) return "0,50 100,50";
  return values.map((value, index) => `${index / (values.length - 1) * 100},${92 - ((value - min) / range) * 84}`).join(" ");
}

function failureLabel(value: string) {
  return FAILURE_TYPE_LABELS[value] ?? (value ? value.replaceAll("_", " ") : "원인 확인 필요");
}

export function RoleFactoryStandalone(props: ComponentProps<typeof RoleFactoryStandaloneLegacy>) {
  return props.persona === "production" ? <ProductionRequestBoard {...props}/> : <RoleFactoryStandaloneLegacy {...props}/>;
}

function RoleFactoryStandaloneLegacy({ projectId, workspaceId, persona, model, workOrders, workOrderError, currentUserId, currentUser, onRefresh, onLogout }: {
  currentUserId: string;
  currentUser: { displayName: string; title: string };
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
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<AssetDetailViewModel | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [selectedWorkOrderId, setSelectedWorkOrderId] = useState<string | null>(null);
  const [coordinationConnection, setCoordinationConnection] = useState<{ workOrderId: string; state: "loading" | "online" | "offline" } | null>(null);
  const selectedWorkOrder = workOrders.find((item) => item.work_order_id === selectedWorkOrderId) ?? workOrders.find((item) => item.assigned_to === currentUserId) ?? workOrders[0];
  const risky = [...model.assets].filter((asset) => asset.status !== "normal").sort((a, b) => severity(b) - severity(a) || (b.failureProbability ?? -1) - (a.failureProbability ?? -1));
  const urgent = risky.filter((asset) => tone(asset) === "critical");
  const impactedLines = new Set(risky.map((asset) => asset.line)).size;
  const title = persona === "maintenance" ? "보전 작업 현황" : "생산 대응 현황";
  const subtitle = persona === "maintenance" ? "점검 요청부터 현장 조치와 결과 회신까지" : "설비 위험을 부족분·납기·정지 일정 판단으로 연결";

  useEffect(() => {
    if (persona !== "production") return;
    setSelectedAsset((current) => {
      if (current) return risky.find((asset) => asset.assetId === current.assetId) ?? risky[0] ?? null;
      return risky[0] ?? null;
    });
  }, [model.assets, persona]);

  useEffect(() => {
    if (persona !== "production" || !selectedAsset?.eventId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    loadOperationsAssetDetail(projectId, workspaceId, selectedAsset.assetId, selectedAsset.eventId, model.context.datasetVersionId, "24h")
      .then((payload) => { if (!cancelled) setDetail(payload); })
      .catch((reason) => { if (!cancelled) { setDetail(null); setDetailError(reason instanceof Error ? reason.message : "생산 영향 정보를 불러오지 못했습니다."); } })
      .finally(() => { if (!cancelled) setDetailLoading(false); });
    return () => { cancelled = true; };
  }, [model.context.datasetVersionId, persona, projectId, selectedAsset?.assetId, selectedAsset?.eventId, workspaceId]);


  return <main className={`engineer-lite-board role-factory-board role-factory-${persona}`}>
    <header className="engineer-factory-header">
      <div><strong>{title}</strong><span>{model.context.workspaceName} · {subtitle}</span></div>
      <div className="engineer-factory-live"><span>{model.assets.length}대 기준</span><OperationsAccountBadge {...currentUser} /><button type="button" onClick={() => void onLogout()}><LogOut size={14} /> 로그아웃</button></div>
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

    {persona === "production" ? <section className="role-production-summary-strip" aria-label="생산 대응 종합 수치">
      <article><span>선택 설비</span><strong>{selectedAsset?.displayName ?? "선택 필요"}</strong></article>
      <article><span>일일 생산 계획</span><strong>{detail?.operation_context.production_plan ? `${detail.operation_context.production_plan.planned_units.toLocaleString("ko-KR")}개` : detailLoading ? "조회 중" : "정보 없음"}</strong></article>
      <article><span>예상 생산 손실</span><strong>{detail?.operation_context.event_impact?.estimated_lost_units != null ? `${detail.operation_context.event_impact.estimated_lost_units.toLocaleString("ko-KR")}개` : detailLoading ? "조회 중" : "정보 없음"}</strong></article>
      <article><span>예상 정지 시간</span><strong>{minutes(selectedAsset?.estimatedDowntimeMinutes ?? model.metrics.estimatedDowntimeMinutes)}</strong></article>
    </section> : null}

    <section className="role-factory-grid">
      <section className="engineer-factory-card role-work-queue">
        <header><strong>{persona === "maintenance" ? "점검 요청 목록" : "생산 영향 우선순위"}</strong><span>{persona === "maintenance" ? "먼저 접수된 순" : "위험도 높은 순"}</span></header>
        <div>{persona === "maintenance" ? (
          workOrderError ? <p className="role-empty-state">정비 요청 연결을 확인해 주세요.</p> : workOrders.length ? workOrders.map((item) => <button className="maintenance-request-item" type="button" key={item.work_order_id} aria-pressed={selectedWorkOrder?.work_order_id === item.work_order_id} onClick={() => setSelectedWorkOrderId(item.work_order_id)}>
            <b>{item.equipment_id || item.asset_id}</b>
            <span className="maintenance-request-owner">담당 {item.assigned_to_display_name || (item.assigned_to ? "담당 보전팀" : "배정 대기")}</span>
            <small>#{item.work_order_id.slice(-8)}</small>
            <span className={`maintenance-request-state state-${item.status}`}>{item.status === "in_progress" ? "점검 중" : item.status === "approved" ? "착수 준비" : "접수 대기"}</span>
          </button>) : <p className="role-empty-state">현재 정비 요청이 없습니다.</p>
        ) : risky.map((asset) => <button type="button" key={asset.assetId} aria-pressed={selectedAsset?.assetId === asset.assetId} className={`role-impact-item tone-${tone(asset)}${selectedAsset?.assetId === asset.assetId ? " is-selected" : ""}`} onClick={() => { setSelectedAsset(asset); setDetailOpen(false); }}><b>{asset.displayName}</b><span>{asset.line}{asset.cell && asset.cell !== asset.line ? ` · ${asset.cell}` : ""}</span><strong>{pct(asset.failureProbability)}</strong><small>{statusLabel(asset)} · {failureLabel(asset.predictedFailureType)}</small></button>)}</div>
      </section>

      <section className="engineer-factory-card role-primary-work">
        <header><strong>{persona === "maintenance" ? "점검 및 정비 처리" : "생산 대응 검토"}</strong><div className="maintenance-work-status"><span>업무 단계별 확인</span>{persona === "maintenance" ? (() => {
          const state = workOrderError ? "offline" : !selectedWorkOrder || selectedWorkOrder.status === "requested" ? "online"
            : coordinationConnection?.workOrderId === selectedWorkOrder.work_order_id ? coordinationConnection.state : "loading";
          return <span role="status" className={`maintenance-connection is-${state}`}><i/>{state === "online" ? "연결 정상" : state === "offline" ? "연결 확인 필요" : "연결 확인 중"}</span>;
        })() : null}</div></header>
        {persona === "maintenance" && selectedWorkOrder ? <InspectionWorkOrderEditor key={selectedWorkOrder.work_order_id} item={selectedWorkOrder} currentUserId={currentUserId} projectId={projectId} workspaceId={workspaceId} onRefresh={onRefresh} onConnectionChange={setCoordinationConnection} /> : persona === "maintenance" ? <div className="role-step-list">
          <article><b>1. 요청 접수</b><p>설비, 이상 근거, 요청 시각과 중복 요청 여부를 확인합니다.</p></article>
          <article><b>2. 현장 점검</b><p>안전 절차와 센서·부품 점검 결과를 기록합니다.</p></article>
          <article><b>3. 조치안 협의</b><p>방법, 필요 부품, 예상 정지 시간과 영향 품목을 생산 관리자에게 전달합니다.</p></article>
          <article><b>4. 작업 및 회신</b><p>착수 조건 확인 후 작업 결과와 후속 관측 기준을 회신합니다.</p></article>
        </div> : selectedAsset ? <div className="role-production-center-stack"><section className="role-production-risk-preview"><header><div><strong>위험 점수 추세 · 최근 관측</strong><span>{selectedAsset.displayName} · {selectedAsset.assetId}</span></div><b className={`tone-${tone(selectedAsset)}`}>{pct(selectedAsset.failureProbability)}</b></header><svg viewBox="0 0 100 100" preserveAspectRatio="none"><rect y="0" width="100" height="38" className="risk-zone"/><rect y="38" width="100" height="20" className="attention-zone"/><rect y="58" width="100" height="42" className="normal-zone"/><line x1="0" x2="100" y1="38" y2="38"/><line x1="0" x2="100" y1="58" y2="58"/><polyline points={seriesPoints(selectedAsset, detail)}/></svg><footer><span>이전 관측</span><b>현재 상태 {statusLabel(selectedAsset)}</b><span>현재</span></footer></section><section className="role-production-result-summary"><header><strong>{selectedAsset.displayName} 현황 요약</strong><span>{detailLoading ? "상세 정보 확인 중" : "현재 관측 기준"}</span></header><p><b>{statusLabel(selectedAsset)}</b> 상태의 설비를 생산 계획과 대조합니다.</p><dl><div><dt>예상 고장 영향</dt><dd>{failureLabel(selectedAsset.predictedFailureType)}</dd></div><div><dt>예상 생산 손실</dt><dd>{detail?.operation_context.event_impact?.estimated_lost_units != null ? `${detail.operation_context.event_impact.estimated_lost_units.toLocaleString("ko-KR")}개` : "정보 없음"}</dd></div><div><dt>예상 정지 시간</dt><dd>{minutes(selectedAsset.estimatedDowntimeMinutes)}</dd></div></dl>{detailError ? <small>상세 영향 연결을 확인해 주세요.</small> : null}</section></div> : <p className="role-empty-state">왼쪽 우선순위에서 설비를 선택하면 위험 점수 추세가 표시됩니다.</p>}
      </section>

      {persona === "maintenance" ? <MaintenanceApprovalList projectId={projectId} workspaceId={workspaceId} workOrders={workOrders} workOrderError={workOrderError} selectedId={selectedWorkOrder?.work_order_id} onSelect={setSelectedWorkOrderId}/> : <aside className="engineer-factory-card role-next-action">
        <header><strong>다음 행동</strong><span>역할 책임</span></header>
        <ProductionCoordinationPanel projectId={projectId} workspaceId={workspaceId} mode="production" /><button type="button" disabled={!selectedAsset} onClick={() => setDetailOpen(true)}>{selectedAsset ? "선택 설비 영향 확인" : "설비를 먼저 선택하세요"}</button>
      </aside>}
    </section>
    {persona === "production" && selectedAsset && detailOpen ? <div className="role-impact-overlay" onClick={() => setDetailOpen(false)}><aside className="role-impact-drawer" onClick={(event) => event.stopPropagation()} aria-label={`${selectedAsset.displayName} 생산 영향 상세`}>
      <header><div><strong>{selectedAsset.displayName}</strong><span>{selectedAsset.assetId} · 생산 영향 검토</span></div><button type="button" onClick={() => setDetailOpen(false)} aria-label="생산 영향 상세 닫기">×</button></header>
      <div className="role-impact-body">
        <section className="role-impact-summary"><header><strong>생산 영향 요약</strong><span>{detailLoading ? "운영 API 조회 중" : detailError ? "연결 정보 없음" : "현재 관측 기준"}</span></header>{detailError ? <p className="role-detail-error">{detailError}</p> : null}<dl><div><dt>일일 생산 계획</dt><dd>{detail?.operation_context.production_plan ? `${detail.operation_context.production_plan.planned_units.toLocaleString("ko-KR")}개` : "정보 없음"}</dd></div><div><dt>예상 손실 수량</dt><dd>{detail?.operation_context.event_impact?.estimated_lost_units != null ? `${detail.operation_context.event_impact.estimated_lost_units.toLocaleString("ko-KR")}개` : "정보 없음"}</dd></div><div><dt>예상 정지 시간</dt><dd>{minutes(selectedAsset.estimatedDowntimeMinutes)}</dd></div><div><dt>대상 품목</dt><dd>{detail?.operation_context.event_impact?.product_variant ?? "정보 없음"}</dd></div></dl></section>
        <section className="role-impact-chart"><header><div><strong>위험 점수 추세</strong><span>{selectedAsset.line}{selectedAsset.cell && selectedAsset.cell !== selectedAsset.line ? ` · ${selectedAsset.cell}` : ""}</span></div><b className={`tone-${tone(selectedAsset)}`}>{pct(selectedAsset.failureProbability)}</b></header><svg viewBox="0 0 100 100" preserveAspectRatio="none"><rect y="0" width="100" height="38" className="risk-zone"/><rect y="38" width="100" height="20" className="attention-zone"/><rect y="58" width="100" height="42" className="normal-zone"/><line x1="0" x2="100" y1="38" y2="38"/><line x1="0" x2="100" y1="58" y2="58"/><polyline points={seriesPoints(selectedAsset, detail)}/></svg><footer><span>이전 관측</span><b>현재 상태 {statusLabel(selectedAsset)}</b><span>현재</span></footer></section>
        <section className="role-impact-evidence"><header><strong>생산 영향 상세 현황</strong><span>현재 설비 관측 기준</span></header><div className="role-financial-summary"><article><span>예상 생산 손실</span><strong>{detail?.operation_context.event_impact?.estimated_lost_units != null ? `${detail.operation_context.event_impact.estimated_lost_units.toLocaleString("ko-KR")}개` : "정보 없음"}</strong></article><article><span>예상 금전 손실</span><strong>산정 기준 미연결</strong><small>품목 단가 계약 필요</small></article></div><section className="role-current-metrics"><header><strong>현 지표</strong><span>위험 기여도 순</span></header><div>{selectedAsset.topFactors.slice(0,4).map((factor) => <article key={factor.id}><span>{displayEquipmentSensorLabel(selectedAsset.assetId, factor.feature, factor.label)}</span><strong>{typeof factor.value === "number" ? `${factor.value.toLocaleString("ko-KR",{maximumFractionDigits:2})}${factor.unit ? ` ${factor.unit}` : ""}` : "확인 필요"}</strong><small>위험 기여 {Math.round(Math.abs(factor.contribution) * 100)}%</small></article>)}</div></section><section className="role-sensor-trends"><header><strong>센서별 자세한 추이</strong><span>{selectedAsset.sensorHistory?.length ?? 0}개 센서</span></header><div>{selectedAsset.sensorHistory?.length ? selectedAsset.sensorHistory.map((sensor) => <article key={sensor.feature}><header><b>{displayEquipmentSensorLabel(selectedAsset.assetId, sensor.feature, sensor.label)}</b><strong>{sensor.points.at(-1)?.value.toLocaleString("ko-KR",{maximumFractionDigits:2})}{sensor.unit ? ` ${sensor.unit}` : ""}</strong></header><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline points={sensorPoints(sensor.points)}/></svg><footer><span>이전</span><span>{sensor.points.length}개 관측</span><span>현재</span></footer></article>) : <p>표시할 센서 관측 이력이 없습니다.</p>}</div></section></section>
      </div>
    </aside></div> : null}
  </main>;
}

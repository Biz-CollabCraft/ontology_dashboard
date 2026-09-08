import { relativeRecordTime } from "../../../standalone/briefFormat.js";
import { NaturalBriefing } from "./NaturalBriefing";
import type {
  OperationsAsset,
  OperationsAgentReviewSummaryResponse,
  OperationsBootstrapModel,
  OperationsRiskStatus,
} from "../api/operationsContracts";
import type { CSSProperties, ReactNode } from "react";
import { useEffect, useState } from "react";
import { LogOut } from "lucide-react";
import { OperationsAccountBadge } from "./OperationsAccountBadge";
import { EngineerRequestProgress } from "./EngineerRequestProgress";
import { orderEngineerSensors } from "./engineerSensorOrder";
import type { OpenInspectionWorkOrderReadModel } from "../../../api";
import { requestInspectionWorkOrder } from "../../../api";
import {
  displayAssetName,
  displayAssetShortName,
  displayEquipmentSensorLabel,
} from "../displayLabels";

const STATUS_LABEL: Record<OperationsRiskStatus, string> = {
  normal: "정상",
  attention: "주의",
  warning: "주의",
  critical: "긴급",
  data_quality_hold: "확인 필요",
};

function formatTimestamp(value: string | null | undefined) {
  if (!value) return "시각 정보 없음";
  return relativeRecordTime(value);
}

function formatProbability(value: number | null | undefined) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "—";
}

function formatMinutes(value: number | null | undefined) {
  if (typeof value !== "number") return "정보 없음";
  const hours = Math.floor(value / 60);
  const minutes = Math.round(value % 60);
  return hours ? `${hours}시간 ${minutes}분` : `${minutes}분`;
}

function compactJobId(value: string) {
  const hash = value.split("-").filter(Boolean).at(-1) ?? value;
  const compact = hash.replace(/[^A-Za-z0-9]/g, "").slice(-8);
  return compact ? `#${compact}` : "#-";
}

function tone(status: OperationsRiskStatus) {
  if (status === "critical") return "critical";
  if (status === "warning" || status === "attention") return "attention";
  if (status === "data_quality_hold") return "hold";
  return "normal";
}

function riskFill(asset: OperationsAsset) {
  const fallback =
    asset.status === "critical"
      ? 0.9
      : asset.status === "warning" || asset.status === "attention"
        ? 0.58
        : asset.status === "data_quality_hold"
          ? 0.68
          : 0.22;
  const probability = Math.max(
    0,
    Math.min(1, asset.failureProbability ?? fallback),
  );
  return `${Math.round(30 + probability * 60)}%`;
}

function sensorPolyline(points: Array<{ value: number }>) {
  if (!points.length) return "";
  const values = points.map((point) => point.value);
  if (values.every((value) => value >= 0 && value <= 1)) {
    return points
      .map(
        (point, index) =>
          `${((index / Math.max(1, points.length - 1)) * 100).toFixed(2)},${(100 - point.value * 100).toFixed(2)}`,
      )
      .join(" ");
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1e-6);
  return points
    .map(
      (point, index) =>
        `${((index / Math.max(1, points.length - 1)) * 100).toFixed(2)},${(92 - ((point.value - min) / span) * 84).toFixed(2)}`,
    )
    .join(" ");
}

function riskPolyline(points: Array<{ value: number }>) {
  return points
    .map(
      (point, index) =>
        `${((index / Math.max(1, points.length - 1)) * 100).toFixed(2)},${(100 - Math.max(0, Math.min(1, point.value)) * 100).toFixed(2)}`,
    )
    .join(" ");
}

function zoneLabel(value: string) {
  const match = value.match(/^S0?(\d+)$/i);
  return match ? `${Number(match[1])}구역` : value;
}

function cellLabel(value: string) {
  const match = value.match(/L0?(\d+)$/i);
  return match ? `${Number(match[1])}셀` : value;
}

function TrendSvg({ points }: { points: string }) {
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <rect y="0" width="100" height="38" className="risk-zone" />
      <rect y="38" width="100" height="20" className="attention-zone" />
      <rect y="58" width="100" height="42" className="normal-zone" />
      <line x1="0" x2="100" y1="38" y2="38" />
      <line x1="0" x2="100" y1="58" y2="58" />
      <polyline points={points} />
    </svg>
  );
}

function DetailedTrendSvg({
  points,
  unit,
}: {
  points: Array<{ observedAt: string; value: number }>;
  unit: string | null;
}) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  if (!points.length)
    return (
      <div className="engineer-expanded-empty">표시할 관측값이 없습니다.</div>
    );
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, Math.abs(max) * 0.05, 1e-6);
  const plotted = points.map((point, index) => ({
    ...point,
    x: 58 + (index / Math.max(1, points.length - 1)) * 714,
    y: 28 + (1 - (point.value - min) / span) * 270,
  }));
  const active = activeIndex === null ? null : plotted[activeIndex];
  const tooltipX = active ? Math.max(8, Math.min(622, active.x - 85)) : 0;
  const tooltipY = active ? Math.max(8, active.y - 70) : 0;
  return (
    <svg
      className="engineer-detailed-trend"
      viewBox="0 0 800 360"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="센서 관측 시각별 상세 추이"
    >
      {[0, 1, 2, 3, 4].map((row) => (
        <line
          key={row}
          x1="58"
          x2="772"
          y1={28 + row * 67.5}
          y2={28 + row * 67.5}
          className="detail-grid"
        />
      ))}
      <text x="50" y="34" textAnchor="end">
        {max.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}
      </text>
      <text x="50" y="302" textAnchor="end">
        {min.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}
      </text>
      <polyline
        points={plotted.map((point) => `${point.x},${point.y}`).join(" ")}
      />
      {plotted.map((point, index) => (
        <circle
          key={`${point.observedAt}-${index}`}
          cx={point.x}
          cy={point.y}
          r={activeIndex === index ? 5 : 3}
          tabIndex={0}
          aria-label={`${formatTimestamp(point.observedAt)}, ${point.value.toLocaleString("ko-KR", { maximumFractionDigits: 2 })}${unit ? ` ${unit}` : ""}`}
          onMouseEnter={() => setActiveIndex(index)}
          onMouseLeave={() => setActiveIndex(null)}
          onFocus={() => setActiveIndex(index)}
          onBlur={() => setActiveIndex(null)}
        />
      ))}
      <text x="58" y="332">
        {formatTimestamp(points[0].observedAt)}
      </text>
      <text x="772" y="332" textAnchor="end">
        {formatTimestamp(points.at(-1)?.observedAt)}
      </text>
      {active ? (
        <g
          className="detail-tooltip"
          transform={`translate(${tooltipX} ${tooltipY})`}
          pointerEvents="none"
        >
          <rect width="170" height="54" rx="5" />
          <text x="10" y="20">
            {formatTimestamp(active.observedAt)}
          </text>
          <text x="10" y="41">
            {active.value.toLocaleString("ko-KR", { maximumFractionDigits: 3 })}
            {unit ? ` ${unit}` : ""}
          </text>
        </g>
      ) : null}
    </svg>
  );
}

function LoadingPanel({
  title,
  className = "",
}: {
  title: string;
  className?: string;
}) {
  return (
    <section
      className={`engineer-factory-card engineer-local-loading ${className}`}
      aria-busy="true"
    >
      <header>
        <strong>{title}</strong>
      </header>
      <div>
        <i />
        <span>데이터 로딩 중</span>
      </div>
    </section>
  );
}

export function EngineerFactoryLoading() {
  return (
    <main
      className="engineer-lite-board engineer-lite-loading"
      aria-label="공장 현황 데이터 로딩 중"
    >
      <header className="engineer-factory-header">
        <div>
          <strong>공장 현황</strong>
          <span>설비 데이터를 연결하고 있습니다</span>
        </div>
        <div className="engineer-factory-live">
          <i />
          <b>연결 확인 중</b>
        </div>
      </header>
      <section className="engineer-factory-kpis">
        <article aria-busy="true">
          <span>즉시 조치 필요 설비</span>
          <strong>—</strong>
          <p>데이터 로딩 중</p>
        </article>
        <article aria-busy="true">
          <span>가동 중 설비</span>
          <strong>—</strong>
          <p>데이터 로딩 중</p>
        </article>
        <article aria-busy="true">
          <span>예상 정지 영향</span>
          <strong>—</strong>
          <p>데이터 로딩 중</p>
        </article>
      </section>
      <section className="engineer-lite-main">
        <LoadingPanel
          title="라인 · 셀 · 설비 상태"
          className="engineer-equipment-list"
        />
        <LoadingPanel
          title="위험 점수 추세 · 최근 12시간"
          className="engineer-risk-trend"
        />
        <LoadingPanel
          title="정비 지시 내역"
          className="engineer-recent-events"
        />
      </section>
      <section className="engineer-factory-bottom-grid">
        <LoadingPanel title="선택 설비 근거 요약" />
        <LoadingPanel title="실시간 상태 신호" />
      </section>
    </main>
  );
}

export function EngineerFactoryStandalone({
  model,
  selectedAssetId,
  canGenerateBrief = false,
  briefingResponse,
  briefingRole = "process_engineer",
  readOnly = false,
  recordPanel,
  maintenanceDirectives = [],
  maintenanceDirectiveError = false,
  currentUser,
  onSelectAsset,
  onRefresh,
  onLogout,
}: {
  model: OperationsBootstrapModel;
  selectedAssetId: string | null;
  canGenerateBrief?: boolean;
  briefingResponse?: OperationsAgentReviewSummaryResponse;
  briefingRole?: "process_engineer" | "maintenance_technician" | "process_manager";
  readOnly?: boolean;
  recordPanel?: ReactNode;
  maintenanceDirectives?: OpenInspectionWorkOrderReadModel[];
  maintenanceDirectiveError?: boolean;
  currentUser?: { displayName: string; title: string };
  onSelectAsset: (assetId: string, eventId: string | null) => void;
  onRefresh: () => void;
  onLogout?: () => void | Promise<void>;
}) {
  const [sensorDetailOpen, setSensorDetailOpen] = useState(false);
  const [expandedSensor, setExpandedSensor] = useState<string | null>(null);
  const [directiveAssetId, setDirectiveAssetId] = useState<string | null>(null);
  const [maintenanceRequestBusy, setMaintenanceRequestBusy] = useState(false);
  const [maintenanceRequestFailed, setMaintenanceRequestFailed] =
    useState(false);
  const [maintenanceRequestSucceeded, setMaintenanceRequestSucceeded] =
    useState(false);
  const [zoneFilter, setZoneFilter] = useState("all");
  const [equipmentFilter, setEquipmentFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");

  useEffect(() => {
    if (!sensorDetailOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [sensorDetailOpen]);
  const selected =
    model.assets.find((asset) => asset.assetId === selectedAssetId) ??
    model.assets[0] ??
    null;
  const highestRisk =
    [...model.assets].sort(
      (a, b) => (b.failureProbability ?? -1) - (a.failureProbability ?? -1),
    )[0] ?? null;
  const riskEquipment = [...model.assets]
    .filter((asset) => asset.status !== "normal")
    .sort(
      (a, b) => (b.failureProbability ?? -1) - (a.failureProbability ?? -1),
    );
  const riskSelected =
    (maintenanceDirectives.some((item) => item.asset_id === directiveAssetId)
      ? model.assets.find((asset) => asset.assetId === directiveAssetId)
      : null) ?? highestRisk;
  const groups = new Map<string, OperationsAsset[]>();
  const matchesMonitoringCondition = (asset: OperationsAsset) => {
    const isCompressor =
      asset.assetType.toLowerCase().includes("compress") ||
      asset.assetId.startsWith("CMP-");
    return (
      (zoneFilter === "all" || asset.line === zoneFilter) &&
      (equipmentFilter === "all" ||
        (equipmentFilter === "compressor" ? isCompressor : !isCompressor)) &&
      (statusFilter === "all" || tone(asset.status) === statusFilter)
    );
  };
  const highlightedAssetCount = model.assets.filter(
    matchesMonitoringCondition,
  ).length;
  model.assets.forEach((asset) => {
    const key = `${asset.line || "위치 미상"}`;
    groups.set(key, [...(groups.get(key) ?? []), asset]);
  });
  const actionable = model.assets.filter(
    (asset) => asset.status === "critical" || asset.status === "warning",
  ).length;
  const held = model.assets.filter(
    (asset) => asset.status === "data_quality_hold",
  ).length;
  const values = riskSelected?.riskHistory?.map((point) => point.value) ?? [];
  const points = values
    .map(
      (value, index) =>
        `${((index / Math.max(1, values.length - 1)) * 100).toFixed(2)},${(100 - value * 100).toFixed(2)}`,
    )
    .join(" ");
  const factors =
    selected?.topFactors
      .filter((factor) => typeof factor.value === "number")
      .slice(0, 4) ?? [];
  const selectedMaintenanceDirective = selected
    ? maintenanceDirectives.find((item) => item.asset_id === selected.assetId)
    : null;
  const approvedMaintenanceDirectives = maintenanceDirectives.filter(
    (item) => item.status === "approved" || item.status === "in_progress",
  );
  const requestedMaintenanceDirectives = maintenanceDirectives.filter(
    (item) => item.status !== "approved" && item.status !== "in_progress",
  );

  async function requestMaintenanceApproval() {
    if (readOnly || !selected?.eventId || selectedMaintenanceDirective) return;
    setMaintenanceRequestBusy(true);
    setMaintenanceRequestFailed(false);
    setMaintenanceRequestSucceeded(false);
    try {
      if (!selected.maintenanceSnapshotBasis) {
        throw new Error("maintenance snapshot basis unavailable");
      }
      await requestInspectionWorkOrder({
        projectId: model.context.projectId,
        workspaceId: model.context.workspaceId,
        eventId: selected.eventId,
        snapshotBasis: selected.maintenanceSnapshotBasis,
        idempotencyKey: [
          "engineer-maintenance-approval",
          selected.eventId,
          selected.maintenanceSnapshotBasis.artifact_id,
        ]
          .join(":")
          .replace(/[^A-Za-z0-9_.:-]/g, "_")
          .slice(0, 200),
      });
      setDirectiveAssetId(selected.assetId);
      setMaintenanceRequestSucceeded(true);
      onRefresh();
    } catch {
      setMaintenanceRequestFailed(true);
    } finally {
      setMaintenanceRequestBusy(false);
    }
  }

  return (
    <main className="engineer-lite-board">
      <header className="engineer-factory-header">
        <div>
          <strong>공장 현황</strong>
          <span>
            {model.context.workspaceName} · {groups.size}개 라인 · 설비{" "}
            {model.assets.length}대
          </span>
        </div>
        <div className="engineer-factory-live">
          <i />
          <b>{readOnly ? "보관된 관측 재현" : "실시간 수집 중"}</b>
          <span>
            기준 시각{" "}
            {formatTimestamp(
              model.context.observedAt ?? model.context.refreshedAt,
            )}
          </span>
          <button
            type="button"
            onClick={onRefresh}
            aria-label="공장 현황 새로고침"
            disabled={readOnly}
          >
            ↻ 새로고침
          </button>
          {onLogout ? (
            <OperationsAccountBadge displayName={currentUser?.displayName ?? "사용자"} title={currentUser?.title ?? "엔지니어"} />
          ) : null}
          {onLogout ? (
            <button
              type="button"
              className="engineer-logout-button"
              onClick={() => void onLogout()}
              aria-label="로그아웃"
              title="로그아웃"
            >
              <LogOut size={14} />
              <span>로그아웃</span>
            </button>
          ) : null}
        </div>
      </header>

      <section className="engineer-factory-kpis">
        <article>
          <span>즉시 조치 필요 설비</span>
          <strong>
            {actionable}
            <small>대</small>
          </strong>
          <p>긴급·경고 등급으로 현장 확인이 필요합니다.</p>
        </article>
        <article>
          <span>{readOnly ? "진단값 확인 가능 설비" : "가동 중 설비"}</span>
          <strong>
            {Math.max(0, model.assets.length - held)}
            <small>/ {model.assets.length}대</small>
          </strong>
          <p>확인 보류 설비 {held}대는 별도로 구분합니다.</p>
        </article>
        <article>
          <span>예상 정지 영향</span>
          <strong>
            {formatMinutes(model.metrics.estimatedDowntimeMinutes)}
          </strong>
          <p>{readOnly ? "생산 계획의 정지 가정입니다. 실제 정지 시간은 아닙니다." : "현재 위험 설비의 예측 비가동 시간 합계입니다."}</p>
        </article>
      </section>

      <section
        className="engineer-monitoring-toolbar"
        aria-label="설비 감시 조건"
      >
        <div>
          <strong>감시 조건</strong>
          <span>
            {highlightedAssetCount}대 강조 · 전체 {model.assets.length}대
          </span>
        </div>
        <label>
          <span>구역</span>
          <select
            value={zoneFilter}
            onChange={(event) => setZoneFilter(event.target.value)}
          >
            <option value="all">전체 구역</option>
            {[...new Set(model.assets.map((asset) => asset.line))].map(
              (line) => (
                <option key={line} value={line}>
                  {zoneLabel(line)}
                </option>
              ),
            )}
          </select>
        </label>
        <label>
          <span>설비</span>
          <select
            value={equipmentFilter}
            onChange={(event) => setEquipmentFilter(event.target.value)}
          >
            <option value="all">전체 설비</option>
            <option value="compressor">압축기</option>
            <option value="cnc">CNC 가공기</option>
          </select>
        </label>
        <label>
          <span>상태</span>
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="all">전체 상태</option>
            <option value="normal">정상</option>
            <option value="attention">주의</option>
            <option value="critical">긴급</option>
            <option value="hold">확인 필요</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setZoneFilter("all");
            setEquipmentFilter("all");
            setStatusFilter("all");
          }}
        >
          초기화
        </button>
      </section>

      <section className="engineer-lite-main">
        <section className="engineer-factory-card engineer-equipment-list">
          <header>
            <strong>라인 · 셀 · 설비 상태</strong>
            <span>설비를 누르면 현황이 함께 바뀝니다</span>
          </header>
          <div className="engineer-equipment-scroll">
            {[...groups.entries()].map(([line, assets]) => {
              const cells = new Map<string, OperationsAsset[]>();
              assets.forEach((asset) =>
                cells.set(asset.cell, [
                  ...(cells.get(asset.cell) ?? []),
                  asset,
                ]),
              );
              return (
                <article key={line} className="engineer-equipment-zone">
                  <div className="engineer-equipment-zone-label">
                    <b>{zoneLabel(line)}</b>
                    <small>{assets.length}대</small>
                  </div>
                  <div className="engineer-equipment-cells">
                    {[...cells.entries()].map(([cell, cellAssets]) => {
                      const compressors = cellAssets.filter(
                        (asset) =>
                          asset.assetType.toLowerCase().includes("compress") ||
                          asset.assetId.startsWith("CMP-"),
                      );
                      const machines = cellAssets.filter(
                        (asset) => !compressors.includes(asset),
                      );
                      const machineRows = Array.from(
                        { length: Math.ceil(machines.length / 2) },
                        (_, index) => machines.slice(index * 2, index * 2 + 2),
                      );
                      const assetButton = (asset: OperationsAsset) => (
                        <button
                          type="button"
                          key={asset.assetId}
                          aria-label={`${displayAssetShortName(asset)} · ${STATUS_LABEL[asset.status]} · 위험도 ${formatProbability(asset.failureProbability)}`}
                          aria-pressed={asset.assetId === selected?.assetId}
                          style={
                            { "--risk-fill": riskFill(asset) } as CSSProperties
                          }
                          className={`tone-${tone(asset.status)} ${matchesMonitoringCondition(asset) ? "is-highlighted" : "is-muted"} ${asset.assetId === selected?.assetId ? "is-selected" : ""}`}
                          onClick={() => {
                            onSelectAsset(asset.assetId, asset.eventId);
                            setSensorDetailOpen(true);
                          }}
                        >
                          <span>{displayAssetShortName(asset)}</span>
                        </button>
                      );
                      return (
                        <section key={cell} className="engineer-equipment-cell">
                          <header>
                            <b>{cellLabel(cell)}</b>
                            <small>{cellAssets.length}대</small>
                          </header>
                          <div className="engineer-cell-compressor">
                            {compressors.map(assetButton)}
                          </div>
                          <div className="engineer-cell-machines">
                            {machineRows.map((row, index) => (
                              <div
                                className="engineer-cell-machine-row"
                                key={`${cell}-row-${index}`}
                              >
                                {row.map(assetButton)}
                              </div>
                            ))}
                          </div>
                        </section>
                      );
                    })}
                  </div>
                </article>
              );
            })}
          </div>
          <footer className="engineer-equipment-legend">
            <span>
              <i className="normal" />
              정상
            </span>
            <span>
              <i className="attention" />
              주의
            </span>
            <span>
              <i className="critical" />
              긴급
            </span>
            <span>
              <i className="hold" />
              확인 필요
            </span>
          </footer>
        </section>

        {recordPanel ?? (
        <div className="engineer-status-side-stack">
          <section className="engineer-factory-card engineer-recent-events engineer-approval-events">
            <header>
              <strong>정비 승인 내역</strong>
              <span
                className={`engineer-directive-connection ${maintenanceDirectiveError ? "is-offline" : "is-online"}`}
              >
                <i />
                {maintenanceDirectiveError
                  ? "연결 확인 필요"
                  : "목록 연결 정상"}
              </span>
              <span>{approvedMaintenanceDirectives.length}건</span>
            </header>
            <div>
              {!maintenanceDirectiveError &&
              approvedMaintenanceDirectives.length ? (
                approvedMaintenanceDirectives.map((directive) => (
                  <button
                    type="button"
                    key={directive.work_order_id}
                    aria-pressed={directiveAssetId === directive.asset_id}
                    onClick={() => {
                      setDirectiveAssetId(directive.asset_id);
                      onSelectAsset(directive.asset_id, directive.event_id);
                    }}
                  >
                    <span>
                      <b>
                        {directive.status === "in_progress"
                          ? "점검 중"
                          : "승인됨"}
                      </b>
                      <small title={directive.work_order_id}>
                        {compactJobId(directive.work_order_id)}
                      </small>
                    </span>
                    <strong>
                      {directive.equipment_id || directive.asset_id}
                    </strong>
                    <small>{directive.asset_id}</small>
                    <p>
                      {directive.assigned_to
                        ? `담당 ${directive.assigned_to_display_name ?? directive.assigned_to}`
                        : "담당자 배정 대기"}
                    </p>
                  </button>
                ))
              ) : (
                <p className="engineer-directive-empty">
                  {maintenanceDirectiveError
                    ? "승인 내역을 조회할 수 없습니다"
                    : "현재 정비 승인 내역이 없습니다"}
                </p>
              )}
            </div>
          </section>

          <section className="engineer-factory-card engineer-recent-events">
            <header>
              <strong>요청 내역</strong>
              <span
                className={`engineer-directive-connection ${maintenanceDirectiveError ? "is-offline" : "is-online"}`}
              >
                <i />
                {maintenanceDirectiveError
                  ? "연결 확인 필요"
                  : "목록 연결 정상"}
              </span>
              <span>
                {requestedMaintenanceDirectives.length
                  ? `대기 ${requestedMaintenanceDirectives.length}건 · 먼저 접수된 순`
                  : "미완료 작업"}
              </span>
            </header>
            <div>
              {!maintenanceDirectiveError &&
              requestedMaintenanceDirectives.length ? (
                requestedMaintenanceDirectives.map((directive) => (
                  <button
                    type="button"
                    key={directive.work_order_id}
                    aria-pressed={directiveAssetId === directive.asset_id}
                    onClick={() => {
                      setDirectiveAssetId(directive.asset_id);
                      onSelectAsset(directive.asset_id, directive.event_id);
                    }}
                  >
                    <span>
                      <b>
                        {directive.status === "in_progress"
                          ? "점검 중"
                          : directive.status === "approved"
                            ? "승인됨"
                            : "요청됨"}
                      </b>
                      <small title={directive.work_order_id}>
                        {compactJobId(directive.work_order_id)}
                      </small>
                    </span>
                    <strong>
                      {directive.equipment_id || directive.asset_id}
                    </strong>
                    <small>{directive.asset_id}</small>
                    <p>
                      {directive.assigned_to
                        ? `담당 ${directive.assigned_to_display_name ?? directive.assigned_to}`
                        : "담당자 배정 대기"}
                    </p>
                  </button>
                ))
              ) : (
                <p className="engineer-directive-empty">
                  {maintenanceDirectiveError
                    ? "요청 내역을 조회할 수 없습니다"
                    : "현재 요청 내역이 없습니다"}
                </p>
              )}
            </div>
          </section>
        </div>
        )}
      </section>

      <section className="engineer-factory-bottom-grid">
        <section className="engineer-factory-card engineer-evidence-summary">
          <header>
            <strong>선택 설비 근거 요약</strong>
            <span>
              {selected?.assetId ?? "-"} ·{" "}
              {formatTimestamp(selected?.observedAt ?? null)} 관측
            </span>
          </header>
          {selected ? (
            <>
              <div className="engineer-evidence-lead">
                <b>{STATUS_LABEL[selected.status]}</b>
                <strong>
                  {selected.status === "critical"
                    ? "지금 현장 확인과 보전 대응이 필요한 설비입니다."
                    : selected.status === "data_quality_hold"
                      ? "값보다 계측 연결 상태를 먼저 확인해야 합니다."
                      : "현재 상태에 맞춰 관찰과 점검을 이어갑니다."}
                </strong>
              </div>
              <NaturalBriefing projectId={model.context.projectId} workspaceId={model.context.workspaceId}
                assetId={selected.assetId} eventId={selected.eventId} datasetVersionId={model.context.datasetVersionId}
                observedAt={selected.observedAt} role={briefingRole} providedResponse={briefingResponse} canGenerate={canGenerateBrief && !readOnly} revision={JSON.stringify([selected, maintenanceDirectives.filter(item => item.asset_id === selected.assetId)])}/>
              <ol>
                {selected.topFactors.slice(0, 4).map((factor) => (
                  <li key={factor.id}>
                    {displayEquipmentSensorLabel(
                      selected?.assetId,
                      factor.feature,
                      factor.label,
                    )}{" "}
                    · 기여도 {Math.round(Math.abs(factor.contribution) * 100)}%
                  </li>
                ))}
              </ol>
              <dl>
                <div>
                  <dt>담당자</dt>
                  <dd>{selected.assignedEngineer ?? "미배정"}</dd>
                </div>
                <div>
                  <dt>예상 정지</dt>
                  <dd>{formatMinutes(selected.estimatedDowntimeMinutes)}</dd>
                </div>
                <div>
                  <dt>부품</dt>
                  <dd>
                    {selected.sparePartAvailable === true
                      ? "확보"
                      : selected.sparePartAvailable === false
                        ? "미확보"
                        : "확인 필요"}
                  </dd>
                </div>
                <div>
                  <dt>설비 중요도</dt>
                  <dd>{selected.criticality ?? "정보 없음"}</dd>
                </div>
              </dl>
              <p className="engineer-evidence-footer">
                판단 근거는 현재 선택 설비의 서버 진단 결과와 관측 시각을 기준으로
                표시합니다.
              </p>
            </>
          ) : null}
        </section>
        <section className="engineer-factory-card engineer-live-signals">
          <header>
            <strong>{readOnly ? "기준 시각의 관측 신호" : "실시간 상태 신호"}</strong>
            <span>
              위험 판단에 반영된 신호 상위 {factors.length}건 ·{" "}
              {formatTimestamp(selected?.observedAt ?? null)}
            </span>
          </header>
          <div>
            {factors.map((factor) => (
              <article key={factor.id}>
                <i>
                  <b
                    style={{
                      height: `${Math.max(8, Math.min(100, Math.abs(factor.contribution) * 100))}%`,
                    }}
                  />
                </i>
                <strong>
                  {factor.value?.toLocaleString("ko-KR", {
                    maximumFractionDigits: 2,
                  })}
                  <small>{factor.unit ?? ""}</small>
                </strong>
                <span>
                  {displayEquipmentSensorLabel(
                    selected?.assetId,
                    factor.feature,
                    factor.label,
                  )}
                </span>
                <small>현재 관측값</small>
              </article>
            ))}
          </div>
          <footer className="engineer-signal-note">
            <span>
              <i />
              정상 범위 띠
            </span>
            <span>막대 높이 = 위험 기여도</span>
            <span>서버 관측 품질 기준</span>
          </footer>
        </section>
      </section>

      {sensorDetailOpen && selected ? (
        <div
          className="engineer-sensor-overlay"
          onClick={() => {
            setSensorDetailOpen(false);
            setExpandedSensor(null);
          }}
        >
          <aside
            className="engineer-sensor-drawer"
            aria-label={`${displayAssetName(selected)} 상세 현황`}
            onClick={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <strong>{displayAssetName(selected)}</strong>
                <span>{selected.assetId} · 위험 및 정비 요청 현황</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSensorDetailOpen(false);
                  setExpandedSensor(null);
                }}
                aria-label="센서 상세 닫기"
              >
                ×
              </button>
            </header>
            <div className="engineer-sensor-drawer-body">
              <section className="engineer-detail-column">
                <article className="engineer-drawer-risk">
                  <header>
                    <div>
                      <strong>위험 점수 추세 · 최근 관측</strong>
                      <span>
                        {displayAssetName(selected)} · {selected.assetId}
                      </span>
                    </div>
                    <b className={`tone-${tone(selected.status)}`}>
                      {formatProbability(selected.failureProbability)}
                    </b>
                  </header>
                  <div className="engineer-drawer-trend">
                    <TrendSvg
                      points={sensorPolyline(selected.riskHistory ?? [])}
                    />
                    <div>
                      <span>이전 관측</span>
                      <span>현재</span>
                    </div>
                  </div>
                  <footer>
                    <span>
                      현재 상태 <b>{STATUS_LABEL[selected.status]}</b>
                    </span>
                    <span>
                      {selected.riskHistory?.length ?? 0}개 관측 ·{" "}
                      {formatTimestamp(selected.riskHistory?.[0]?.observedAt)}
                    </span>
                  </footer>
                </article>
                <article className="engineer-detail-summary">
                  <header>
                    <strong>선택 설비 근거 요약</strong>
                    <span>{formatTimestamp(selected.observedAt)} 관측</span>
                  </header>
                  <div className="engineer-detail-summary-status">
                    <p>
                      {selected.status === "critical"
                        ? "즉시 현장 확인과 보전 대응이 필요합니다."
                        : selected.status === "data_quality_hold"
                          ? "센서 연결과 데이터 품질을 먼저 확인해야 합니다."
                          : "현재 상태를 기준으로 관찰과 점검을 이어갑니다."}
                    </p>
                    <span
                      className={`engineer-request-connection ${maintenanceRequestBusy ? "is-checking" : maintenanceDirectiveError || maintenanceRequestFailed ? "is-offline" : "is-online"}`}
                    >
                      <i />
                      {maintenanceRequestBusy
                        ? "연결 확인 중"
                        : selectedMaintenanceDirective ||
                            maintenanceRequestSucceeded
                          ? "요청 등록 완료"
                          : maintenanceDirectiveError ||
                              maintenanceRequestFailed
                            ? "요청 연결 확인 필요"
                            : "요청 연결 정상"}
                    </span>
                  </div>
                  <div className="engineer-detail-actions">
                    <button
                      type="button"
                      className="is-primary"
                      disabled={
                        readOnly || maintenanceRequestBusy ||
                        Boolean(selectedMaintenanceDirective) ||
                        !selected.eventId
                      }
                      onClick={() => void requestMaintenanceApproval()}
                    >
                      {maintenanceRequestBusy
                        ? "점검 요청 중"
                        : selectedMaintenanceDirective
                          ? selectedMaintenanceDirective.status === "approved" ? "보전팀 접수됨" : selectedMaintenanceDirective.status === "in_progress" ? "보전팀 점검 중" : "점검 요청됨"
                          : "점검 요청"}
                    </button>
                    <EngineerRequestProgress projectId={model.context.projectId} workspaceId={model.context.workspaceId} order={selectedMaintenanceDirective}
                      busy={maintenanceRequestBusy} connectionError={maintenanceDirectiveError || maintenanceRequestFailed} />
                  </div>
                  {selectedMaintenanceDirective ? <p role="status" className="engineer-detail-work-status">
                    <span>{selectedMaintenanceDirective.status === "approved" ? "보전팀 처리 대기 · 점검 후 정비가 필요한 경우 생산 관리자에게 승인을 요청합니다." : selectedMaintenanceDirective.status === "in_progress" ? "보전팀 처리 중 · 담당자가 점검 또는 승인된 정비의 결과를 기록합니다." : "보전팀의 점검 요청 접수를 기다리고 있습니다."}</span>
                    <span className="engineer-detail-assignee">담당: {selectedMaintenanceDirective.assigned_to_display_name || "배정 대기"}</span>
                  </p> : null}
                  <dl>
                    <div>
                      <dt>상태</dt>
                      <dd>{STATUS_LABEL[selected.status]}</dd>
                    </div>
                    <div>
                      <dt>담당자</dt>
                      <dd>{selected.assignedEngineer ?? "미배정"}</dd>
                    </div>
                    <div>
                      <dt>예상 정지</dt>
                      <dd>
                        {formatMinutes(selected.estimatedDowntimeMinutes)}
                      </dd>
                    </div>
                    <div>
                      <dt>부품</dt>
                      <dd>
                        {selected.sparePartAvailable === true
                          ? "확보"
                          : selected.sparePartAvailable === false
                            ? "미확보"
                            : "확인 필요"}
                      </dd>
                    </div>
                  </dl>
                  <ol>
                    {selected.topFactors.slice(0, 4).map((factor) => (
                      <li key={factor.id}>
                        {displayEquipmentSensorLabel(
                          selected?.assetId,
                          factor.feature,
                          factor.label,
                        )}{" "}
                        <b>
                          {Math.round(Math.abs(factor.contribution) * 100)}%
                        </b>
                      </li>
                    ))}
                  </ol>
                </article>
              </section>
              <section className="engineer-drawer-sensors">
                {selected.sensorHistory?.length ? (
                  orderEngineerSensors(selected.assetId, selected.sensorHistory).map((sensor) => {
                    const latest = sensor.points.at(-1)?.value;
                    return (
                      <article
                        key={sensor.feature}
                        role="button"
                        tabIndex={0}
                        onClick={() => setExpandedSensor(sensor.feature)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ")
                            setExpandedSensor(sensor.feature);
                        }}
                      >
                        <header>
                          <strong>
                            {displayEquipmentSensorLabel(
                              selected.assetId,
                              sensor.feature,
                              sensor.label,
                            )}
                          </strong>
                          <span>
                            {latest?.toLocaleString("ko-KR", {
                              maximumFractionDigits: 2,
                            })}
                            {sensor.unit ? ` ${sensor.unit}` : ""}
                          </span>
                        </header>
                        <div className="engineer-drawer-trend">
                          <TrendSvg points={sensorPolyline(sensor.points)} />
                          <div>
                            <span>이전 관측</span>
                            <span>현재</span>
                          </div>
                        </div>
                        <footer>
                          <span>{sensor.points.length}개 관측</span>
                          <span>확대해서 보기</span>
                        </footer>
                      </article>
                    );
                  })
                ) : (
                  <p>표시할 센서 관측 이력이 없습니다.</p>
                )}
              </section>
              <section className="engineer-detail-requests">
                <header>
                  <div>
                    <strong>정비 승인 목록</strong>
                    <span>승인 상태 확인</span>
                  </div>
                  <span
                    className={`engineer-directive-connection ${maintenanceDirectiveError ? "is-offline" : "is-online"}`}
                  >
                    <i />
                    {maintenanceDirectiveError
                      ? "연결 확인 필요"
                      : "목록 연결 정상"}
                  </span>
                </header>
                <div>
                  {!maintenanceDirectiveError &&
                  maintenanceDirectives.length ? (
                    maintenanceDirectives.map((directive) => (
                      <button
                        type="button"
                        key={directive.work_order_id}
                        className={
                          directive.asset_id === selected.assetId
                            ? "is-selected"
                            : ""
                        }
                        onClick={() => {
                          setDirectiveAssetId(directive.asset_id);
                          setExpandedSensor(null);
                          onSelectAsset(directive.asset_id, directive.event_id);
                        }}
                      >
                        <span>
                          <b>
                            {directive.status === "in_progress"
                              ? "점검 중"
                              : directive.status === "approved"
                                ? "승인됨"
                                : "요청됨"}
                          </b>
                          <small title={directive.work_order_id}>
                            {compactJobId(directive.work_order_id)}
                          </small>
                        </span>
                        <strong>
                          {directive.equipment_id || directive.asset_id}
                        </strong>
                        <small>{directive.asset_id}</small>
                        <p>
                          {directive.assigned_to
                            ? `담당 ${directive.assigned_to_display_name ?? directive.assigned_to}`
                            : "담당자 배정 대기"}
                        </p>
                      </button>
                    ))
                  ) : (
                    <p className="engineer-directive-empty">
                      {maintenanceDirectiveError
                        ? "정비 승인 목록을 불러오지 못했습니다"
                        : "현재 승인 대기 정비가 없습니다"}
                    </p>
                  )}
                </div>
              </section>
              <section className="engineer-detail-requests engineer-detail-risk-list">
                <header>
                  <div>
                    <strong>위험 장비 목록</strong>
                    <span>위험 점수 높은 순</span>
                  </div>
                  <span>{riskEquipment.length}대</span>
                </header>
                <div>
                  {riskEquipment.length ? (
                    riskEquipment.map((asset, index) => (
                      <button
                        type="button"
                        key={asset.assetId}
                        className={
                          asset.assetId === selected.assetId
                            ? "is-selected"
                            : ""
                        }
                        onClick={() => {
                          setDirectiveAssetId(null);
                          setExpandedSensor(null);
                          onSelectAsset(asset.assetId, asset.eventId);
                        }}
                      >
                        <span>
                          <b>{index + 1}위</b>
                          <strong
                            className={`engineer-risk-score tone-${tone(asset.status)}`}
                          >
                            {formatProbability(asset.failureProbability)}
                          </strong>
                        </span>
                        <strong>{displayAssetName(asset)}</strong>
                        <small>{asset.assetId}</small>
                      </button>
                    ))
                  ) : (
                    <p className="engineer-directive-empty">
                      현재 위험 장비가 없습니다
                    </p>
                  )}
                </div>
              </section>
            </div>
            {expandedSensor
              ? (() => {
                  const sensor = selected.sensorHistory?.find(
                    (item) => item.feature === expandedSensor,
                  );
                  return sensor ? (
                    <div
                      className="engineer-sensor-expanded"
                      onClick={() => setExpandedSensor(null)}
                    >
                      <article onClick={(event) => event.stopPropagation()}>
                        <header>
                          <div>
                            <strong>
                              {displayEquipmentSensorLabel(
                                selected.assetId,
                                sensor.feature,
                                sensor.label,
                              )}{" "}
                              상세 추이
                            </strong>
                            <span>{sensor.points.length}개 관측값</span>
                          </div>
                          <button
                            type="button"
                            onClick={() => setExpandedSensor(null)}
                            aria-label="확대 그래프 닫기"
                          >
                            ×
                          </button>
                        </header>
                        <DetailedTrendSvg
                          points={sensor.points}
                          unit={sensor.unit}
                        />
                        <footer>
                          <span>
                            {formatTimestamp(sensor.points[0]?.observedAt)}
                          </span>
                          <b>
                            {sensor.points
                              .at(-1)
                              ?.value.toLocaleString("ko-KR", {
                                maximumFractionDigits: 2,
                              })}
                            {sensor.unit ? ` ${sensor.unit}` : ""}
                          </b>
                          <span>
                            {formatTimestamp(sensor.points.at(-1)?.observedAt)}
                          </span>
                        </footer>
                      </article>
                    </div>
                  ) : null;
                })()
              : null}
          </aside>
        </div>
      ) : null}
    </main>
  );
}

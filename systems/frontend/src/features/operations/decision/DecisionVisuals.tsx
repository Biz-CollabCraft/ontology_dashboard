import { useState } from "react";
import type { OperationsEventDetailModel } from "../api/operationsContracts";
import { formatTimestamp } from "../components/OperationsUi";
import { factorLabel, fieldText, measurement } from "./decisionLabels";

export type SeriesPoint = { observedAt: string; value: number | null; qualityStatus?: string };
export function chartGeometry(points: SeriesPoint[], percent: boolean) {
  const sorted = points.filter(p => Number.isFinite(Date.parse(p.observedAt))).slice().sort((a,b) => Date.parse(a.observedAt)-Date.parse(b.observedAt));
  const values = sorted.filter(p => p.qualityStatus !== "bad" && typeof p.value === "number" && Number.isFinite(p.value)).map(p => p.value as number);
  const min = percent ? 0 : Math.min(...values), max = percent ? 100 : Math.max(...values);
  const padding = Math.max(Math.abs(max-min)*.12, Math.abs(max)*.02, .01);
  const low = percent ? 0 : min-padding, high = percent ? 100 : max+padding;
  const start = Date.parse(sorted[0]?.observedAt ?? ""), end = Date.parse(sorted.at(-1)?.observedAt ?? "");
  const coordinates = sorted.map(p => ({ ...p, x: end === start ? 350 : 52+(Date.parse(p.observedAt)-start)/(end-start)*610, y: p.value !== null && Number.isFinite(p.value) && p.qualityStatus !== "bad" ? 170-(p.value-low)/(high-low)*146 : null }));
  const segments: string[] = []; let current: string[] = [];
  for (const p of coordinates) { if (p.y === null) { if (current.length) segments.push(current.join(" ")); current=[]; } else current.push(`${p.x},${p.y}`); }
  if(current.length) segments.push(current.join(" "));
  return { coordinates, segments, low, high, hasValues: values.length>0 };
}
export function SeriesChart({ title, points, unit, percent=false, threshold }: { title: string; points: SeriesPoint[]; unit?: string | null; percent?: boolean; threshold?: number | null }) {
  const chart = chartGeometry(points, percent);
  const [selected, setSelected] = useState<number | null>(null);
  const point = selected === null ? chart.coordinates.at(-1) : chart.coordinates[selected];
  return <section className="dw-chart"><h3>{title}</h3>{chart.hasValues ? <>
    <svg viewBox="0 0 700 205" role="img" aria-label={title}>
      {[chart.low,(chart.low+chart.high)/2,chart.high].map((v,i)=><g key={i}><line x1="52" x2="662" y1={170-i*73} y2={170-i*73} stroke="#d4dde2" /><text x="45" y={174-i*73} textAnchor="end">{v.toLocaleString("ko-KR",{maximumFractionDigits:1})}</text></g>)}
      {percent && typeof threshold === "number" && <line x1="52" x2="662" y1={170-threshold*146} y2={170-threshold*146} stroke="#b16c50" strokeDasharray="5 4"><title>주의 기준 {measurement(threshold*100,"%")}</title></line>}
      {chart.segments.map((s,i)=><polyline key={i} points={s} fill="none" stroke={percent ? "#b16c50" : "#34566a"} strokeWidth="2" />)}
      {chart.coordinates.map((p,i)=>p.y === null ? null : <circle key={i} cx={p.x} cy={p.y} r="4" fill={percent ? "#b16c50" : "#34566a"} tabIndex={0} onFocus={()=>setSelected(i)} onMouseEnter={()=>setSelected(i)} onClick={()=>setSelected(i)} aria-label={`${formatTimestamp(p.observedAt)} · ${measurement(p.value,unit)}`}><title>{formatTimestamp(p.observedAt)} · {measurement(p.value,unit)}</title></circle>)}
      <text x="52" y="195">{formatTimestamp(chart.coordinates[0]?.observedAt ?? null)}</text><text x="662" y="195" textAnchor="end">{formatTimestamp(chart.coordinates.at(-1)?.observedAt ?? null)}</text>
    </svg>
    <p className="dw-muted" aria-live="polite">{point ? `${formatTimestamp(point.observedAt)} · ${measurement(point.value,unit)}` : ""}{percent && typeof threshold === "number" ? ` · 점선: 주의 기준 ${measurement(threshold*100,"%")}` : ""}</p>
  </> : <p className="dw-empty-chart">이 기간에 표시할 관측 이력이 없습니다.</p>}</section>;
}
export function DecisionVisuals({detail}: {detail: OperationsEventDetailModel}) {
  const sensors=detail.sensors;
  const [sensorId,setSensorId]=useState(sensors.find(s => s.historyPoints?.some(p => p.value !== null))?.id ?? sensors[0]?.id ?? "");
  const sensor=sensors.find(s=>s.id===sensorId) ?? sensors[0];
  const factors=detail.topFactors.slice(0,5);
  const max=Math.max(...factors.map(f=>Math.abs(f.contribution)),.001);
  const lastRisk = detail.riskSeries.at(-1);
  const riskConflict = lastRisk && Date.parse(lastRisk.observedAt) === Date.parse(detail.event.observedAt ?? "") && detail.event.failureProbability !== null && Math.abs(lastRisk.failureProbability - detail.event.failureProbability) > 0.0001;
  return <section className="dw-panel dw-visuals">{riskConflict && <p className="dw-warning">현재 판단값과 이력의 마지막 위험도가 다릅니다. 현재 조치는 상단 판단 근거를 기준으로 검토해 주세요.</p>}<div className="dw-section-title"><h2>위험도와 설비 신호</h2><span className="dw-muted">선택한 관측 기준 · 최근 24시간</span></div>
    <div className="dw-chart-grid"><SeriesChart title="고장 위험도 추이" percent unit="%" threshold={detail.threshold} points={detail.riskSeries.map(p=>({observedAt:p.observedAt,value:p.failureProbability*100}))} />
    <section><label className="dw-chart-select">센서·분석 지표<select aria-label="센서·분석 지표" value={sensor?.id ?? ""} onChange={e=>setSensorId(e.target.value)}>{sensors.map(s=><option key={s.id} value={s.id}>{factorLabel(s.id,s.label)}</option>)}</select></label>{sensor ? <SeriesChart title={factorLabel(sensor.id,sensor.label)} unit={sensor.unit} points={sensor.historyPoints ?? []} /> : <p>연결된 센서가 없습니다.</p>}</section></div>
    {factors.length>0 && <div className="dw-factors"><h3>위험도 판단에 영향을 준 지표</h3>{factors.map(f=><div className="dw-factor" key={f.id}><span title={f.feature}>{factorLabel(f.feature,f.label)}</span><div className="dw-bar"><i style={{width:`${Math.abs(f.contribution)/max*100}%`,background:f.direction==="risk_up"?"#b16c50":"#548477"}} /></div><span>{f.direction==="risk_up"?"위험 증가":"위험 감소"} · {measurement(f.contribution)}</span></div>)}<p className="dw-muted">막대는 모델 기여도이며 고장 확률이나 센서 측정 단위와 다릅니다.</p></div>}
    {!!detail.evidenceContext?.selectedRelationPaths.length && <details className="dw-evidence"><summary>판단 근거 연결</summary>{detail.evidenceContext.selectedRelationPaths.map(p=><div className="dw-relation" key={p.candidateId}>{p.relationPath.map((node,i)=><span key={i}>{i>0&&" → "}{fieldText(node)}</span>)}</div>)}</details>}
  </section>;
}

import { economicBasis, referenceEconomics } from "./referenceEconomics";
const money = (n: number | null) => n === null ? "정지 시간 입력 필요" : n.toLocaleString("ko-KR") + "원";
export function ReferenceEconomicPanel({assetId, minutes}: {assetId: string; minutes?: number | null}) {
  const e = referenceEconomics(assetId, minutes);
  if (!e) return <p>이 설비 종류의 참고 단가표가 없습니다.</p>;
  return <section className="prb-basis" aria-label="가정 기반 비용 참고"><h3>비용 검토 참고 · 가정 기반</h3>
    <p>실제 견적·확정 손실이 아닙니다. {e.profile.affected_cnc}대 CNC 생산 의존 가정.</p>
    <dl><dt>시간당 생산원가</dt><dd>{money(e.hourlyProductionCost)}/시간</dd>
    <dt>시간당 정지 기회손실 노출</dt><dd>{money(e.hourlyOpportunity)}/시간</dd>
    <dt>계산 정지 시간 · {e.usesDefault ? "기본값 적용" : "직접 입력"}</dt><dd>{e.stopMinutes ?? "유효한 시간 필요"}분</dd>
    <dt>{e.usesDefault ? "기본 정지 시간 기준 노출액" : "요청 시간 기준 정지 노출액"}</dt><dd>{money(e.stopExposure)}</dd>
    <dt>정비 인건비 · {e.profile.labor_minutes}분/1인 가정</dt><dd>{money(e.labor)}</dd>
    <dt>교체 부품비 · {e.profile.part_scope}</dt><dd>{money(e.parts)}</dd></dl>
    <p>생산원가는 정지 손실에 합산하지 않습니다. 교체비는 실제 교체할 경우만 적용합니다.</p>
    <details><summary>단가·가정·근거 보기</summary>
      <p>버전: {e.version} · {e.profile.basis}</p>
      <p>미입력 기본 정지 시간: {e.profile.default_stop_minutes}분 · {e.profile.default_stop_basis} 승인 일정은 별도 확인합니다.</p>
      <div className="prb-table-scroll"><table><thead><tr><th>입력</th><th>값</th><th>근거</th></tr></thead><tbody>
      {economicBasis.parameters.map(p => <tr key={p.key}><th>{p.key}</th><td>{p.value.toLocaleString("ko-KR")} {p.unit}</td><td>{p.basis}</td></tr>)}</tbody></table></div>
      {economicBasis.sources.map(s => <p key={s.id}>{s.url.startsWith("https:") ? <a href={s.url} target="_blank" rel="noreferrer">{s.id}</a> : s.id}: {s.basis}</p>)}
      {economicBasis.limitations.map(l => <p key={l}>{l}</p>)}
    </details>
  </section>;
}

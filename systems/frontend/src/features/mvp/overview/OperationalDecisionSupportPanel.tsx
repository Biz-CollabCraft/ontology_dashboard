import { RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  createMvpDecisionSupportBrief,
  getMvpDecisionSupportBrief,
} from "../../../api";
import type {
  MvpDecisionBriefRole,
  MvpDecisionSupportResponse,
} from "../api/mvpContracts";

interface Props {
  assetId: string;
  projectId: string;
  workspaceId: string;
  evidenceSnapshotId: string | null;
  decisionAsOf: string | null;
  riskStatus: string;
  role: MvpDecisionBriefRole;
  canMaterialize: boolean;
}

const OPTION_LABEL: Record<string, string> = {
  stop_now: "지금 정지",
  planned_maintenance: "계획 정비",
  continue_operation: "제한 운전",
};

export function OperationalDecisionSupportPanel({
  assetId,
  projectId,
  workspaceId,
  evidenceSnapshotId,
  decisionAsOf,
  riskStatus,
  role,
  canMaterialize,
}: Props) {
  const [response, setResponse] = useState<MvpDecisionSupportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [materializing, setMaterializing] = useState(false);
  const [error, setError] = useState("");
  const request = useMemo(() => {
    if (!evidenceSnapshotId || !decisionAsOf) return null;
    return {
      assetId,
      projectId,
      workspaceId,
      evidenceSnapshotId,
      decisionAsOf,
      role,
    };
  }, [assetId, decisionAsOf, evidenceSnapshotId, projectId, role, workspaceId]);

  useEffect(() => {
    if (!request) {
      setResponse(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    void getMvpDecisionSupportBrief(request)
      .then((value) => {
        if (active) setResponse(value);
      })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "운영 판단 지원을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [request]);

  const materialize = async () => {
    if (!request || !canMaterialize) return;
    setMaterializing(true);
    setError("");
    try {
      setResponse(await createMvpDecisionSupportBrief({ ...request, riskStatus }));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "운영 판단 지원을 생성하지 못했습니다.");
    } finally {
      setMaterializing(false);
    }
  };

  const brief = response?.brief;
  const versions = brief ? Object.entries(brief.frame.context_version_set) : [];

  return (
    <section className="mvp-decision-support" aria-label="운영 판단 지원">
      <header>
        <div>
          <strong>운영 판단 지원</strong>
          <small>근거·운영 맥락 기반 읽기 전용 Brief</small>
        </div>
        <button
          type="button"
          className="mvp-agent-review-refresh"
          onClick={() => void materialize()}
          disabled={!request || !canMaterialize || materializing}
        >
          <RefreshCw size={13} className={materializing ? "mvp-action-spinner" : ""} />
          {materializing ? "생성 중" : canMaterialize ? "맥락 갱신" : "조회 전용"}
        </button>
      </header>

      {!request ? <p>Evidence snapshot과 관측 시점이 연결되면 판단 맥락을 조회할 수 있습니다.</p> : null}
      {loading ? <p>저장된 판단 맥락을 조회하는 중입니다.</p> : null}
      {error ? <p className="mvp-decision-support__error">{error}</p> : null}
      {!loading && request && !error && !brief ? (
        <p>저장된 Brief가 없습니다. 권한이 있는 담당자가 명시적으로 생성해야 합니다.</p>
      ) : null}

      {brief ? (
        <>
          <div className="mvp-decision-support__status">
            <span>{response?.trace.status}</span>
            <span>{response?.trace.reused ? "저장본 재사용" : "새 맥락 생성"}</span>
            <span>시간 검증 {response?.trace.temporal_validation}</span>
          </div>

          <dl className="mvp-decision-support__facts">
            <div><dt>위험 상태</dt><dd>{brief.frame.risk_status}</dd></div>
            <div><dt>생산오더</dt><dd>{brief.why_now.order_ids.join(", ") || "미연결"}</dd></div>
            <div><dt>재공 수량</dt><dd>{brief.why_now.wip_units ?? "미산정"}</dd></div>
            <div><dt>최초 납기</dt><dd>{brief.why_now.earliest_due_at ?? "미연결"}</dd></div>
          </dl>

          <div className="mvp-decision-support__section">
            <strong>관계와 제약</strong>
            {brief.relationships.length ? (
              <ol>
                {brief.relationships.slice(0, 6).map((item, index) => (
                  <li key={`${item.relationship_type}-${item.from_ref}-${item.to_ref}-${index}`}>
                    <b>{item.relationship_type}</b>
                    <span>{item.from_ref} → {item.to_ref}</span>
                    <small>{item.status}</small>
                  </li>
                ))}
              </ol>
            ) : <p>확인 가능한 관계가 없습니다.</p>}
          </div>

          <div className="mvp-decision-support__section">
            <strong>조건부 선택지 비교</strong>
            <div className="mvp-decision-support__options">
              {brief.option_comparison.map((item) => (
                <article key={item.option}>
                  <b>{OPTION_LABEL[item.option] ?? item.option}</b>
                  <span>{item.calculation_state}</span>
                  <small>자동 선택하지 않음</small>
                </article>
              ))}
            </div>
          </div>

          {brief.gaps.length || brief.why_now.decision_blockers.length ? (
            <div className="mvp-decision-support__section is-warning">
              <strong>Gap과 blocker</strong>
              <ul>
                {brief.why_now.decision_blockers.map((item) => <li key={item}>{item}</li>)}
                {brief.gaps.map((item, index) => (
                  <li key={`${item.owner_domain}-${item.state}-${index}`}>
                    {item.owner_domain}: {item.state}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <details className="mvp-decision-support__sources">
            <summary>출처와 시간 기준</summary>
            <small>as-of {brief.frame.decision_as_of}</small>
            {versions.map(([domain, version]) => (
              <code key={domain}>{domain}: {version}</code>
            ))}
            {Object.entries(brief.source_classifications).map(([domain, source]) => (
              <small key={domain}>{domain}: {source}</small>
            ))}
          </details>
          <small>AI는 계산 결과를 설명하며 WorkOrder·정비 실행을 생성하지 않습니다.</small>
        </>
      ) : null}
    </section>
  );
}

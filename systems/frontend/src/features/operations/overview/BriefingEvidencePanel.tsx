import { useEffect, useState } from "react";
import { getOperationsAgentReviewPacket } from "../../../api";
import { resolveBriefingEvidence, type BriefingEvidenceItem } from "./briefingEvidence";

interface Props {
  projectId: string; assetId: string; eventId: string | null;
  datasetVersionId?: string | null; observedAt?: string | null;
  refs: string[];
  expectedSummaryKey?: string;
  onEvidenceChanged?: () => void;
}

export function BriefingEvidencePanel(props: Props) {
  const [items, setItems] = useState<BriefingEvidenceItem[]>([]);
  const [status, setStatus] = useState("연결된 근거를 불러오는 중입니다.");
  useEffect(() => {
    const controller = new AbortController();
    if (!props.expectedSummaryKey) {
      setStatus("브리핑의 근거 기준을 확인할 수 없습니다. 브리핑을 다시 조회해 주세요.");
      return () => controller.abort();
    }
    void getOperationsAgentReviewPacket({ ...props, historyWindow: "24h", signal: controller.signal }).then(packet => {
      if (controller.signal.aborted) return;
      const basis = packet.snapshot_basis;
      if (packet.project_id !== props.projectId || packet.asset_id !== props.assetId || basis?.event_id !== props.eventId
        || (props.observedAt && Date.parse(packet.generated_at) !== Date.parse(props.observedAt))) {
        setStatus("근거가 갱신되었습니다. 현재 사건의 브리핑을 다시 확인해 주세요.");
        props.onEvidenceChanged?.();
        return;
      }
      const evidence = resolveBriefingEvidence(packet, props.refs);
      setItems(evidence);
      setStatus(evidence.length ? "" : "이 인용의 상세 근거가 현재 사건에 연결되어 있지 않습니다.");
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      const changed = error && typeof error === "object" && "status" in error && error.status === 409;
      if (changed) props.onEvidenceChanged?.();
      setStatus(changed
        ? "근거가 갱신되었습니다. 현재 사건의 브리핑을 다시 확인해 주세요."
        : "근거를 불러오지 못했습니다. 닫았다가 다시 열어 주세요.");
    });
    return () => controller.abort();
  }, []);
  return <div className="natural-briefing-evidence" aria-label="연결 근거 상세">
    <p className="natural-briefing-evidence-scope">{props.assetId} · 선택한 사건의 브리핑 근거</p>
    {status ? <p role="status">{status}</p> : null}
    {items.map(item => <article key={item.id}>
      <strong>{item.title}</strong><p>{item.text || "상세 내용이 없습니다."}</p>
      {item.details?.length ? <dl>{item.details.map((detail, index) => <div key={index}><dt>{detail.label}</dt><dd>{detail.value}</dd></div>)}</dl> : null}
      {item.paths.map((path, index) => <ol aria-label="근거 연결 경로" key={index}>
        <li>{path.steps[0].source_id}</li>
        {path.steps.map(step => <li key={step.edge_id}>{step.target_id}</li>)}
      </ol>)}
    </article>)}
  </div>;
}

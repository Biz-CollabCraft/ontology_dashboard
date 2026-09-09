import type { EvidenceRelationPath, OperationsAgentReviewPacket } from "../api/operationsContracts";

export interface BriefingEvidenceItem {
  id: string;
  title: string;
  text: string;
  paths: EvidenceRelationPath[];
  details?: { label: string; value: string }[];
}

const titles: Record<string, string> = {
  production_orders: "생산오더", wip: "재공품", delivery_commitments: "납기",
  part_requirements: "필요 부품", inventory_snapshots: "부품 재고",
  maintenance_windows: "정비 가능 시간", technician_candidates: "작업자",
  quality_lots: "품질 상태", alternative_resources: "대체 설비",
};

export function evidenceTime(value: unknown): string {
  if (typeof value !== "string" || !value || Number.isNaN(Date.parse(value))) return "시각 확인 필요";
  return new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(value)) + " (한국 시간)";
}

function gapLabel(gap: { field: string; reason: string }): string {
  if (gap.field.includes("baseline")) return "센서 정상 범위 기준 미확인";
  if (gap.field.includes("history.points")) return "센서 변화 추이 미연결";
  if (gap.field === "risk_series") return "위험도 변화 이력 미연결";
  if (gap.field === "equipment_history") return "설비 전체 정비 이력 미연결";
  if (gap.field.includes("criticality")) return "설비 중요도 기준 미확인";
  if (gap.field.startsWith("maintenance_context")) return "정비 계획 정보 미확인";
  if (gap.field.startsWith("operation_context")) return "생산 운영 정보 미확인";
  if (gap.field === "review_priority") return "점검 우선순위 산정 기준 부족";
  return /[가-힣]/.test(gap.reason) ? gap.reason : "추가 판단 근거 미확인";
}

const activityLabels: Record<string, string> = {
  "work_order.in_progress": "점검 시작", "inspection.result_recorded": "점검 결과 기록",
  "inspection.finished": "점검 완료", "inspection.coordination.pending": "생산 협의 요청",
  "work_order.requested": "작업요청 생성", "work_order.assigned": "요청 수락·담당 배정",
  "work_order.approved": "작업요청 승인", "work_order.started": "작업 시작", "work_order.completed": "작업 완료",
  "inspection.completed": "점검 결과 기록", "recommendation.proposed": "정비안 제안",
  "recommendation.decided": "정비안 판단", "maintenance.started": "정비 시작", "maintenance.completed": "정비 완료",
  "maintenance.execution.started": "정비 착수", "maintenance.execution.completed": "정비 완료",
  "inspection_coordination.requested": "생산 협의 요청", "inspection_coordination.confirmed": "생산 승인 완료",
};

// Resolve exact references from the product packet, never a raw data file or arbitrary URL.
export function resolveBriefingEvidence(packet: OperationsAgentReviewPacket, refs: string[]): BriefingEvidenceItem[] {
  const allowed = new Set(packet.source_refs);
  const selected = new Set(refs.filter(ref => allowed.has(ref)));
  const items: BriefingEvidenceItem[] = [];
  const add = (ref: string | null | undefined, item: BriefingEvidenceItem) => {
    if (ref && selected.has(ref)) items.push(item);
  };
  const snapshot = packet.snapshot_basis;
  const risk = packet.risk_summary;
  const grades: Record<string, string> = { normal: "정상", attention: "주의", warning: "경고", critical: "위험" };
  if (snapshot) {
    const text = [
      risk?.status_grade ? `위험 상태: ${grades[risk.status_grade] ?? risk.status_grade}` : "위험 상태: 확인 필요",
      risk?.failure_probability != null ? `고장 확률: ${(risk.failure_probability * 100).toFixed(1)}%` : "고장 확률: 미산정",
      snapshot.observed_at ? `관측 시각: ${evidenceTime(snapshot.observed_at)}` : "",
      
    ].filter(Boolean).join(" · ");
    for (const ref of [snapshot.artifact_id, snapshot.evidence_payload_reference]) {
      add(ref, { id: "prediction-snapshot", title: "예측 결과와 관측 기준", text, paths: [], details: [...new Set((packet.evidence_gaps ?? []).map(gapLabel))].map(value => ({ label: "확인 필요", value })) });
    }
  }
  for (const basis of packet.evidence_context?.selected_basis ?? []) {
    add(basis.source_ref, { id: basis.candidate_id, title: titles[basis.fact_type] ?? "연결 근거",
      text: basis.display_fields?.length ? basis.display_fields.map(field => `${field.label}: ${field.value}`).join(" · ") : basis.value_summary, paths: basis.relation_paths ?? [] });
  }
  for (const factor of packet.model_expression_context?.top_factors ?? []) {
    add(factor.source_ref, { id: factor.source_ref, title: factor.display_name,
      text: `${factor.value ?? "관측값 없음"}${factor.unit ? ` ${factor.unit}` : ""}`, paths: [] });
  }
  for (const target of packet.inspection_targets ?? []) {
    for (const ref of [target.source_ref, target.location_source_ref, ...target.basis_refs]) {
      add(ref, { id: target.target_id, title: target.component_label,
        text: [target.location_label, target.inspection_method, target.unavailable_reason].filter(Boolean).join(" · "), paths: [] });
    }
  }
  for (const sop of packet.sop_guidance ?? []) {
    add(sop.source_ref, { id: sop.sop_id, title: `${sop.component_label} 점검 절차`, text: sop.checklist_draft.join(" · "), paths: [] });
  }
  const context = packet.operation_context_summary;
  if (context) add(context.source_ref, { id: "production-context", title: "생산 영향", text: context.basis, paths: [] });
  const history = packet.maintenance_history_summary;
  if (history) {
    for (const [key, title] of [["work_orders", "작업요청"], ["inspection_results", "점검 결과"],
      ["maintenance_actions", "정비 조치"], ["maintenance_events", "정비 기록"], ["activities", "활동 기록"],
      ["equipment_history", "설비 이력"], ["recent_equipment_history", "설비 이력"], ["similar_events", "유사 사례"]]) {
      const records = (history as unknown as Record<string, unknown>)[key];
      if (!Array.isArray(records)) continue;
      for (const record of records as Record<string, unknown>[]) {
        const ref = typeof record.source_ref === "string" ? record.source_ref : null;
        const labels: Record<string, string> = { maintenance_recommended: "정비 필요", no_action_required: "조치 불필요",
          inspection_completed_pending_production_approval: "점검 완료 · 생산 승인 대기",
          production_approval_confirmed: "생산 승인 완료", production_changes_requested: "생산 재협의 요청" };
        const findings = Array.isArray(record.findings) ? record.findings.filter(value => typeof value === "string") : [];
        const coordination = record.production_coordination as { status?: string; request?: {work_summary?: string; downtime_minutes?: number; affected_items?: string}; response?: {scheduled_window?: string} } | undefined;
        const details: {label: string; value: string}[] = [];
        let text = [...new Set([record.summary, record.description, record.action_taken, ...findings, record.outcome, record.status]
          .filter((value): value is string => typeof value === "string" && Boolean(value))
          .map(value => labels[value] ?? value))].join(" · ");
        if (coordination) {
          text = ({pending: "점검 완료 · 생산 승인 대기", confirmed: "생산 승인 완료", changes_requested: "생산 재협의 요청"} as Record<string,string>)[coordination.status ?? ""] ?? "생산 협의 상태 확인 필요";
          const request = coordination.request;
          if (request?.work_summary) details.push({label: "정비 내용", value: request.work_summary});
          if (request?.downtime_minutes != null) details.push({label: "요청 정지 시간", value: `${request.downtime_minutes}분`});
          if (request?.affected_items) details.push({label: "생산 영향", value: request.affected_items});
          if (coordination.response?.scheduled_window) details.push({label: "승인 일정", value: coordination.response.scheduled_window});
        }
        const stamp = record.recorded_at ?? record.occurred_at ?? record.observed_at;
        if (stamp) details.push({label: "기록 시각", value: evidenceTime(stamp)});
        const displayTitle = key === "activities" ? activityLabels[String(record.activity_type)] ?? "업무 활동 기록" : title;
        if (key === "activities" && !text) text = "해당 사건에 연결된 활동입니다.";
        add(ref, { id: String(record.record_id ?? record.similar_event_id ?? ref), title: displayTitle, text, details, paths: [] });
      }
    }
  }
  for (const traversal of packet.ontology_context?.traversals ?? []) {
    for (const part of traversal.spare_parts) {
      add(part.source_ref, { id: part.part_id, title: part.part_label,
        text: [part.replacement_scope, part.lead_time_days != null ? `조달 ${part.lead_time_days}일` : "",
          part.replacement_window_minutes != null ? `교체 작업 ${part.replacement_window_minutes}분` : ""].filter(Boolean).join(" · "), paths: [] });
    }
  }
  return [...new Map(items.map(item => [item.id, item])).values()];
}

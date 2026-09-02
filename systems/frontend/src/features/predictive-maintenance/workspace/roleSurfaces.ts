import type { OperationsView } from "../../operations/api/operationsContracts";
import type {
  ReliabilityExperienceKind,
  ReliabilityLocalizedCopy,
  ReliabilityPageCopy,
} from "./roleExperience";

export type ReliabilitySurfaceId =
  | "executive-brief"
  | "operational-risk"
  | "executive-kpi"
  | "executive-reports"
  | "decision-bottleneck"
  | "maintenance-effect"
  | "roadmap"
  | "operations-status"
  | "pending-decisions"
  | "decision-case"
  | "production-impact"
  | "maintenance-approval"
  | "backlog"
  | "report-draft"
  | "monitoring"
  | "assets"
  | "sensor-features"
  | "inspection"
  | "maintenance-history"
  | "field-notes"
  | "my-work"
  | "work-targets"
  | "field-status"
  | "work-history";

export interface ReliabilitySurface {
  id: ReliabilitySurfaceId;
  view: OperationsView;
  label: ReliabilityLocalizedCopy;
  detail: ReliabilityLocalizedCopy;
  page: ReliabilityPageCopy;
}

function copy(ko: string, en: string): ReliabilityLocalizedCopy { return { ko, en }; }
function page(eyebrow: string, title: string, detail: string, eyebrowEn: string, titleEn: string, detailEn: string): ReliabilityPageCopy {
  return { eyebrow: copy(eyebrow, eyebrowEn), title: copy(title, titleEn), detail: copy(detail, detailEn) };
}

export const RELIABILITY_SURFACES: Record<ReliabilityExperienceKind, ReliabilitySurface[]> = {
  executive: [
    { id: "executive-brief", view: "reports", label: copy("Executive Brief", "Executive Brief"), detail: copy("경영 요약 · 보고 준비", "Executive summary · reporting"), page: page("경영 브리핑", "운영 리스크와 경영 보고", "실시간 공장 현황 위에 생산 영향, KPI, 핵심 Decision Case와 보고 초안을 연결합니다.", "EXECUTIVE BRIEF", "Operational risk and executive reporting", "Connect live factory status to production impact, KPI, critical Decision Cases, and reporting." ) },
    { id: "decision-bottleneck", view: "operations", label: copy("의사결정 병목", "Decision bottlenecks"), detail: copy("지연 · Owner · Backlog", "Delay · owner · backlog"), page: page("의사결정 병목", "지연 중인 핵심 판단", "판단이 지연된 Case와 다음 책임자, 생산 영향의 크기를 함께 봅니다.", "DECISION BOTTLENECKS", "Delayed critical decisions", "Review delayed cases, accountable owners, and production impact together." ) },
    { id: "operational-risk", view: "overview", label: copy("운영 리스크", "Operational risk"), detail: copy("공장 · 라인 · 위험", "Plant · line · risk"), page: page("운영 리스크", "생산 연속성 위험", "공장과 라인 단위의 위험 분포와 우선 대응 대상을 확인합니다.", "OPERATIONAL RISK", "Production continuity risk", "Review plant and line risk distribution and the highest-priority exposures." ) },
    { id: "maintenance-effect", view: "objects", label: copy("정비 효과", "Maintenance effect"), detail: copy("Before-after · 재발", "Before-after · recurrence"), page: page("정비 효과", "정비 이후 위험 변화", "과거 정비와 현재 위험을 연결해 before-after와 재발 여부를 확인합니다.", "MAINTENANCE EFFECT", "Risk after maintenance", "Connect maintenance history to current risk for before-after and recurrence review." ) },
  ],
  operations: [
    { id: "pending-decisions", view: "operations", label: copy("판단 대기", "Pending decisions"), detail: copy("우선순위 · SLA", "Priority · SLA"), page: page("판단 대기", "지금 판단해야 할 항목", "생산 영향이 큰 항목부터 다음 운영 판단과 Owner를 확인합니다.", "PENDING DECISIONS", "Decisions required now", "Prioritize high-impact cases and review the next operational decision and owner." ) },
    { id: "operations-status", view: "overview", label: copy("운영 현황", "Operations status"), detail: copy("실시간 KPI · 상태맵", "Live KPI · factory map"), page: page("운영 현황", "생산 리스크와 조치 현황", "실시간 공장 상태와 판단 대기 항목을 함께 확인합니다.", "OPERATIONS STATUS", "Production risk and response", "Review live factory status together with work requiring decisions." ) },
    { id: "production-impact", view: "objects", label: copy("생산 영향", "Production impact"), detail: copy("수량 · 비용 · 제품", "Units · cost · product"), page: page("생산 영향", "설비 위험의 운영 영향", "예상 정지, 계획 손실 수량, 제품 경제성과 자재 제약을 연결합니다.", "PRODUCTION IMPACT", "Operational impact of asset risk", "Connect downtime, planned unit loss, product economics, and material constraints." ) },
    { id: "report-draft", view: "reports", label: copy("보고 초안", "Report draft"), detail: copy("Decision Packet · 경영 전환", "Decision packet · executive handoff"), page: page("보고 초안", "운영 판단 보고", "같은 Case의 근거와 판단을 경영진이 사용할 수 있는 보고 언어로 전환합니다.", "REPORT DRAFT", "Operational decision report", "Transform the same case evidence and decisions into executive-ready reporting language." ) },
  ],
  engineering: [
    { id: "monitoring", view: "overview", label: copy("모니터링", "Monitoring"), detail: copy("상태맵 · 위험 알림", "Factory map · risk alerts"), page: page("모니터링", "조사가 필요한 설비", "실시간 상태맵과 이상 신호에서 조사 우선순위를 좁혀갑니다.", "MONITORING", "Assets requiring investigation", "Narrow investigation priority from live factory state and abnormal signals." ) },
    { id: "assets", view: "objects", label: copy("설비 · 센서 피쳐", "Assets · sensor features"), detail: copy("실시간 피쳐 · 이상 센서", "Live features · abnormal sensors"), page: page("설비 진단", "설비 신호와 원인 근거", "선택 설비의 센서 추세, 모델 기여와 정비 이력을 함께 분석합니다.", "ASSET ANALYSIS", "Equipment signals and causal evidence", "Analyze sensor trends, model contribution, and maintenance history for the selected asset." ) },
    { id: "inspection", view: "operations", label: copy("점검 · 정비 이력", "Inspection · maintenance"), detail: copy("점검 실행 · 과거 조치", "Inspection · past actions"), page: page("점검 기록", "점검 대상과 정비 이력", "근거에 연결된 점검 위치와 checklist, 과거 정비 기록을 함께 확인합니다.", "INSPECTION RECORD", "Inspection targets and maintenance history", "Review grounded inspection targets and checklists together with past maintenance records." ) },
    { id: "field-notes", view: "reports", label: copy("현장 메모 · 분석 보고", "Field notes · analysis report"), detail: copy("근거 정리 · 공유", "Evidence summary · sharing"), page: page("분석 보고", "근거 기반 현장 기록", "현장 관측, 남은 불확실성과 handoff 내용을 Evidence와 연결해 정리합니다.", "ANALYSIS REPORT", "Evidence-based field record", "Connect field observations, uncertainty, and handoff notes to evidence." ) },
  ],
  maintenance: [
    { id: "my-work", view: "operations", label: copy("내 작업", "My work"), detail: copy("승인 작업 · 진행 상태", "Approved work · progress"), page: page("내 작업", "승인된 현장 작업", "어디에서 무엇을 해야 하는지와 현재 작업 순서를 먼저 확인합니다.", "MY WORK", "Approved field work", "Start with where to go, what to do, and the current work sequence." ) },
    { id: "work-targets", view: "objects", label: copy("작업 대상", "Work targets"), detail: copy("위치 · 상태 · 근거", "Location · condition · evidence"), page: page("작업 대상", "설비 위치와 현장 근거", "승인된 작업에 필요한 설비 위치, 상태, 점검 근거와 자재를 확인합니다.", "WORK TARGETS", "Asset location and field evidence", "Review asset location, condition, inspection evidence, and materials needed for approved work." ) },
    { id: "field-status", view: "overview", label: copy("현장 현황", "Field status"), detail: copy("점검 · 정비 진행", "Inspection · maintenance progress"), page: page("현장 현황", "현장 작업 진행 상태", "현재 점검과 정비가 어느 단계에 있고 무엇이 남았는지 확인합니다.", "FIELD STATUS", "Field work status", "See the current stage of inspection and maintenance work and what remains." ) },
    { id: "work-history", view: "reports", label: copy("작업 이력", "Work history"), detail: copy("완료 결과 · 기록", "Completion · records"), page: page("작업 이력", "완료 작업과 실행 이력", "완료 결과와 현장 기록을 통해 작업 이력을 추적합니다.", "WORK HISTORY", "Completed work and execution history", "Trace work through completion results and field records." ) },
  ],
};

export function reliabilitySurfaces(kind: ReliabilityExperienceKind): ReliabilitySurface[] {
  return RELIABILITY_SURFACES[kind];
}

export function defaultReliabilitySurface(kind: ReliabilityExperienceKind): ReliabilitySurface {
  return RELIABILITY_SURFACES[kind][0];
}

export function resolveReliabilitySurface(kind: ReliabilityExperienceKind, surfaceId: string | null | undefined): ReliabilitySurface {
  return RELIABILITY_SURFACES[kind].find((item) => item.id === surfaceId) ?? defaultReliabilitySurface(kind);
}

export function reliabilitySurfaceForView(kind: ReliabilityExperienceKind, view: OperationsView): ReliabilitySurface {
  return RELIABILITY_SURFACES[kind].find((item) => item.view === view) ?? defaultReliabilitySurface(kind);
}

import { displaySensorFactorLabel, humanizeOperationalText } from "../displayLabels";

const TERMS: Record<string, string> = {
  "Smart Factory A": "스마트 공장 A", "Production Reliability": "설비 신뢰성 관리",
  "Unassigned · policy review": "미배정 · 조치 기준 검토", Unassigned: "미배정",
  maintenance_context_missing_or_unresolved: "정비 이력과 작업 조건이 연결되지 않았습니다.",
  operation_context_missing_or_unresolved: "생산 일정·작업 조건의 연결을 확인해야 합니다.",
  model_unit: "모델 환산값", "model unit": "모델 환산값",
  unknown: "확인 필요", stale: "갱신 지연", aligned: "시점 일치",
  missing: "미연결", unresolved: "연결 확인 필요", conflicting: "근거 충돌",
  process_manager: "생산 관리자", process_engineer: "공정 엔지니어",
  maintenance_technician: "보전 담당자", system_admin: "시스템 관리자",
  inspection: "현장 점검", maintenance: "정비 작업", requested: "요청 접수",
  approved: "작업 승인", in_progress: "작업 중", completed: "작업 완료",
};
export function fieldText(value: string | null | undefined, fallback = "확인 필요"): string {
  if (!value) return fallback;
  return TERMS[value] ?? humanizeOperationalText(value);
}
export function lineLabel(value: string): string {
  const match = value.match(/S(\d+)(?:\s*\/\s*S\d+)?-L(\d+)/i);
  return match ? `${Number(match[1])}구역 · ${Number(match[2])}셀` : fieldText(value);
}
export function factorLabel(key: string, fallback?: string): string {
  return displaySensorFactorLabel(key, fallback);
}
export function measurement(value: number | string | boolean | null, unit?: string | null): string {
  if (value === null) return "관측값 없음";
  const shown = typeof value === "number" ? value.toLocaleString("ko-KR", { maximumFractionDigits: 3 }) : String(value);
  return `${shown}${unit ? ` ${fieldText(unit)}` : ""}`;
}

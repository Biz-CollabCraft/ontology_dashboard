import type { OperationsView } from "../../operations/api/operationsContracts";
import type { ReliabilityExperienceKind } from "./roleExperience";
import type { ReliabilitySurfaceId } from "./roleSurfaces";

export type ReliabilityBlockId =
  | "risk-metrics"
  | "factory-map"
  | "business-kpis"
  | "risk-portfolio"
  | "line-risk"
  | "risk-queue"
  | "asset-brief"
  | "production-exposure"
  | "decision-queue"
  | "workflow-lifecycle"
  | "workflow-actions"
  | "sensor-signals"
  | "feature-trend"
  | "evidence-factors"
  | "inspection-targets"
  | "maintenance-history"
  | "material-context"
  | "decision-history"
  | "report-summary"
  | "context-evidence"
  | "data-quality";

export interface ReliabilityCompositionSignals {
  hasCriticalRisk: boolean;
  hasDataQualityHold: boolean;
  hasOpenWorkflow: boolean;
  hasMaterialConstraint: boolean;
}

const COMPOSITIONS: Record<ReliabilityExperienceKind, Record<Exclude<OperationsView, "system">, ReliabilityBlockId[]>> = {
  executive: {
    reports: ["risk-metrics", "factory-map", "report-summary", "business-kpis", "production-exposure", "decision-queue", "risk-portfolio", "context-evidence"],
    operations: ["decision-queue", "production-exposure", "workflow-lifecycle", "business-kpis", "risk-queue", "context-evidence"],
    overview: ["risk-metrics", "factory-map", "risk-portfolio", "business-kpis", "line-risk", "risk-queue", "context-evidence"],
    objects: ["asset-brief", "production-exposure", "maintenance-history", "material-context", "evidence-factors"],
  },
  operations: {
    operations: ["risk-metrics", "factory-map", "decision-queue", "production-exposure", "workflow-lifecycle", "workflow-actions", "material-context", "context-evidence"],
    overview: ["risk-metrics", "factory-map", "risk-portfolio", "line-risk", "risk-queue", "decision-queue", "business-kpis"],
    objects: ["asset-brief", "production-exposure", "maintenance-history", "material-context", "evidence-factors", "context-evidence"],
    reports: ["report-summary", "production-exposure", "decision-history", "business-kpis", "context-evidence"],
  },
  engineering: {
    overview: ["risk-metrics", "factory-map", "risk-queue", "feature-trend", "sensor-signals", "evidence-factors", "inspection-targets", "maintenance-history"],
    objects: ["asset-brief", "feature-trend", "sensor-signals", "evidence-factors", "maintenance-history", "material-context", "context-evidence"],
    operations: ["inspection-targets", "workflow-lifecycle", "workflow-actions", "maintenance-history", "decision-history", "evidence-factors"],
    reports: ["report-summary", "evidence-factors", "maintenance-history", "context-evidence"],
  },
  maintenance: {
    operations: ["risk-metrics", "factory-map", "workflow-lifecycle", "workflow-actions", "inspection-targets", "asset-brief", "material-context", "maintenance-history"],
    objects: ["asset-brief", "inspection-targets", "sensor-signals", "maintenance-history", "material-context"],
    overview: ["risk-metrics", "factory-map", "workflow-lifecycle", "risk-queue", "material-context", "maintenance-history"],
    reports: ["maintenance-history", "decision-history", "report-summary", "context-evidence"],
  },
};

const SURFACE_COMPOSITIONS: Partial<Record<ReliabilitySurfaceId, ReliabilityBlockId[]>> = {
  "executive-brief": ["report-summary", "business-kpis", "production-exposure", "decision-queue", "risk-portfolio", "context-evidence"],
  "operational-risk": ["risk-metrics", "factory-map", "risk-portfolio", "line-risk", "risk-queue"],
  "executive-kpi": ["risk-metrics", "business-kpis", "production-exposure", "decision-history", "line-risk"],
  "executive-reports": ["report-summary", "business-kpis", "decision-history", "context-evidence"],
  "decision-bottleneck": ["risk-metrics", "decision-queue", "workflow-lifecycle", "production-exposure", "context-evidence"],
  "maintenance-effect": ["maintenance-history", "production-exposure", "risk-portfolio", "material-context", "context-evidence"],
  roadmap: ["business-kpis", "decision-history", "maintenance-history", "material-context", "context-evidence"],

  "operations-status": ["risk-metrics", "factory-map", "line-risk", "risk-queue", "decision-queue"],
  "pending-decisions": ["risk-metrics", "decision-queue", "production-exposure", "workflow-lifecycle", "workflow-actions", "material-context", "context-evidence"],
  "decision-case": ["asset-brief", "decision-queue", "production-exposure", "evidence-factors", "workflow-lifecycle", "decision-history", "context-evidence"],
  "production-impact": ["production-exposure", "business-kpis", "material-context", "risk-queue", "line-risk"],
  "maintenance-approval": ["workflow-lifecycle", "workflow-actions", "inspection-targets", "material-context", "maintenance-history"],
  backlog: ["risk-metrics", "decision-queue", "decision-history", "line-risk", "context-evidence"],
  "report-draft": ["report-summary", "production-exposure", "decision-history", "business-kpis", "context-evidence"],

  monitoring: ["risk-metrics", "factory-map", "risk-queue", "feature-trend", "sensor-signals", "evidence-factors"],
  assets: ["asset-brief", "feature-trend", "sensor-signals", "evidence-factors", "maintenance-history", "material-context"],
  "sensor-features": ["feature-trend", "sensor-signals", "evidence-factors", "maintenance-history"],
  inspection: ["inspection-targets", "workflow-lifecycle", "workflow-actions", "evidence-factors", "maintenance-history"],
  "maintenance-history": ["maintenance-history", "material-context", "decision-history", "evidence-factors"],
  "field-notes": ["decision-history", "report-summary", "inspection-targets", "context-evidence"],

  "my-work": ["risk-metrics", "factory-map", "workflow-lifecycle", "workflow-actions", "inspection-targets", "material-context"],
  "work-targets": ["asset-brief", "inspection-targets", "material-context", "feature-trend", "maintenance-history"],
  "field-status": ["risk-metrics", "factory-map", "workflow-lifecycle", "risk-queue", "maintenance-history"],
  "work-history": ["maintenance-history", "decision-history", "report-summary", "context-evidence"],
};

function promote(blocks: ReliabilityBlockId[], id: ReliabilityBlockId, position = 0): ReliabilityBlockId[] {
  const next = blocks.filter((item) => item !== id);
  next.splice(Math.max(0, Math.min(position, next.length)), 0, id);
  return next;
}

export function resolveReliabilityComposition(
  kind: ReliabilityExperienceKind,
  view: OperationsView,
  signals: ReliabilityCompositionSignals,
  surfaceId?: string | null,
): ReliabilityBlockId[] {
  if (view === "system") return [];
  const surfaceBlocks = surfaceId ? SURFACE_COMPOSITIONS[surfaceId as ReliabilitySurfaceId] : null;
  let blocks = [...(surfaceBlocks ?? COMPOSITIONS[kind][view])];
  if (signals.hasDataQualityHold) {
    blocks = ["data-quality", ...blocks.filter((item) => item !== "data-quality")];
  }
  if (signals.hasOpenWorkflow) {
    blocks = promote(blocks, "workflow-lifecycle", signals.hasDataQualityHold ? 1 : 0);
  }
  if (signals.hasMaterialConstraint && (kind === "operations" || kind === "executive" || kind === "maintenance")) {
    blocks = promote(blocks, "material-context", Math.min(2, blocks.length));
  }
  if (signals.hasCriticalRisk && kind === "executive") {
    blocks = promote(blocks, "production-exposure", signals.hasDataQualityHold ? 1 : 0);
  }
  return blocks;
}

export function baseReliabilityComposition(
  kind: ReliabilityExperienceKind,
  view: Exclude<OperationsView, "system">,
): ReliabilityBlockId[] {
  return [...COMPOSITIONS[kind][view]];
}

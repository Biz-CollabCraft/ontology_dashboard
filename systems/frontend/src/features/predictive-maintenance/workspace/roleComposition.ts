import type { OperationsView } from "../../operations/api/operationsContracts";
import type { ReliabilityExperienceKind } from "./roleExperience";
import type { ReliabilitySurfaceId } from "./roleSurfaces";

export type ReliabilityBlockId =
  | "risk-metrics"
  | "factory-map"
  | "business-kpis"
  | "operational-kpis"
  | "risk-portfolio"
  | "line-risk"
  | "risk-queue"
  | "asset-brief"
  | "production-exposure"
  | "decision-queue"
  | "workflow-lifecycle"
  | "case-lineage"
  | "workflow-actions"
  | "sensor-signals"
  | "feature-trend"
  | "evidence-factors"
  | "inspection-targets"
  | "maintenance-history"
  | "maintenance-effect"
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
  hasDecisionBacklog: boolean;
  hasHighProductionExposure: boolean;
  hasMaintenanceOutcome: boolean;
}

const COMPOSITIONS: Record<ReliabilityExperienceKind, Record<Exclude<OperationsView, "system">, ReliabilityBlockId[]>> = {
  executive: {
    reports: ["risk-metrics", "operational-kpis", "report-summary", "production-exposure", "decision-queue", "case-lineage", "business-kpis", "risk-portfolio", "context-evidence"],
    operations: ["operational-kpis", "decision-queue", "production-exposure", "case-lineage", "workflow-lifecycle", "business-kpis", "risk-queue", "context-evidence"],
    overview: ["risk-metrics", "factory-map", "operational-kpis", "risk-portfolio", "business-kpis", "line-risk", "risk-queue", "context-evidence"],
    objects: ["asset-brief", "production-exposure", "case-lineage", "maintenance-effect", "maintenance-history", "material-context", "evidence-factors"],
  },
  operations: {
    operations: ["risk-metrics", "operational-kpis", "decision-queue", "production-exposure", "case-lineage", "workflow-lifecycle", "workflow-actions", "material-context", "context-evidence"],
    overview: ["risk-metrics", "factory-map", "operational-kpis", "risk-portfolio", "line-risk", "risk-queue", "decision-queue", "business-kpis"],
    objects: ["asset-brief", "production-exposure", "case-lineage", "maintenance-history", "maintenance-effect", "material-context", "evidence-factors", "context-evidence"],
    reports: ["report-summary", "operational-kpis", "production-exposure", "case-lineage", "decision-history", "business-kpis", "context-evidence"],
  },
  engineering: {
    overview: ["risk-metrics", "factory-map", "risk-queue", "feature-trend", "sensor-signals", "evidence-factors", "case-lineage", "inspection-targets", "maintenance-history"],
    objects: ["asset-brief", "feature-trend", "sensor-signals", "evidence-factors", "case-lineage", "maintenance-history", "maintenance-effect", "material-context", "context-evidence"],
    operations: ["inspection-targets", "case-lineage", "workflow-lifecycle", "workflow-actions", "maintenance-history", "decision-history", "evidence-factors"],
    reports: ["report-summary", "evidence-factors", "maintenance-history", "context-evidence"],
  },
  maintenance: {
    operations: ["risk-metrics", "case-lineage", "workflow-lifecycle", "workflow-actions", "inspection-targets", "asset-brief", "material-context", "maintenance-history", "maintenance-effect"],
    objects: ["asset-brief", "inspection-targets", "sensor-signals", "case-lineage", "maintenance-history", "maintenance-effect", "material-context"],
    overview: ["risk-metrics", "factory-map", "case-lineage", "workflow-lifecycle", "risk-queue", "material-context", "maintenance-history"],
    reports: ["maintenance-effect", "maintenance-history", "decision-history", "report-summary", "context-evidence"],
  },
};

const SURFACE_COMPOSITIONS: Partial<Record<ReliabilitySurfaceId, ReliabilityBlockId[]>> = {
  "executive-brief": ["operational-kpis", "report-summary", "production-exposure", "decision-queue", "case-lineage", "business-kpis", "risk-portfolio", "context-evidence"],
  "operational-risk": ["risk-metrics", "factory-map", "operational-kpis", "risk-portfolio", "line-risk", "risk-queue"],
  "executive-kpi": ["operational-kpis", "risk-metrics", "business-kpis", "production-exposure", "decision-history", "line-risk"],
  "executive-reports": ["report-summary", "operational-kpis", "case-lineage", "business-kpis", "decision-history", "context-evidence"],
  "decision-bottleneck": ["operational-kpis", "decision-queue", "case-lineage", "workflow-lifecycle", "production-exposure", "context-evidence"],
  "maintenance-effect": ["maintenance-effect", "maintenance-history", "production-exposure", "risk-portfolio", "material-context", "context-evidence"],
  roadmap: ["business-kpis", "decision-history", "maintenance-history", "material-context", "context-evidence"],

  "operations-status": ["risk-metrics", "factory-map", "operational-kpis", "line-risk", "risk-queue", "decision-queue"],
  "pending-decisions": ["operational-kpis", "risk-metrics", "decision-queue", "production-exposure", "case-lineage", "workflow-lifecycle", "workflow-actions", "material-context", "context-evidence"],
  "decision-case": ["asset-brief", "case-lineage", "decision-queue", "production-exposure", "evidence-factors", "workflow-lifecycle", "decision-history", "context-evidence"],
  "production-impact": ["production-exposure", "business-kpis", "material-context", "risk-queue", "line-risk"],
  "maintenance-approval": ["case-lineage", "workflow-lifecycle", "workflow-actions", "inspection-targets", "material-context", "maintenance-history", "maintenance-effect"],
  backlog: ["operational-kpis", "risk-metrics", "decision-queue", "decision-history", "line-risk", "context-evidence"],
  "report-draft": ["report-summary", "operational-kpis", "case-lineage", "production-exposure", "decision-history", "business-kpis", "context-evidence"],

  monitoring: ["risk-metrics", "factory-map", "risk-queue", "feature-trend", "sensor-signals", "evidence-factors", "case-lineage"],
  assets: ["asset-brief", "feature-trend", "sensor-signals", "evidence-factors", "case-lineage", "maintenance-history", "maintenance-effect", "material-context"],
  "sensor-features": ["feature-trend", "sensor-signals", "evidence-factors", "maintenance-history"],
  inspection: ["inspection-targets", "case-lineage", "workflow-lifecycle", "workflow-actions", "evidence-factors", "maintenance-history"],
  "maintenance-history": ["maintenance-effect", "maintenance-history", "material-context", "decision-history", "evidence-factors"],
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
  if (signals.hasDecisionBacklog && kind === "operations") {
    blocks = promote(blocks, "decision-queue", signals.hasDataQualityHold ? 1 : 0);
  }
  if (signals.hasCriticalRisk && kind === "engineering") {
    blocks = promote(blocks, "feature-trend", signals.hasDataQualityHold ? 1 : 0);
    blocks = promote(blocks, "evidence-factors", signals.hasDataQualityHold ? 2 : 1);
  }
  if (signals.hasHighProductionExposure && kind === "executive") {
    blocks = promote(blocks, "production-exposure", signals.hasDataQualityHold ? 1 : 0);
  }
  if (signals.hasMaintenanceOutcome) {
    blocks = promote(blocks, "maintenance-effect", Math.min(signals.hasDataQualityHold ? 2 : 1, blocks.length));
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

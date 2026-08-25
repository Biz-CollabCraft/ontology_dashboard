export type MvpView = "overview" | "objects" | "operations" | "reports";
export type MvpReportTab = "status-map" | "inspection-request" | "summary-report" | "executive-brief";
export type MvpRoleLens = "process_manager" | "field_operator";
export type MvpRiskStatus = "normal" | "attention" | "warning" | "critical" | "data_quality_hold";
export type MvpConfidence = "high" | "medium" | "low" | "unavailable";
export type MvpCriticality = "low" | "medium" | "high" | null;
export type MvpDecision =
  | "continue_monitoring"
  | "request_inspection"
  | "review_shutdown"
  | "hold_for_data_check";

export type MvpSourceMode = "canonical-runtime" | "gold-fixture-fallback";

export interface MvpProvenance {
  datasetId: string | null;
  datasetVersionId: string;
  datasetLabel: string;
  sourceVersion: string | null;
  modelVersion: string | null;
  policyVersion: string | null;
  schemaVersion: string | null;
  promptVersion: string | null;
  sourceRefs: string[];
}

export interface MvpFactor {
  id: string;
  feature: string;
  label: string;
  value: number | null;
  unit: string | null;
  contribution: number;
  direction: "risk_up" | "risk_down";
  explanationMethod: string | null;
}

export interface MvpAsset {
  assetId: string;
  displayName: string;
  assetType: string;
  site: string;
  line: string;
  cell: string;
  status: MvpRiskStatus;
  failureProbability: number | null;
  confidence: MvpConfidence;
  confidenceScore: number | null;
  criticality: MvpCriticality;
  assignedEngineer: string | null;
  estimatedDowntimeMinutes: number | null;
  sparePartAvailable: boolean | null;
  predictedFailureType: string;
  recommendedDecision: MvpDecision;
  observedAt: string | null;
  eventId: string | null;
  topFactors: MvpFactor[];
  provenance: MvpProvenance;
}

export interface MvpEvent {
  eventId: string;
  scenarioId: string;
  assetId: string;
  assetName: string;
  line: string;
  status: MvpRiskStatus;
  failureProbability: number | null;
  confidence: MvpConfidence;
  predictedFailureType: string;
  recommendedDecision: MvpDecision;
  criticality: MvpCriticality;
  assignedEngineer: string | null;
  estimatedDowntimeMinutes: number | null;
  sparePartAvailable: boolean | null;
  observedAt: string | null;
  datasetVersionId: string;
  ontologyObjectId: string | null;
}

export interface MvpMetrics {
  totalAssets: number;
  normal: number;
  attention: number;
  warning: number;
  critical: number;
  dataQualityHold: number;
  averageRisk: number | null;
  estimatedDowntimeMinutes: number | null;
  pendingDecisions: number;
}

export interface MvpLineRisk {
  line: string;
  total: number;
  normal: number;
  critical: number;
  warning: number;
  attention: number;
  dataQualityHold: number;
  averageRisk: number | null;
}

export interface MvpContextModel {
  projectId: string;
  projectName: string;
  workspaceId: string;
  workspaceName: string;
  datasetVersionId: string;
  datasetLabel: string;
  sourceVersion: string | null;
  modelVersion: string | null;
  schemaVersion: string | null;
  sourceMode: MvpSourceMode;
  sourceStatus: string;
  refreshedAt: string;
  observedAt: string | null;
  stale: boolean;
  warnings: string[];
}

export interface MvpBootstrapModel {
  context: MvpContextModel;
  assets: MvpAsset[];
  events: MvpEvent[];
  metrics: MvpMetrics;
  lineRisk: MvpLineRisk[];
}

export interface MvpSensorValue {
  id: string;
  label: string;
  value: number | string | boolean | null;
  unit: string | null;
  observedAt?: string | null;
  qualityStatus?: "good" | "bad" | "unknown";
  historySourceRef?: string | null;
  historyPointCount?: number;
  historyPoints?: MvpFeatureHistoryPoint[];
}

export interface MvpFeatureHistoryPoint {
  observedAt: string;
  value: number | null;
  qualityStatus: "good" | "bad" | "unknown";
}

export interface MvpRiskSeriesPoint {
  observedAt: string;
  failureProbability: number;
  status: "normal" | "attention" | "warning" | "critical" | null;
}

export interface MvpActivityItem {
  id: string;
  kind: "decision" | "note" | "conversation" | "system";
  title: string;
  detail: string;
  actor: string;
  createdAt: string;
  decision: MvpDecision | null;
}

export interface MvpReportSection {
  id: string;
  title: string;
  body: string;
  evidenceFieldIds: string[];
}

export interface MvpReportModel {
  reportId: string;
  revision: number;
  mode: "llm" | "deterministic-fallback" | "template-fallback";
  headline: string;
  summary: string;
  sections: MvpReportSection[];
  actions: string[];
  limitations: string[];
  generatedAt: string;
  promptVersion: string | null;
}

export interface MvpEquipmentHistoryItem {
  occurredAt: string;
  kind: string;
  tone: "critical" | "warning" | "attention" | "normal" | "hold";
  description: string;
  source: string;
  memo: string | null;
}

export interface MvpEvidenceGap {
  field: string;
  reason: string;
  ownerDomain: string;
}

export interface MvpAssetDetailStatus {
  isStale: boolean | null;
  isDataQualityHold: boolean;
  lastUpdatedAt: string | null;
  source: "canonical" | "fallback";
}

export interface MvpEventDetailModel {
  event: MvpEvent;
  sensors: MvpSensorValue[];
  topFactors: MvpFactor[];
  riskSeries: MvpRiskSeriesPoint[];
  predictionHorizonHours: number | null;
  threshold: number | null;
  dataQualityWarnings: Array<{ code: string; field: string; message: string; severity: string }>;
  equipmentHistory: MvpEquipmentHistoryItem[];
  evidenceGaps: MvpEvidenceGap[];
  assetDetailStatus: MvpAssetDetailStatus | null;
  operationContext: {
    loadLevel: "low" | "normal" | "high" | null;
    runtimeHours7d: number | null;
    productionImpact: "none" | "low" | "medium" | "high" | null;
  } | null;
  reviewPriority: {
    level: "immediate" | "high" | "medium" | "low";
    reasons: string[];
    sourceFields: string[];
  } | null;
  activity: MvpActivityItem[];
  report: MvpReportModel;
  provenance: MvpProvenance;
  loadedSources: {
    evidence: boolean;
    report: boolean;
    activity: boolean;
  };
  warnings: string[];
}

export interface AssetDetailViewModel {
  asset: {
    asset_id: string;
    asset_type: "compressor" | "cnc";
    display_name?: string;
    site_id?: string;
    cell_id?: string;
    observed_at: string;
    criticality?: MvpCriticality;
    criticality_basis?: string[];
    criticality_source?: string;
  };
  risk: {
    current: number | null;
    threshold: number | null;
    status_grade: "normal" | "attention" | "warning" | "critical" | null;
    prediction_horizon_hours: number | null;
  };
  risk_series: Array<{
    observed_at: string;
    failure_probability: number;
    status_grade: "normal" | "attention" | "warning" | "critical" | null;
    prediction_id: string;
    source_kind: "runtime_inference" | "compatibility_fallback";
    source_ref?: string;
  }>;
  features: Array<{
    key: string;
    label: string;
    unit: string;
    current: {
      observed_at: string;
      value: number | null;
      quality_status: "good" | "bad" | "unknown";
    };
    history: {
      source_ref?: string;
      points: Array<{
        observed_at: string;
        value: number | null;
        quality_status: "good" | "bad" | "unknown";
      }>;
    };
    top_factor: {
      rank: number;
      contribution: number;
      direction: "risk_up" | "risk_down";
      explanation_method: string;
      evidence_field_id?: string;
    } | null;
  }>;
  equipment_history: Array<{
    occurred_at: string;
    kind: string;
    tone: "critical" | "warning" | "attention" | "normal" | "hold";
    description: string;
    source: string;
    memo?: string;
  }>;
  operation_context?: {
    load_level: "low" | "normal" | "high" | null;
    runtime_hours_7d: number | null;
    production_impact: "none" | "low" | "medium" | "high" | null;
  };
  review_priority?: {
    level: "immediate" | "high" | "medium" | "low";
    reasons: string[];
    source_fields: string[];
  } | null;
  evidence: {
    artifact_id: string | null;
    model_version: string | null;
    dataset_version: string | null;
    source_kind: "runtime_inference" | "compatibility_fallback";
    gaps: Array<{ field: string; reason: string; owner_domain: string }>;
  };
  data_status: {
    source: "canonical" | "fallback";
    is_stale: boolean | null;
    is_data_quality_hold: boolean;
    last_updated_at?: string;
    warnings: string[];
  };
}

export interface MvpSelection {
  view: MvpView;
  reportTab: MvpReportTab;
  projectId: string;
  workspaceId: string | null;
  assetId: string | null;
  eventId: string | null;
  role: MvpRoleLens;
}

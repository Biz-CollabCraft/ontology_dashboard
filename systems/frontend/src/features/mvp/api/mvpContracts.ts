export type MvpView = "overview" | "objects" | "operations" | "reports" | "system";
export type MvpDashboardMode = "workflow" | "classic";
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
export type MvpSensorWindowId = "24h" | "7d" | "30d";
export type MvpSensorWindowCoverage = "complete" | "partial" | "empty" | "unknown";

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

export interface MvpEvidenceSnapshotBasis {
  artifactId: string | null;
  evidencePayloadReference: string;
  assetId: string | null;
  eventId: string | null;
  observedAt: string | null;
  modelVersion: string | null;
  datasetVersion: string | null;
  sourceSha256: string | null;
}

export interface EvidenceSnapshotBasisWire {
  artifact_id: string | null;
  evidence_payload_reference: string;
  asset_id: string | null;
  event_id: string | null;
  observed_at: string | null;
  model_version: string | null;
  dataset_version: string | null;
  source_sha256: string | null;
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
  historyWindow?: MvpFeatureHistoryWindow | null;
  historyPoints?: MvpFeatureHistoryPoint[];
}

export interface MvpFeatureHistoryWindow {
  requested: MvpSensorWindowId;
  anchorObservedAt: string | null;
  requestedStart: string | null;
  requestedEnd: string | null;
  actualStart: string | null;
  actualEnd: string | null;
  pointCount: number;
  coverageStatus: MvpSensorWindowCoverage;
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

export type MvpProductionImpact = "none" | "low" | "medium" | "high" | null;
export type MvpOperationSourceType = "synthetic_capacity_model";
export type MvpScreenPriority = "none" | "monitor" | "shift_inspection" | "plan_at_risk" | "data_check_required";
export type MvpImpactStatus = "not_applicable" | "estimated" | "withheld_data_quality_hold";

export interface MvpOperationTemporalScope {
  snapshotId: string;
  timezone: string;
  validFrom: string;
  validTo: string;
  generatedAt: string;
}

export interface MvpProductionPlan {
  planId: string;
  planDate: string;
  plannedUnits: number;
  productMix: Array<{ variant: string; share: number; plannedUnits: number }>;
}

export interface MvpCapacityModel {
  activeAssetCount: number;
  plannedOperatingHours: number;
  oee: number;
  standardCycleMinutesPerUnit: number;
  assetUnitsPerHour: number;
  dailyCapacityUnits: number;
  basis: string;
}

export interface MvpEventImpact {
  eventId: string;
  equipmentId: string;
  line: string;
  productVariant: string;
  screenPriority: MvpScreenPriority;
  impactStatus: MvpImpactStatus;
  estimatedLostUnits: number | null;
  basis: {
    estimatedDowntimeMinutes: number;
    assetUnitsPerHour: number;
    formula: string;
  };
}

export interface MvpOperationContext {
  loadLevel: "low" | "normal" | "high" | null;
  runtimeHours7d: number | null;
  productionImpact: MvpProductionImpact;
  contextId?: string;
  sourceType?: MvpOperationSourceType;
  temporalScope?: MvpOperationTemporalScope;
  productionPlan?: MvpProductionPlan;
  capacityModel?: MvpCapacityModel;
  eventImpact?: MvpEventImpact | null;
  limitations?: string[];
}

export type MvpClosedLoopWorkType = "inspection" | "maintenance";
export type MvpClosedLoopWorkOrderStatus = "requested" | "approved" | "in_progress" | "completed" | "blocked" | "failed" | "cancelled";
export type MvpClosedLoopMaintenanceActionStatus = "planned" | "in_progress" | "completed" | "failed" | "cancelled";
export type MvpClosedLoopRuntimeStatus = "equipment_under_maintenance" | "warming_up" | "history_insufficient" | "ready" | "predicted" | null;
export type MvpClosedLoopLifecycleStep =
  | "prediction"
  | "evidence"
  | "decision"
  | "inspection_requested"
  | "inspection_approved"
  | "inspection_in_progress"
  | "inspection_completed"
  | "recommendation_proposed"
  | "maintenance_requested"
  | "maintenance_approved"
  | "maintenance_in_progress"
  | "maintenance_completed"
  | "post_maintenance_observation_pending"
  | "ready_for_reprediction";

export interface MvpClosedLoopAvailableAction {
  actionId: string;
  targetType: "recommendation" | "work_order" | "maintenance_action" | "inspection_result" | "event";
  targetId: string | null;
  label?: string;
  disabledReason?: string | null;
}

export interface MvpClosedLoopWorkOrder {
  workOrderId: string;
  workType: MvpClosedLoopWorkType;
  status: MvpClosedLoopWorkOrderStatus;
  assignedTo?: string | null;
  actorDisplayName?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
}

export interface MvpClosedLoopMaintenanceAction {
  maintenanceActionId: string;
  workOrderId: string | null;
  status: MvpClosedLoopMaintenanceActionStatus;
  actorDisplayName?: string | null;
  startedAt?: string | null;
  completedAt?: string | null;
}

export interface MvpClosedLoopMaintenanceEvent {
  maintenanceEventId: string;
  maintenanceActionId: string | null;
  workOrderId: string | null;
  completedAt: string | null;
  actorDisplayName?: string | null;
}

export interface MvpClosedLoopActivity {
  activityId: string;
  activityType: string;
  workType?: MvpClosedLoopWorkType | null;
  actorDisplayName?: string | null;
  beforeStatus?: string | null;
  afterStatus?: string | null;
  createdAt?: string | null;
  workOrderId?: string | null;
  maintenanceActionId?: string | null;
  maintenanceEventId?: string | null;
}

export interface MvpClosedLoopLifecycleSummary {
  currentStep: MvpClosedLoopLifecycleStep;
  currentStepLabel: string;
  completedSteps: MvpClosedLoopLifecycleStep[];
  nextStep: MvpClosedLoopLifecycleStep | null;
  source: "backend_closed_loop_policy";
}

export interface MvpClosedLoopPrimaryAction extends MvpClosedLoopAvailableAction {
  label: string;
  ownerRole: "process_manager" | "process_engineer" | "maintenance_technician" | "unassigned";
  ownerLabel: string;
  requiresInput: boolean;
}

export interface MvpClosedLoopTimelineItem {
  timelineId: string;
  eventType: string;
  label: string;
  status: "completed" | "pending" | "blocked" | "failed";
  actorDisplayName?: string | null;
  occurredAt?: string | null;
  targetType?: string | null;
  targetId?: string | null;
}

export interface MvpClosedLoopSummary {
  workOrders: MvpClosedLoopWorkOrder[];
  maintenanceActions: MvpClosedLoopMaintenanceAction[];
  maintenanceEvents: MvpClosedLoopMaintenanceEvent[];
  activities: MvpClosedLoopActivity[];
  availableActions: MvpClosedLoopAvailableAction[];
  lifecycleSummary: MvpClosedLoopLifecycleSummary | null;
  primaryAction: MvpClosedLoopPrimaryAction | null;
  timeline: MvpClosedLoopTimelineItem[];
  runtimeStatus: MvpClosedLoopRuntimeStatus;
}

export interface MvpInspectionGuidance {
  sourceType: "demo_sop_fixture" | "site_sop";
  sopId: string;
  title: string;
  version: string;
  referenceLocationLabel: string;
  suggestedCheckMethod: string;
  checklistDraft: string[];
  maintenanceReviewPrerequisites: {
    label: string;
    reviewConditions: string[];
    requiredMeasurements: string[];
    humanReviewQuestions: string[];
    decisionBoundary: string;
  };
  safetyLevel: "none" | "caution" | "permit_required" | "shutdown_controlled";
  requiresHumanApproval: boolean;
  sourceRef: string;
  disclaimer: string;
}

export interface MvpInspectionTarget {
  targetId: string;
  componentId: string;
  componentLabel: string;
  association: string;
  locationLabel: string | null;
  inspectionMethod: string | null;
  locationContractId: string | null;
  locationSourceRef: string | null;
  locationMaturity: "fixture" | "draft" | "approved" | "retired" | null;
  inspectionGuidance: MvpInspectionGuidance | null;
  basisRefs: string[];
  sourceRef: string;
  unavailableReason: string | null;
}

export interface MvpAgentReviewPacket {
  schema_version: "agent-review-packet-v1.0";
  project_id: string;
  asset_id: string;
  asset_label: string;
  generated_at: string;
  snapshot_basis: EvidenceSnapshotBasisWire;
  risk_summary: {
    status_grade: "normal" | "attention" | "warning" | "critical" | null;
    failure_probability: number | null;
    prediction_horizon_hours: number | null;
  };
  review_priority: {
    level: "immediate" | "high" | "medium" | "low";
    reasons: string[];
    source_fields: string[];
  } | null;
  review_draft: {
    title: string;
    summary: string;
    priority_label: string;
    recommended_next_step: string;
    checklist: string[];
    history_summary: string[];
    evidence_gap_count: number;
    boundary_note: string;
  };
  sop_retrieval: {
    provider: "local_sop_metadata_retriever";
    query: {
      asset_type: string;
      failure_mode: string;
      factor_keys: string[];
      component_ids: string[];
      risk_grade: string;
      criticality: string;
      production_impact: string;
    };
    top_k: number;
    returned_count: number;
    mutation_allowed: false;
  };
  sop_guidance: Array<{
    target_id: string;
    component_id: string;
    component_label: string;
    location_label: string | null;
    inspection_method: string | null;
    location_source_ref: string | null;
    sop_id: string;
    source_type: "demo_sop_fixture" | "site_sop";
    maturity: "fixture" | "draft" | "approved" | "retired";
    checklist_draft: string[];
    replacement_review_guidance: {
      review_label: string;
      review_triggers: string[];
      required_measurements: string[];
      operator_review_items: string[];
      decision_boundary: string;
    };
    sensor_judgment: Record<string, unknown> | null;
    retrieval_score: number;
    matched_fields: string[];
    disclaimer: string;
    source_ref: string;
  }>;
  inspection_targets: Array<{
    target_id: string;
    component_id: string;
    component_label: string;
    association: string;
    location_label: string | null;
    inspection_method: string | null;
    location_source_ref: string | null;
    basis_refs: string[];
    source_ref: string;
    unavailable_reason: string | null;
  }>;
  operation_context_summary?: {
    production_impact: "none" | "low" | "medium" | "high" | null;
    estimated_downtime_minutes: number | null;
    estimated_lost_units: number | null;
    product_variant: string | null;
    basis: string;
    limitations: string[];
    source_ref: string | null;
  } | null;
  model_expression_context: {
    source_type: string;
    model_version: string | null;
    dataset_version: string | null;
    failure_probability: number | null;
    threshold: number | null;
    confidence_label: string | null;
    top_factors: Array<{
      rank: number;
      feature: string;
      display_name: string;
      value: number | string | boolean | null;
      unit: string;
      contribution: number | null;
      direction: "positive" | "negative" | "risk_up" | "risk_down" | string;
      explanation_method: string;
      source_ref: string;
    }>;
    source_refs: string[];
  };
  maintenance_history_summary: {
    provider: string;
    mutation_allowed: false;
    open_work_order_exists: boolean | null;
    similar_events_30d: number | null;
    work_orders: Array<Record<string, unknown>>;
    inspection_results: Array<Record<string, unknown>>;
    maintenance_actions: Array<Record<string, unknown>>;
    maintenance_events: Array<Record<string, unknown>>;
    activities: Array<Record<string, unknown>>;
    equipment_history: Array<Record<string, unknown>>;
    similar_events: Array<Record<string, unknown>>;
    source_refs: string[];
  };
  ontology_context: {
    provider: string;
    mutation_allowed: false;
    traversals: Array<{
      component_id: string;
      component_label: string;
      factor_refs: string[];
      location_label: string | null;
      location_source_ref: string | null;
      sop_ids: string[];
      spare_parts: Array<{
        part_id: string;
        part_label: string;
        replacement_scope: string;
        availability: "available_from_fixture" | "unavailable_from_fixture" | "unknown";
        lead_time_days: number | null;
        replacement_window_minutes: number | null;
        assumption_level: string;
        source_ref: string;
      }>;
      similar_events: Array<{
        similar_event_id: string;
        asset_label: string;
        observed_at: string;
        matched_factor_keys: string[];
        action_taken: string;
        outcome: string;
        post_action_observation_window_hours: number | null;
        assumption_level: string;
        source_ref: string;
      }>;
      source_refs: string[];
    }>;
    source_refs: string[];
  };
  history_review_items: string[];
  evidence_gaps: Array<{ field: string; reason: string; owner_domain: string }>;
  source_refs: string[];
  closed_loop_boundary: {
    mutation_allowed: false;
    available_action_ids: string[];
    forbidden_actions: string[];
    note: string;
  };
  limitations: string[];
}

export interface MvpAgentReviewSummary {
  schema_version: "agent-review-summary-v1.0";
  packet_schema_version: "agent-review-packet-v1.0";
  asset_id: string;
  generated_at: string;
  mode: "llm" | "deterministic_fallback";
  title: string;
  summary: string;
  role_summaries: Array<{
    role: "field_operator" | "process_manager";
    label: string;
    quote: string;
    source_refs: string[];
  }>;
  history_summary: string[];
  inspection_focus: Array<{
    component_id: string;
    component_label: string;
    location_label: string | null;
    basis_refs: string[];
    source_refs: string[];
  }>;
  evidence_gaps: Array<{ field: string; reason: string; owner_domain: string }>;
  data_footnotes: Array<{ code: string; note: string; owner_domain: string; source_refs: string[] }>;
  source_refs: string[];
  boundary_note: string;
  confidence_label: "grounded" | "partial" | "fallback" | "data_quality_hold";
  limitations: string[];
}

export interface MvpAgentReviewSummaryResponse {
  summary: MvpAgentReviewSummary | null;
  trace: {
    provider: string;
    fallback: boolean;
    reason: string | null;
    validation_errors: string[];
    fallback_validation_errors?: string[];
    materialization?: {
      summary_id: string | null;
      summary_key: string;
      workflow_run_id: string | null;
      status: "ready" | "fallback" | "failed" | "stale" | "pending";
      reused: boolean;
      source_sha256: string;
      context_sha256: string | null;
      prompt_version: string;
      model_version: string;
      generated_at: string | null;
      created_at: string | null;
      updated_at: string | null;
      fallback_reason?: string | null;
    };
    workflow_run?: {
      workflow_run_id: string;
      trigger: string;
      engine: string;
      status: "running" | "completed" | "partial" | "failed";
      started_at: string;
      completed_at: string | null;
      updated_at: string;
      summary_key: string;
      source_sha256: string;
      context_sha256: string;
      error_type: string | null;
      error_message: string | null;
    };
  };
}

export interface MvpAgentReviewWorkflowRun {
  workflow_run_id: string;
  trigger: string;
  engine: string;
  status: "running" | "completed" | "partial" | "failed";
  started_at: string;
  completed_at: string | null;
  updated_at: string;
  asset_id: string | null;
  event_id: string | null;
  dataset_version_id: string | null;
  history_window: string | null;
  summary_key: string;
  source_sha256: string;
  context_sha256: string;
  error_type: string | null;
  error_message: string | null;
  trace: {
    stage?: string;
    materialization?: Record<string, unknown>;
    provider?: string | null;
    fallback?: boolean | null;
    reason?: string | null;
    validation_errors?: string[];
  };
}

export interface MvpAgentReviewWorkflowRunsResponse {
  project_id: string;
  workspace_id: string;
  items: MvpAgentReviewWorkflowRun[];
}

export interface MvpEventDetailModel {
  snapshotBasis: MvpEvidenceSnapshotBasis | null;
  event: MvpEvent;
  sensors: MvpSensorValue[];
  topFactors: MvpFactor[];
  riskSeries: MvpRiskSeriesPoint[];
  predictionHorizonHours: number | null;
  threshold: number | null;
  assetCriticality: MvpCriticality;
  criticalityBasis: string[];
  criticalitySource: "manual_initial_assessment" | "equipment_master" | "project_context" | "unknown";
  maintenanceContext: {
    lastMaintenanceDaysAgo: number | null;
    similarEvents30d: number | null;
    openWorkOrderExists: boolean | null;
  } | null;
  inspectionTargets: MvpInspectionTarget[];
  dataQualityWarnings: Array<{ code: string; field: string; message: string; severity: string }>;
  equipmentHistory: MvpEquipmentHistoryItem[];
  evidenceGaps: MvpEvidenceGap[];
  assetDetailStatus: MvpAssetDetailStatus | null;
  operationContext: MvpOperationContext | null;
  closedLoop: MvpClosedLoopSummary | null;
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
  snapshot_basis: EvidenceSnapshotBasisWire;
  asset: {
    asset_id: string;
    asset_type: "compressor" | "cnc";
    display_name?: string;
    site_id?: string;
    cell_id?: string;
    observed_at: string;
    criticality: MvpCriticality;
    criticality_basis: string[];
    criticality_source: "manual_initial_assessment" | "equipment_master" | "project_context" | "unknown";
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
      window?: {
        requested: MvpSensorWindowId;
        anchor_observed_at: string | null;
        requested_start: string | null;
        requested_end: string | null;
        actual_start: string | null;
        actual_end: string | null;
        point_count: number;
        coverage_status: MvpSensorWindowCoverage;
      };
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
  maintenance_context: {
    last_maintenance_days_ago: number | null;
    similar_events_30d: number | null;
    open_work_order_exists: boolean | null;
  };
  inspection_targets?: Array<{
    target_id: string;
    component_id: string;
    component_label: string;
    association: string;
    location_label: string | null;
    inspection_method: string | null;
    location_contract_id: string | null;
    location_source_ref: string | null;
    location_maturity: "fixture" | "draft" | "approved" | "retired" | null;
    inspection_guidance?: {
      source_type: "demo_sop_fixture" | "site_sop";
      sop_id: string;
      title: string;
      version: string;
      reference_location_label: string;
      suggested_check_method: string;
      checklist_draft: string[];
      maintenance_review_prerequisites: {
        label: string;
        review_conditions: string[];
        required_measurements: string[];
        human_review_questions: string[];
        decision_boundary: string;
      };
      safety_level: "none" | "caution" | "permit_required" | "shutdown_controlled";
      requires_human_approval: boolean;
      source_ref: string;
      disclaimer: string;
    };
    basis_refs: string[];
    source_ref: string;
    unavailable_reason: string | null;
  }>;
  operation_context: {
    load_level: "low" | "normal" | "high" | null;
    runtime_hours_7d: number | null;
    production_impact: MvpProductionImpact;
    context_id?: string;
    source_type?: MvpOperationSourceType;
    temporal_scope?: {
      snapshot_id: string;
      timezone: string;
      valid_from: string;
      valid_to: string;
      generated_at: string;
    };
    production_plan?: {
      plan_id: string;
      plan_date: string;
      planned_units: number;
      product_mix: Array<{ variant: string; share: number; planned_units: number }>;
    };
    capacity_model?: {
      active_asset_count: number;
      planned_operating_hours: number;
      oee: number;
      standard_cycle_minutes_per_unit: number;
      asset_units_per_hour: number;
      daily_capacity_units: number;
      basis: string;
    };
    event_impact?: {
      event_id: string;
      equipment_id: string;
      line: string;
      product_variant: string;
      screen_priority: MvpScreenPriority;
      impact_status: MvpImpactStatus;
      estimated_lost_units: number | null;
      basis: {
        estimated_downtime_minutes: number;
        asset_units_per_hour: number;
        formula: string;
      };
    } | null;
    limitations?: string[];
  };
  closed_loop?: {
    work_orders?: Array<{
      work_order_id: string;
      work_type: MvpClosedLoopWorkType;
      status: MvpClosedLoopWorkOrderStatus;
      assigned_to?: string | null;
      actor_display_name?: string | null;
      created_at?: string | null;
      updated_at?: string | null;
    }>;
    maintenance_actions?: Array<{
      maintenance_action_id: string;
      work_order_id?: string | null;
      status: MvpClosedLoopMaintenanceActionStatus;
      actor_display_name?: string | null;
      started_at?: string | null;
      completed_at?: string | null;
    }>;
    maintenance_events?: Array<{
      maintenance_event_id: string;
      maintenance_action_id?: string | null;
      work_order_id?: string | null;
      completed_at?: string | null;
      actor_display_name?: string | null;
    }>;
    activities?: Array<{
      activity_id: string;
      activity_type: string;
      work_type?: MvpClosedLoopWorkType | null;
      actor_display_name?: string | null;
      before_status?: string | null;
      after_status?: string | null;
      created_at?: string | null;
      work_order_id?: string | null;
      maintenance_action_id?: string | null;
      maintenance_event_id?: string | null;
    }>;
    inspection_results?: Array<Record<string, unknown>>;
    available_actions?: Array<{
      action_id: string;
      target_type: "recommendation" | "work_order" | "maintenance_action" | "inspection_result" | "event";
      target_id?: string | null;
      label?: string;
      disabled_reason?: string | null;
    }>;
    lifecycle_summary?: {
      current_step: MvpClosedLoopLifecycleStep;
      current_step_label: string;
      completed_steps: MvpClosedLoopLifecycleStep[];
      next_step?: MvpClosedLoopLifecycleStep | null;
      source: "backend_closed_loop_policy";
    } | null;
    primary_action?: {
      action_id: string;
      target_type: "recommendation" | "work_order" | "maintenance_action" | "inspection_result" | "event";
      target_id?: string | null;
      label: string;
      owner_role: "process_manager" | "process_engineer" | "maintenance_technician" | "unassigned";
      owner_label: string;
      disabled_reason?: string | null;
      requires_input: boolean;
    } | null;
    timeline?: Array<{
      timeline_id: string;
      event_type: string;
      label: string;
      status: "completed" | "pending" | "blocked" | "failed";
      actor_display_name?: string | null;
      occurred_at?: string | null;
      target_type?: string | null;
      target_id?: string | null;
    }>;
    runtime_status?: MvpClosedLoopRuntimeStatus;
  } | null;
  review_priority: {
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
  dashboard: MvpDashboardMode;
  reportTab: MvpReportTab;
  projectId: string;
  workspaceId: string | null;
  assetId: string | null;
  eventId: string | null;
  role: MvpRoleLens;
}

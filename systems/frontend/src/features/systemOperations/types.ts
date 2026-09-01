export type RegistryStatus = "verified" | "discovered" | "invalid" | "conflicted" | "drifted" | "unavailable";
export type ValidationStatus = "valid" | "invalid" | "not_validated";

export interface OperationalAssetDependency {
  asset_type: string;
  asset_key: string;
  version: string;
  resolved_asset_id?: string | null;
  resolved_version_id?: string | null;
  resolution_status?: "resolved" | "missing" | "version_missing" | "unavailable";
}

export interface OperationalAssetVersion {
  id: string;
  version: string;
  registry_status: RegistryStatus;
  lifecycle_status?: string | null;
  logical_uri: string;
  sha256: string;
  schema_id?: string | null;
  schema_version?: string | null;
  content_type: string;
  size_bytes: number;
  is_active: boolean;
  pointer_ref?: string | null;
  validation_status: ValidationStatus;
  validation_errors: string[];
  dependencies: OperationalAssetDependency[];
  first_seen_at: string;
  last_seen_at: string;
}

export interface OperationalAssetSummary {
  id: string;
  source_system: string;
  asset_type: string;
  asset_key: string;
  current_version?: string;
  registry_status?: RegistryStatus;
  lifecycle_status?: string | null;
  validation_status?: ValidationStatus;
  active?: boolean;
  logical_uri?: string;
  sha256?: string;
  schema_id?: string | null;
  schema_version?: string | null;
  last_seen_at?: string;
  created_at: string;
  updated_at: string;
}

export interface OperationalAssetDetail extends OperationalAssetSummary {
  versions: OperationalAssetVersion[];
}

export interface OperationalAssetListResponse { items: OperationalAssetSummary[]; total: number }
export interface LatestReconciliation {
  id: string;
  source_system: string;
  status: string;
  asset_count: number;
  verified_count: number;
  invalid_count: number;
  conflicted_count: number;
  started_at: string;
  completed_at: string;
  snapshot_sha256: string;
}

export interface MappingFieldDefinition {
  source_field: string;
  target_field: string;
  source_type: "float" | "int" | "string" | "bool" | "number";
  target_type: "float" | "int" | "string" | "bool" | "datetime";
  required: boolean;
  transform: string;
  unit?: string;
  timezone?: string;
}

export interface MappingDraft {
  draft_id: string;
  mapping_id: string;
  target_version: string;
  base_version?: string | null;
  revision: number;
  status: string;
  payload: Record<string, unknown> & { field_mappings?: MappingFieldDefinition[] };
  payload_sha256: string;
  validation_status: string;
  validation_errors: Array<{ code?: string; message?: string; path?: Array<string | number> }>;
  validated_revision?: number | null;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
  published_at?: string | null;
  published_sha256?: string | null;
  publish_error_code?: string | null;
  publish_error_message?: string | null;
}

export interface MappingDraftDiff {
  draft_id: string;
  base_version?: string | null;
  target_version: string;
  summary: { added: number; removed: number; changed: number };
  changes: Array<Record<string, unknown>>;
}

export interface SystemPipelineJob {
  job_id: string;
  job_type: "mapping_rebuild" | "downstream_rebuild";
  status: "queued" | "running" | "checkpointed" | "cancel_requested" | "succeeded" | "partially_succeeded" | "failed" | "cancelled";
  mapping_id: string;
  mapping_version: string;
  mapping_sha256: string;
  source_uri: string;
  activate_on_success: boolean;
  progress: Record<string, unknown>;
  checkpoint?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  error?: { code: string; message: string } | null;
  cancel_requested: boolean;
  created_by: string;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  steps?: SystemPipelineJobStep[];
}

export interface SystemPipelineJobStep {
  step_id: string;
  action_id: string;
  stage: "preprocessing" | "feature" | "training";
  sequence: number;
  status: "pending" | "ready" | "running" | "succeeded" | "failed" | "blocked" | "skipped" | "cancelled";
  input: Record<string, unknown>;
  output?: Record<string, unknown> | null;
  error?: { code: string; message: string } | null;
}

export interface SystemImpactAction {
  action_id: string;
  stage: "preprocessing" | "feature" | "training";
  status: "recommended" | "blocked";
  required_parameters: Record<string, unknown>;
  missing_parameters: string[];
  depends_on_action_ids: string[];
}

export interface SystemImpactAnalysis {
  analysis_id: string;
  status: string;
  mapping_id: string;
  mapping_version: string;
  mapping_sha256: string;
  rebuild_job_id: string;
  snapshot_sha256: string;
  recommended_actions: SystemImpactAction[];
  blocked_actions: SystemImpactAction[];
  created_at: string;
}

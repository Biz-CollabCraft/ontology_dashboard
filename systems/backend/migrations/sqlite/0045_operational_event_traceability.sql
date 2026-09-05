-- Supplemental traceability layer for reconstructing one operational incident
-- across prediction, decision, field work, maintenance, and reassessment.
-- The source fact tables remain authoritative; these rows are read-model
-- checkpoints keyed by event_id and workflow_run_id.

CREATE TABLE IF NOT EXISTS operational_event_trace_snapshots (
  trace_snapshot_id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  workflow_run_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  prediction_result_id TEXT,
  recommendation_id TEXT,
  work_order_id TEXT,
  maintenance_action_id TEXT,
  maintenance_event_id TEXT,
  source_export_checkpoint_id TEXT,
  as_of TEXT NOT NULL,
  model_version TEXT,
  source_hash TEXT,
  context_hash TEXT,
  used_evidence_json TEXT NOT NULL,
  excluded_evidence_json TEXT NOT NULL,
  limitations_json TEXT NOT NULL,
  reassessment_status TEXT NOT NULL CHECK(reassessment_status IN (
    'pending',
    'maintenance_completed',
    'observation_pending',
    're_prediction_requested',
    'new_decision_created'
  )),
  created_at TEXT NOT NULL,
  UNIQUE(
    organization_id,
    project_id,
    workspace_id,
    event_id,
    workflow_run_id,
    prediction_result_id
  )
);
CREATE INDEX IF NOT EXISTS idx_operational_event_trace_snapshots_event
  ON operational_event_trace_snapshots(
    organization_id,
    project_id,
    workspace_id,
    event_id,
    as_of
  );
CREATE INDEX IF NOT EXISTS idx_operational_event_trace_snapshots_workflow
  ON operational_event_trace_snapshots(
    organization_id,
    project_id,
    workspace_id,
    workflow_run_id,
    as_of
  );

CREATE TABLE IF NOT EXISTS operational_event_trace_status_changes (
  trace_status_change_id TEXT PRIMARY KEY,
  organization_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  workflow_run_id TEXT NOT NULL,
  source_activity_id TEXT,
  actor_user_id TEXT,
  actor_display_name TEXT NOT NULL,
  action_type TEXT NOT NULL,
  before_status TEXT,
  after_status TEXT,
  reason TEXT NOT NULL,
  related_recommendation_id TEXT,
  related_work_order_id TEXT,
  related_maintenance_action_id TEXT,
  related_maintenance_event_id TEXT,
  related_export_checkpoint_id TEXT,
  created_at TEXT NOT NULL,
  UNIQUE(organization_id,project_id,workspace_id,source_activity_id)
);
CREATE INDEX IF NOT EXISTS idx_operational_event_trace_status_changes_event
  ON operational_event_trace_status_changes(
    organization_id,
    project_id,
    workspace_id,
    event_id,
    created_at
  );
CREATE INDEX IF NOT EXISTS idx_operational_event_trace_status_changes_workflow
  ON operational_event_trace_status_changes(
    organization_id,
    project_id,
    workspace_id,
    workflow_run_id,
    created_at
  );

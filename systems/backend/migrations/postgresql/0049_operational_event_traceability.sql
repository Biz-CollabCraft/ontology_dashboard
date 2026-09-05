-- Supplemental traceability layer for reconstructing one operational incident
-- across prediction, decision, field work, maintenance, and reassessment.
-- The source fact tables remain authoritative; these rows are read-model
-- checkpoints keyed by event_id and workflow_run_id.

CREATE TABLE IF NOT EXISTS operational_event_trace_snapshots (
  trace_snapshot_id text PRIMARY KEY,
  organization_id text NOT NULL,
  project_id text NOT NULL,
  workspace_id text NOT NULL,
  event_id text NOT NULL,
  workflow_run_id text NOT NULL,
  asset_id text NOT NULL,
  prediction_result_id text,
  recommendation_id text,
  work_order_id text,
  maintenance_action_id text,
  maintenance_event_id text,
  source_export_checkpoint_id text,
  as_of timestamptz NOT NULL,
  model_version text,
  source_hash text,
  context_hash text,
  used_evidence_json jsonb NOT NULL,
  excluded_evidence_json jsonb NOT NULL,
  limitations_json jsonb NOT NULL,
  reassessment_status text NOT NULL CHECK(reassessment_status IN (
    'pending',
    'maintenance_completed',
    'observation_pending',
    're_prediction_requested',
    'new_decision_created'
  )),
  created_at timestamptz NOT NULL,
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
  trace_status_change_id text PRIMARY KEY,
  organization_id text NOT NULL,
  project_id text NOT NULL,
  workspace_id text NOT NULL,
  event_id text NOT NULL,
  workflow_run_id text NOT NULL,
  source_activity_id text,
  actor_user_id text,
  actor_display_name text NOT NULL,
  action_type text NOT NULL,
  before_status text,
  after_status text,
  reason text NOT NULL,
  related_recommendation_id text,
  related_work_order_id text,
  related_maintenance_action_id text,
  related_maintenance_event_id text,
  related_export_checkpoint_id text,
  created_at timestamptz NOT NULL,
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

ALTER TABLE operational_event_trace_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE operational_event_trace_status_changes ENABLE ROW LEVEL SECURITY;

DO $$ DECLARE t text; BEGIN FOREACH t IN ARRAY ARRAY[
  'operational_event_trace_snapshots',
  'operational_event_trace_status_changes'
] LOOP
EXECUTE format('DROP POLICY IF EXISTS %I_tenant ON %I',t,t);
EXECUTE format($p$CREATE POLICY %I_tenant ON %I USING (organization_id=current_setting('app.organization_id',true) AND project_id=current_setting('app.project_id',true)) WITH CHECK (organization_id=current_setting('app.organization_id',true) AND project_id=current_setting('app.project_id',true))$p$,t,t); END LOOP; END $$;

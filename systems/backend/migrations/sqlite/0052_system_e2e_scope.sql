ALTER TABLE system_e2e_runs ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE system_e2e_runs ADD COLUMN project_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE system_e2e_runs ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE system_e2e_timeline_events ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE system_e2e_timeline_events ADD COLUMN project_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE system_e2e_timeline_events ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE dashboard_anomaly_alerts ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE dashboard_anomaly_alerts ADD COLUMN project_id TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE dashboard_anomaly_alerts ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'legacy';

CREATE INDEX IF NOT EXISTS idx_system_e2e_runs_scope
  ON system_e2e_runs(organization_id,project_id,workspace_id,started_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_e2e_events_scope
  ON system_e2e_timeline_events(organization_id,project_id,workspace_id,occurred_at);
CREATE INDEX IF NOT EXISTS idx_dashboard_alerts_scope
  ON dashboard_anomaly_alerts(organization_id,project_id,workspace_id,observed_at DESC);

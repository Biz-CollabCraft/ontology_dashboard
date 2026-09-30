CREATE TABLE IF NOT EXISTS decision_agent_runs (
 decision_session_id TEXT PRIMARY KEY,
 organization_id TEXT NOT NULL,
 project_id TEXT NOT NULL,
 identity_hash TEXT NOT NULL,
 binding TEXT NOT NULL,
 state_json TEXT NOT NULL,
 lease_owner TEXT,
 lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
 updated_at DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_agent_runs_scope ON decision_agent_runs(organization_id,project_id,identity_hash);
ALTER TABLE decision_agent_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY decision_agent_runs_scope ON decision_agent_runs
 USING (organization_id=current_setting('app.organization_id',true) AND project_id=current_setting('app.project_id',true))
 WITH CHECK (organization_id=current_setting('app.organization_id',true) AND project_id=current_setting('app.project_id',true));

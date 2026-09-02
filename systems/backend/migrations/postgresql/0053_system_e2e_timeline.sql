CREATE TABLE IF NOT EXISTS system_e2e_runs (
  run_id TEXT PRIMARY KEY, status TEXT NOT NULL, source_uri TEXT,
  source_sha256 TEXT, batch_id TEXT, asset_ids_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  started_at TIMESTAMPTZ NOT NULL, completed_at TIMESTAMPTZ, error_code TEXT,
  retryable BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS system_e2e_timeline_events (
  timeline_event_id TEXT PRIMARY KEY, occurred_at TIMESTAMPTZ NOT NULL,
  stage TEXT NOT NULL, status TEXT NOT NULL, service TEXT NOT NULL, domain TEXT NOT NULL,
  request_id TEXT, run_id TEXT NOT NULL REFERENCES system_e2e_runs(run_id), job_id TEXT,
  event_id TEXT, asset_id TEXT, model_id TEXT, input_ref_json JSONB,
  output_ref_json JSONB, error_code TEXT, retryable BOOLEAN NOT NULL DEFAULT FALSE,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_system_e2e_runs_status ON system_e2e_runs(status, started_at);
CREATE INDEX IF NOT EXISTS idx_system_e2e_events_run ON system_e2e_timeline_events(run_id, occurred_at);

CREATE TABLE IF NOT EXISTS dashboard_anomaly_alerts (
  alert_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, asset_id TEXT NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
  headline TEXT NOT NULL, product_result_id TEXT NOT NULL, evidence_id TEXT,
  report_id TEXT, created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dashboard_alerts_asset ON dashboard_anomaly_alerts(asset_id, observed_at DESC);

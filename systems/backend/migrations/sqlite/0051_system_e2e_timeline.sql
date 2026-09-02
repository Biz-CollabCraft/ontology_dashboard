CREATE TABLE IF NOT EXISTS system_e2e_runs (
  run_id TEXT PRIMARY KEY, status TEXT NOT NULL, source_uri TEXT,
  source_sha256 TEXT, batch_id TEXT, asset_ids_json TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL, completed_at TEXT, error_code TEXT, retryable INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS system_e2e_timeline_events (
  timeline_event_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, stage TEXT NOT NULL,
  status TEXT NOT NULL, service TEXT NOT NULL, domain TEXT NOT NULL,
  request_id TEXT, run_id TEXT NOT NULL, job_id TEXT, event_id TEXT,
  asset_id TEXT, model_id TEXT, input_ref_json TEXT, output_ref_json TEXT,
  error_code TEXT, retryable INTEGER NOT NULL DEFAULT 0, metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(run_id) REFERENCES system_e2e_runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_system_e2e_runs_status ON system_e2e_runs(status, started_at);
CREATE INDEX IF NOT EXISTS idx_system_e2e_events_run ON system_e2e_timeline_events(run_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_system_e2e_events_correlation ON system_e2e_timeline_events(request_id, job_id, event_id);

CREATE TABLE IF NOT EXISTS dashboard_anomaly_alerts (
  alert_id TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE, asset_id TEXT NOT NULL,
  observed_at TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
  headline TEXT NOT NULL, product_result_id TEXT NOT NULL, evidence_id TEXT,
  report_id TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dashboard_alerts_asset ON dashboard_anomaly_alerts(asset_id, observed_at DESC);

CREATE TABLE IF NOT EXISTS system_audit_events (
  audit_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, actor_id TEXT NOT NULL,
  actor_type TEXT NOT NULL, action TEXT NOT NULL, resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL, resource_version TEXT, outcome TEXT NOT NULL,
  request_id TEXT NOT NULL, run_id TEXT, job_id TEXT, event_id TEXT,
  reason TEXT, error_code TEXT, before_ref_json TEXT, after_ref_json TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_system_audit_time ON system_audit_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_system_audit_actor ON system_audit_events(actor_id);
CREATE INDEX IF NOT EXISTS idx_system_audit_action ON system_audit_events(action);
CREATE INDEX IF NOT EXISTS idx_system_audit_resource ON system_audit_events(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_system_audit_correlation ON system_audit_events(request_id, run_id, job_id, event_id);

CREATE TABLE IF NOT EXISTS system_operational_logs (
  log_id TEXT PRIMARY KEY, occurred_at TEXT NOT NULL, service TEXT NOT NULL,
  domain TEXT NOT NULL, severity TEXT NOT NULL, message TEXT NOT NULL,
  error_code TEXT, request_id TEXT, run_id TEXT, job_id TEXT, event_id TEXT,
  asset_id TEXT, model_id TEXT, metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_system_logs_time ON system_operational_logs(occurred_at);
CREATE INDEX IF NOT EXISTS idx_system_logs_dimensions ON system_operational_logs(service, domain, severity, error_code);
CREATE INDEX IF NOT EXISTS idx_system_logs_correlation ON system_operational_logs(request_id, run_id, job_id, event_id);

CREATE TABLE IF NOT EXISTS system_log_exports (
  export_id TEXT PRIMARY KEY, requested_by TEXT NOT NULL, status TEXT NOT NULL,
  format TEXT NOT NULL, filters_json TEXT NOT NULL, record_count INTEGER NOT NULL DEFAULT 0,
  truncated INTEGER NOT NULL DEFAULT 0, logical_uri TEXT, sha256 TEXT,
  error_code TEXT, created_at TEXT NOT NULL, completed_at TEXT
);

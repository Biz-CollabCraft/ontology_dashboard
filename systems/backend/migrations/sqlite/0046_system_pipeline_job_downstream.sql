PRAGMA foreign_keys=OFF;

CREATE TABLE system_pipeline_jobs_v2 (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL CHECK(job_type IN ('mapping_rebuild','downstream_rebuild')),
    status TEXT NOT NULL CHECK(status IN ('queued','running','checkpointed','cancel_requested','succeeded','partially_succeeded','failed','cancelled')),
    request_id TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL,
    mapping_id TEXT NOT NULL, mapping_version TEXT NOT NULL, mapping_sha256 TEXT NOT NULL,
    source_uri TEXT NOT NULL, source_identity TEXT, replay_scope TEXT NOT NULL,
    activate_on_success INTEGER NOT NULL CHECK(activate_on_success IN (0,1)),
    progress_json TEXT NOT NULL DEFAULT '{}', checkpoint_json TEXT, result_json TEXT,
    error_code TEXT, error_message TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
    created_by TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, heartbeat_at TEXT,
    completed_at TEXT, lease_owner TEXT, lease_expires_at TEXT
);

INSERT INTO system_pipeline_jobs_v2 SELECT * FROM system_pipeline_jobs;
DROP TABLE system_pipeline_jobs;
ALTER TABLE system_pipeline_jobs_v2 RENAME TO system_pipeline_jobs;
CREATE INDEX idx_system_pipeline_jobs_status_created ON system_pipeline_jobs(status,created_at);
CREATE INDEX idx_system_pipeline_jobs_mapping_source ON system_pipeline_jobs(mapping_id,mapping_version,source_uri,status);

PRAGMA foreign_keys=ON;

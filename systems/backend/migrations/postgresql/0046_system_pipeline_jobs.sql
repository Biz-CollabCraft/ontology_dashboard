CREATE TABLE IF NOT EXISTS system_pipeline_jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL CHECK(job_type = 'mapping_rebuild'),
    status TEXT NOT NULL CHECK(status IN ('queued','running','checkpointed','cancel_requested','succeeded','failed','cancelled')),
    request_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    mapping_id TEXT NOT NULL,
    mapping_version TEXT NOT NULL,
    mapping_sha256 TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    source_identity TEXT,
    replay_scope TEXT NOT NULL CHECK(replay_scope = 'full_source'),
    activate_on_success BOOLEAN NOT NULL,
    progress_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint_json JSONB,
    result_json JSONB,
    error_code TEXT,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    lease_owner TEXT,
    lease_expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_system_pipeline_jobs_status_created
    ON system_pipeline_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_system_pipeline_jobs_mapping_source
    ON system_pipeline_jobs(mapping_id, mapping_version, source_uri, status);

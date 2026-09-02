CREATE TABLE IF NOT EXISTS system_model_selection_history (
    selection_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    from_model_version TEXT,
    to_model_version TEXT,
    from_manifest_sha256 TEXT,
    to_manifest_sha256 TEXT,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    request_id TEXT,
    status TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_system_model_selection_model ON system_model_selection_history(model_id, created_at DESC);

CREATE TABLE IF NOT EXISTS system_active_model_set_revisions (
    revision_id TEXT PRIMARY KEY,
    model_set_id TEXT NOT NULL,
    model_set_version TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    previous_revision_id TEXT,
    status TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    activated_at TIMESTAMPTZ,
    error_code TEXT,
    error_message TEXT,
    payload_json JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_system_model_set_revision ON system_active_model_set_revisions(model_set_id, created_at DESC);

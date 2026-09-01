CREATE TABLE IF NOT EXISTS system_mapping_drafts (
    id TEXT PRIMARY KEY,
    mapping_id TEXT NOT NULL,
    target_version TEXT NOT NULL,
    base_version TEXT,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    validation_errors_json TEXT NOT NULL,
    validated_revision INTEGER,
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    published_sha256 TEXT,
    publish_error_code TEXT,
    publish_error_message TEXT,
    UNIQUE(mapping_id, target_version)
);

CREATE INDEX IF NOT EXISTS idx_system_mapping_drafts_status ON system_mapping_drafts(status, updated_at);

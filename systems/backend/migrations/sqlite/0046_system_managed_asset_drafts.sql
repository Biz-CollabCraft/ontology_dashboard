CREATE TABLE IF NOT EXISTS system_managed_asset_drafts (
    draft_id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL CHECK(asset_type IN ('preprocessing_plan','feature_schema','label_schema','history_requirement','training_config')),
    asset_id TEXT NOT NULL,
    target_version TEXT NOT NULL,
    base_version TEXT,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    status TEXT NOT NULL CHECK(status IN ('draft','validated','validation_failed','publishing','published','publish_failed')),
    payload_json TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK(validation_status IN ('not_validated','valid','invalid')),
    validation_errors_json TEXT NOT NULL DEFAULT '[]',
    validation_warnings_json TEXT NOT NULL DEFAULT '[]',
    validated_revision INTEGER,
    created_by TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT,
    published_sha256 TEXT,
    publish_error_code TEXT,
    publish_error_message TEXT,
    UNIQUE(asset_type,asset_id,target_version)
);
CREATE INDEX IF NOT EXISTS idx_system_managed_asset_drafts_updated
    ON system_managed_asset_drafts(asset_type,status,updated_at);

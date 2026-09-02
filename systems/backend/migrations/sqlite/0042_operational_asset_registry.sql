CREATE TABLE IF NOT EXISTS operational_assets (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    asset_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_system, asset_type, asset_key)
);

CREATE TABLE IF NOT EXISTS operational_asset_versions (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES operational_assets(id),
    version TEXT NOT NULL,
    registry_status TEXT NOT NULL,
    lifecycle_status TEXT,
    logical_uri TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    schema_id TEXT,
    schema_version TEXT,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 0,
    pointer_ref TEXT,
    validation_status TEXT NOT NULL,
    validation_errors_json TEXT NOT NULL,
    dependencies_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(asset_id, version)
);

CREATE TABLE IF NOT EXISTS operational_asset_reconciliations (
    id TEXT PRIMARY KEY,
    source_system TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    asset_count INTEGER NOT NULL,
    verified_count INTEGER NOT NULL,
    invalid_count INTEGER NOT NULL,
    conflicted_count INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operational_assets_type_key ON operational_assets(asset_type, asset_key);
CREATE INDEX IF NOT EXISTS idx_operational_asset_versions_status ON operational_asset_versions(registry_status, is_active);

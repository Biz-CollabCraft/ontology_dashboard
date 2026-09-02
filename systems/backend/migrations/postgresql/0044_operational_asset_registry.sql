CREATE TABLE IF NOT EXISTS operational_assets (
    id text PRIMARY KEY,
    source_system text NOT NULL,
    asset_type text NOT NULL,
    asset_key text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE(source_system, asset_type, asset_key)
);

CREATE TABLE IF NOT EXISTS operational_asset_versions (
    id text PRIMARY KEY,
    asset_id text NOT NULL REFERENCES operational_assets(id),
    version text NOT NULL,
    registry_status text NOT NULL,
    lifecycle_status text,
    logical_uri text NOT NULL,
    sha256 text NOT NULL,
    schema_id text,
    schema_version text,
    content_type text NOT NULL,
    size_bytes bigint NOT NULL,
    is_active boolean NOT NULL DEFAULT false,
    pointer_ref text,
    validation_status text NOT NULL,
    validation_errors_json jsonb NOT NULL,
    dependencies_json jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    UNIQUE(asset_id, version)
);

CREATE TABLE IF NOT EXISTS operational_asset_reconciliations (
    id text PRIMARY KEY,
    source_system text NOT NULL,
    snapshot_sha256 text NOT NULL UNIQUE,
    status text NOT NULL,
    asset_count integer NOT NULL,
    verified_count integer NOT NULL,
    invalid_count integer NOT NULL,
    conflicted_count integer NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operational_assets_type_key ON operational_assets(asset_type, asset_key);
CREATE INDEX IF NOT EXISTS idx_operational_asset_versions_status ON operational_asset_versions(registry_status, is_active);

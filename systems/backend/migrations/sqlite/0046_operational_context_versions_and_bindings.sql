-- Preserve legacy operational_context_snapshots; copy with the verified legacy importer.
CREATE TABLE operational_context_sources (
    source_context_id TEXT PRIMARY KEY,
    owner_domain TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    schema_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    source_updated_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_classification TEXT NOT NULL CHECK (source_classification IN ('synthetic_demo_context','owner_system')),
    max_age_seconds INTEGER NOT NULL CHECK (max_age_seconds >= 0),
    payload_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    UNIQUE (owner_domain,organization_id,project_id,workspace_id,asset_id,source_version),
    UNIQUE (source_context_id,organization_id,project_id),
    CHECK (valid_from < valid_to), CHECK (source_updated_at < valid_to)
);
CREATE TABLE operational_context_bindings (
    source_context_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    evidence_snapshot_id TEXT NOT NULL,
    binding_schema_version INTEGER NOT NULL CHECK (binding_schema_version = 1),
    payload_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    PRIMARY KEY (source_context_id,evidence_snapshot_id),
    FOREIGN KEY (source_context_id,organization_id,project_id)
        REFERENCES operational_context_sources(source_context_id,organization_id,project_id)
);
CREATE INDEX operational_context_sources_lookup_idx ON operational_context_sources
    (organization_id,project_id,workspace_id,asset_id,owner_domain,source_updated_at DESC,source_version DESC);

CREATE TRIGGER operational_context_sources_no_update BEFORE UPDATE ON operational_context_sources
BEGIN SELECT RAISE(ABORT,'Operational context records are immutable'); END;

CREATE TRIGGER operational_context_sources_no_delete BEFORE DELETE ON operational_context_sources
BEGIN SELECT RAISE(ABORT,'Operational context records are immutable'); END;

CREATE TRIGGER operational_context_bindings_no_update BEFORE UPDATE ON operational_context_bindings
BEGIN SELECT RAISE(ABORT,'Operational context records are immutable'); END;

CREATE TRIGGER operational_context_bindings_no_delete BEFORE DELETE ON operational_context_bindings
BEGIN SELECT RAISE(ABORT,'Operational context records are immutable'); END;

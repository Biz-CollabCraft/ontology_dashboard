CREATE TABLE operational_context_snapshots (
    owner_domain TEXT NOT NULL CHECK (owner_domain IN ('production','maintenance_readiness','quality_delivery','planning','impact_policy')),
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_updated_at TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    valid_to TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    source_classification TEXT NOT NULL CHECK (source_classification IN ('synthetic_demo_context','owner_system')),
    max_age_seconds INTEGER NOT NULL CHECK (max_age_seconds >= 0),
    evidence_snapshot_id TEXT,
    payload_json TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    PRIMARY KEY (owner_domain,organization_id,project_id,workspace_id,asset_id,source_version),
    CHECK (valid_from < valid_to), CHECK (source_updated_at < valid_to)
);
CREATE INDEX operational_context_snapshots_lookup_idx ON operational_context_snapshots
    (organization_id,project_id,workspace_id,asset_id,owner_domain,source_updated_at DESC,source_version DESC);

CREATE TRIGGER operational_context_snapshots_no_update BEFORE UPDATE ON operational_context_snapshots
BEGIN SELECT RAISE(ABORT,'Operational context snapshots are immutable'); END;
CREATE TRIGGER operational_context_snapshots_no_delete BEFORE DELETE ON operational_context_snapshots
BEGIN SELECT RAISE(ABORT,'Operational context snapshots are immutable'); END;

-- Schema only: no fixture data is injected into deployment databases.
CREATE TABLE operational_context_snapshots (
    owner_domain TEXT NOT NULL CHECK (owner_domain IN ('production','maintenance_readiness','quality_delivery','planning','impact_policy')),
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ NOT NULL,
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

ALTER TABLE operational_context_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE operational_context_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY operational_context_snapshots_scope ON operational_context_snapshots
USING (organization_id = nullif(current_setting('app.organization_id',true),'') AND project_id = nullif(current_setting('app.project_id',true),''))
WITH CHECK (organization_id = nullif(current_setting('app.organization_id',true),'') AND project_id = nullif(current_setting('app.project_id',true),''));
CREATE FUNCTION reject_operational_context_snapshot_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Operational context snapshots are immutable; insert a new source version'; END;
$$;
CREATE TRIGGER operational_context_snapshots_immutable BEFORE UPDATE OR DELETE ON operational_context_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_operational_context_snapshot_mutation();
